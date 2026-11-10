import os
import re
import html
import tempfile
import edge_tts
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL

VOICE_BY_LANGUAGE = {
    "ru": "ru-RU-DariyaNeural",
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


def clean_text_for_speech(text: str) -> str:
    """Convert Markdown-style assistant output into natural text for TTS."""
    text = html.unescape(text or "")

    # Do not read code blocks or image markup aloud.
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)

    # Keep the readable label of Markdown links, discard the URL.
    text = re.sub(r"\[([^\]]+)\]\((?:[^()]|\([^()]*\))*\)", r"\1", text)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)

    # Remove common Markdown formatting and list/heading markers.
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*|__(.*?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"\*(.*?)\*|_(.*?)_", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"~~(.*?)~~", r"\1", text)
    text = re.sub(r"[`*_~]", "", text)

    # Quotation marks are visual punctuation, not words to be spoken.
    text = re.sub(r'["“”„«»「」『』]', "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:!?])(?=\S)", r"\1 ", text)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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
    if any("\u0400" <= ch <= "\u04ff" for ch in lower):
        return "ru"
    return "en"


async def synthesize_speech(text: str, language: str | None = None) -> bytes:
    """Try the natural Edge voice first, then fall back to OpenAI TTS."""
    lang = language or detect_language(text)
    edge_voice = VOICE_BY_LANGUAGE.get(lang, VOICE_BY_LANGUAGE["ru"])
    speech_text = clean_text_for_speech(text)
    if not speech_text:
        raise ValueError("Нет текста для озвучивания")

    edge_error = None
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name
        await edge_tts.Communicate(
            text=speech_text,
            voice=edge_voice,
            rate="-5%",
            pitch="+2Hz",
        ).save(path)
        with open(path, "rb") as audio:
            result = audio.read()
        if result and len(result) > 128:
            return result
        raise RuntimeError("Edge TTS вернул пустое аудио")
    except Exception as exc:
        edge_error = exc
    finally:
        if path:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    # Fallback prevents Edge TTS outages from disabling voice replies.
    try:
        response = await _client_instance().audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=speech_text,
            response_format="mp3",
        )
        result = response.content
        if not result or len(result) <= 128:
            raise RuntimeError("OpenAI TTS вернул пустое аудио")
        return result
    except Exception as fallback_error:
        raise RuntimeError(
            f"Не удалось создать аудио: Edge TTS: {type(edge_error).__name__}; "
            f"резервный TTS: {type(fallback_error).__name__}"
        ) from fallback_error
