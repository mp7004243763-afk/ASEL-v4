import os
import tempfile
import edge_tts
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL

VOICE_BY_LANGUAGE = {
    "ru": "ru-RU-SvetlanaNeural",
    "kk": "kk-KZ-AidaNeural",
    "en": "en-US-AriaNeural",
}

_client = None

def _client_instance():
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY не настроен")
        kwargs = {"api_key": OPENAI_API_KEY}
        if OPENAI_BASE_URL:
            kwargs["base_url"] = OPENAI_BASE_URL
        _client = AsyncOpenAI(**kwargs)
    return _client

async def transcribe_audio(audio_bytes: bytes, filename: str = "voice.wav") -> str:
    suffix = os.path.splitext(filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(audio_bytes)
        f.flush()
        with open(f.name, "rb") as audio:
            result = await _client_instance().audio.transcriptions.create(
                model="whisper-1",
                file=audio,
            )
    return (getattr(result, "text", "") or "").strip()

def detect_language(text: str) -> str:
    lower = text.lower()
    if any(ch in lower for ch in "әғқңөұүһі"):
        return "kk"
    # A simple script-based fallback. The assistant's response language is
    # normally aligned with the transcript by its system prompt.
    if any("\u0400" <= ch <= "\u04ff" for ch in lower):
        return "ru"
    return "en"

async def synthesize_speech(text: str, language: str | None = None) -> bytes:
    lang = language or detect_language(text)
    voice = VOICE_BY_LANGUAGE.get(lang, VOICE_BY_LANGUAGE["ru"])
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        path = f.name
    try:
        await edge_tts.Communicate(text=text, voice=voice).save(path)
        with open(path, "rb") as audio:
            return audio.read()
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
