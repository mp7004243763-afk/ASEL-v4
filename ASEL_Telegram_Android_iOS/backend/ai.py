from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, ASEL_SYSTEM_PROMPT
from db import get_history, add_message, memory_context

_client = None
def client():
    global _client
    if _client is None:
        if not OPENAI_API_KEY: raise RuntimeError("OPENAI_API_KEY не настроен")
        kwargs={"api_key":OPENAI_API_KEY}
        if OPENAI_BASE_URL: kwargs["base_url"]=OPENAI_BASE_URL
        _client=AsyncOpenAI(**kwargs)
    return _client

async def ask_asel(user_id: str, text: str) -> str:
    history=get_history(user_id,20)
    memories=memory_context(user_id)
    system=ASEL_SYSTEM_PROMPT
    if memories:
        system += "\n\nДОЛГОСРОЧНАЯ ПАМЯТЬ О ПОЛЬЗОВАТЕЛЕ (используй уместно, не перечисляй без просьбы):\n"+memories
    response=await client().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role":"system","content":system},*history,{"role":"user","content":text}],
        temperature=0.75)
    answer=(response.choices[0].message.content or "").strip()
    if not answer: answer="Жаным, не получилось сформировать ответ. Попробуй ещё раз."
    add_message(user_id,"user",text); add_message(user_id,"assistant",answer)
    return answer
