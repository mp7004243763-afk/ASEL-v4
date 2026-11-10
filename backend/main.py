import os, io, asyncio, secrets, logging
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from config import BOT_TOKEN, API_SECRET
from db import (init_db, add_memory, list_memories, delete_memory, add_reminder,
                list_reminders, due_reminders, mark_reminder_sent, delete_reminder,
                add_event, list_events, delete_event, create_link_code, redeem_link_code, get_history, database_status)
from ai import ask_asel
from voice import transcribe_audio, synthesize_speech

logger=logging.getLogger("asel")
telegram_app=None
reminder_task=None

class ChatRequest(BaseModel):
    user_id:str=Field(min_length=1,max_length=100)
    message:str=Field(min_length=1,max_length=12000)
class MemoryRequest(BaseModel):
    user_id:str=Field(min_length=1,max_length=100)
    content:str=Field(min_length=1,max_length=2000)
class ReminderRequest(BaseModel):
    user_id:str=Field(min_length=1,max_length=100)
    text:str=Field(min_length=1,max_length=1000)
    due_at:datetime
class EventRequest(BaseModel):
    user_id:str=Field(min_length=1,max_length=100)
    title:str=Field(min_length=1,max_length=300)
    starts_at:datetime
    ends_at:datetime|None=None
    notes:str=Field(default="",max_length=3000)
class LinkRequest(BaseModel):
    mobile_user_id:str=Field(min_length=1,max_length=100)
    code:str=Field(min_length=6,max_length=12)

def iso_utc(dt):
    if dt.tzinfo is None: raise HTTPException(400,"Дата должна содержать часовой пояс, например +05:00")
    return dt.astimezone(timezone.utc).isoformat()

def authorize(secret):
    if not secret or secret!=API_SECRET: raise HTTPException(401,"Unauthorized")

async def reminder_worker():
    while True:
        now=datetime.now(timezone.utc).isoformat()
        for item in due_reminders(now):
            try:
                if telegram_app and item.get("chat_id"):
                    await telegram_app.bot.send_message(chat_id=int(item["chat_id"]), text=f"⏰ Напоминание от Асель:\n{item['text']}")
                    mark_reminder_sent(item["id"],True)
                else: mark_reminder_sent(item["id"],False)
            except Exception:
                # Do not mark sent on transient delivery failure; retry next cycle.
                await asyncio.sleep(0.1)
        await asyncio.sleep(15)

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Сәлем! Я Асель 💫 Пиши, присылай голосовые. Команды: /remember, /memories, /remind, /today, /link.")
async def telegram_text(update:Update,context:ContextTypes.DEFAULT_TYPE):
    msg=update.effective_message; uid=str(update.effective_user.id)
    try:
        await context.bot.send_chat_action(update.effective_chat.id,"typing")
        await msg.reply_text(await ask_asel(uid,msg.text))
    except Exception: await msg.reply_text("Жаным, сейчас возникла техническая ошибка. Попробуй чуть позже.")
async def telegram_voice(update:Update,context:ContextTypes.DEFAULT_TYPE):
    msg=update.effective_message; uid=str(update.effective_user.id)
    try:
        await context.bot.send_chat_action(update.effective_chat.id,"typing")
        f=await context.bot.get_file(msg.voice.file_id)
        audio=bytes(await f.download_as_bytearray())
        transcript=await transcribe_audio(audio,"telegram_voice.ogg")
        if not transcript:
            await msg.reply_text("Жаным, не расслышала. Попробуй ещё раз."); return
        answer=await ask_asel(uid,transcript)
        await msg.reply_text(f"🎙 {transcript}\n\n{answer}")
        voice=await synthesize_speech(answer)
        await msg.reply_voice(voice=io.BytesIO(voice),filename="asel_reply.mp3")
    except Exception: await msg.reply_text("Жаным, с голосом сейчас техническая заминка. Попробуй позже.")

async def cmd_remember(update,context):
    content=" ".join(context.args).strip()
    if not content:
        await update.message.reply_text("Напиши так: /remember Любит крепкий кофе без сахара"); return
    mid=add_memory(str(update.effective_user.id),content)
    await update.message.reply_text(f"Запомнила 💜 Запись №{mid}. Посмотреть: /memories")
async def cmd_memories(update,context):
    rows=list_memories(str(update.effective_user.id))
    if not rows: await update.message.reply_text("Пока ничего не сохраняла в долгосрочную память."); return
    await update.message.reply_text("Что я помню:\n"+"\n".join(f"#{r['id']} — {r['content']}" for r in rows[:30]))
async def cmd_forget(update,context):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Формат: /forget 3"); return
    ok=delete_memory(str(update.effective_user.id),int(context.args[0]))
    await update.message.reply_text("Удалила эту запись." if ok else "Не нашла такую запись.")
async def cmd_remind(update,context):
    raw=" ".join(context.args)
    if "|" not in raw:
        await update.message.reply_text("Формат: /remind 2026-11-07T18:30+05:00 | Позвонить"); return
    datepart,txt=raw.split("|",1)
    try:
        dt=datetime.fromisoformat(datepart.strip())
        if dt.tzinfo is None: raise ValueError()
        rid=add_reminder(str(update.effective_user.id),txt.strip(),iso_utc(dt),str(update.effective_chat.id))
        await update.message.reply_text(f"Поставила напоминание №{rid} на {dt.isoformat()}.")
    except Exception: await update.message.reply_text("Не поняла дату. Используй ISO-формат с часовым поясом, например 2026-11-07T18:30+05:00.")
async def cmd_today(update,context):
    uid=str(update.effective_user.id)
    now=datetime.now().astimezone()
    start=now.astimezone(timezone.utc).isoformat()
    end=(now+timedelta(days=1)).astimezone(timezone.utc).isoformat()
    events=list_events(uid,start,end); reminders=list_reminders(uid)
    lines=["План на сегодня:"]
    lines += [f"📅 {e['starts_at']} — {e['title']}" for e in events] or ["📅 Событий пока нет."]
    todays=[r for r in reminders if r["due_at"][:10]==now.astimezone(timezone.utc).date().isoformat()]
    lines += [f"⏰ {r['due_at']} — {r['text']}" for r in todays]
    await update.message.reply_text("\n".join(lines))
async def cmd_link(update,context):
    code=f"{secrets.randbelow(900000)+100000}"
    expires=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
    create_link_code(str(update.effective_user.id),code,expires)
    await update.message.reply_text(f"Код привязки приложения: {code}\nОн действует 10 минут. Введи его в приложении ASEL.")

@asynccontextmanager
async def lifespan(app:FastAPI):
    global telegram_app,reminder_task
    init_db()
    if BOT_TOKEN:
        telegram_app=Application.builder().token(BOT_TOKEN).build()
        for command,handler in [
            ("start",start),("remember",cmd_remember),("memories",cmd_memories),
            ("forget",cmd_forget),("remind",cmd_remind),("today",cmd_today),("link",cmd_link)]:
            telegram_app.add_handler(CommandHandler(command,handler))
        telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,telegram_text))
        telegram_app.add_handler(MessageHandler(filters.VOICE,telegram_voice))
        await telegram_app.initialize(); await telegram_app.start(); await telegram_app.updater.start_polling()
    reminder_task=asyncio.create_task(reminder_worker())
    yield
    reminder_task.cancel()
    try: await reminder_task
    except asyncio.CancelledError: pass
    if telegram_app:
        await telegram_app.updater.stop(); await telegram_app.stop(); await telegram_app.shutdown()

app=FastAPI(title="ASEL API",version="0.7.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=False,
                   allow_methods=["GET","POST","DELETE"],allow_headers=["*"])

@app.get("/health")
async def health():
    try:
        db = database_status()
        return {"status": "ok", "service": "ASEL", "version": "0.7.0", "database": db}
    except Exception:
        logger.exception("Database health check failed")
        raise HTTPException(503, "Database unavailable")
@app.get("/api/history")
async def history(user_id:str,limit:int=100,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret)
    # Keep responses bounded; the database returns oldest-to-newest within the selected tail.
    limit=max(1,min(limit,200))
    return {"items":get_history(user_id,limit)}

@app.post("/api/chat")
async def chat(payload:ChatRequest,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret)
    try:
        reply=await ask_asel(payload.user_id,payload.message)
        audio_b64=""
        try:
            import base64
            audio_reply=await synthesize_speech(reply)
            audio_b64=base64.b64encode(audio_reply).decode("ascii")
        except Exception:
            logger.exception("TTS failed in /api/chat; returning text reply")
        return {"reply":reply,"audio_base64":audio_b64,"audio_mime":"audio/mpeg"}
    except RuntimeError as e: raise HTTPException(503,str(e))
    except Exception as e:
        logger.exception("AI provider error in /api/chat")
        raise HTTPException(502,"AI provider error") from e
@app.post("/api/voice")
async def voice_chat(file:UploadFile=File(...),user_id:str="mobile-owner",x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret); audio=await file.read()
    if not audio: raise HTTPException(400,"Пустая аудиозапись")
    if len(audio)>20*1024*1024: raise HTTPException(413,"Аудиофайл больше 20 МБ")
    try:
        transcript=await transcribe_audio(audio,file.filename or "voice.wav")
        if not transcript: raise HTTPException(422,"Не удалось распознать речь")
        reply=await ask_asel(user_id,transcript)
        import base64
        audio_b64=""
        try:
            audio_reply=await synthesize_speech(reply)
            audio_b64=base64.b64encode(audio_reply).decode("ascii")
        except Exception:
            logger.exception("TTS failed in /api/voice; returning transcript and text reply")
        return {"transcript":transcript,"reply":reply,"audio_base64":audio_b64,"audio_mime":"audio/mpeg"}
    except HTTPException: raise
    except RuntimeError as e: raise HTTPException(503,str(e))
    except Exception as e: raise HTTPException(502,f"Ошибка голосового сервиса: {type(e).__name__}")

@app.post("/api/memories")
async def remember(p:MemoryRequest,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret); mid=add_memory(p.user_id,p.content); return {"id":mid,"saved":True}
@app.get("/api/memories")
async def memories(user_id:str,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret); return {"items":list_memories(user_id)}
@app.delete("/api/memories/{memory_id}")
async def forget(memory_id:int,user_id:str,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret)
    if not delete_memory(user_id,memory_id): raise HTTPException(404,"Запись не найдена")
    return {"deleted":True}

@app.post("/api/reminders")
async def create_reminder(p:ReminderRequest,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret); rid=add_reminder(p.user_id,p.text,iso_utc(p.due_at))
    return {"id":rid,"saved":True,"delivery":"telegram_only_when_chat_id_is_linked"}
@app.get("/api/reminders")
async def reminders(user_id:str,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret); return {"items":list_reminders(user_id)}
@app.delete("/api/reminders/{reminder_id}")
async def remove_reminder(reminder_id:int,user_id:str,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret)
    if not delete_reminder(user_id,reminder_id): raise HTTPException(404,"Напоминание не найдено")
    return {"deleted":True}

@app.post("/api/events")
async def create_event(p:EventRequest,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret)
    start=iso_utc(p.starts_at); end=iso_utc(p.ends_at) if p.ends_at else None
    if p.ends_at and p.ends_at < p.starts_at: raise HTTPException(400,"Окончание раньше начала")
    eid=add_event(p.user_id,p.title,start,end,p.notes); return {"id":eid,"saved":True}
@app.get("/api/events")
async def events(user_id:str,start_at:datetime,end_at:datetime,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret)
    if end_at<=start_at: raise HTTPException(400,"end_at должен быть позже start_at")
    return {"items":list_events(user_id,iso_utc(start_at),iso_utc(end_at))}
@app.delete("/api/events/{event_id}")
async def remove_event(event_id:int,user_id:str,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret)
    if not delete_event(user_id,event_id): raise HTTPException(404,"Событие не найдено")
    return {"deleted":True}

@app.post("/api/link")
async def link_account(p:LinkRequest,x_asel_secret:str|None=Header(default=None)):
    authorize(x_asel_secret)
    if not redeem_link_code(p.mobile_user_id,p.code): raise HTTPException(400,"Код неверный или истёк")
    return {"linked":True,"message":"Мобильный аккаунт связан с Telegram"}
