import os
import re
import html
import tempfile
import logging

import edge_tts
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL

logger = logging.getLogger("asel.voice")

# Microsoft Edge neural voices. Aida is not present in Microsoft's
# published kk-KZ voice catalogue; Aigul is the supported female Kazakh voice.
TTS_VOICES = {
    "ru": "ru-RU-DariyaNeural",
    "kk": "kk-KZ-AigulNeural",
    "en": "en-US-AriaNeural",
}
DEFAULT_LANGUAGE = "ru"

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
    text = re.sub(r"\x60{3}[\s\S]*?\x60{3}", " ", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\((?:[^()]|\([^()]*\))*\)", r"\1", text)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*|__(.*?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"\*(.*?)\*|_(.*?)_", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"~~(.*?)~~", r"\1", text)
    text = re.sub(r"[\x60*_~]", "", text)
    text = re.sub(r'["“”„«»「」『』]', "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:!?])(?=\S)", r"\1 ", text)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def detect_language(text: str, language: str | None = None) -> str:
    """Select the TTS locale from an explicit hint or the reply's script."""
    if language:
        hint = language.strip().lower().replace("_", "-")
        if hint.startswith(("kk", "kaz")) or "қазақ" in hint:
            return "kk"
        if hint.startswith(("en", "eng")):
            return "en"
        if hint.startswith(("ru", "rus")):
            return "ru"

    value = text or ""
    if re.search(r"[әғқңөұүһі]", value, flags=re.IGNORECASE):
        return "kk"

    words = set(re.findall(r"[а-яё]+", value.lower()))
    kazakh_markers = {
        "сәлем", "рақмет", "рахмет", "қалай", "жақсы", "үшін",
        "бұл", "сіз", "сен", "менің", "маған", "біз", "сізге",
        "керек", "жоқ", "ия", "иә", "жаным", "қазақша", "болды",
    }
    if words & kazakh_markers:
        return "kk"

    latin_count = len(re.findall(r"[a-z]", value, flags=re.IGNORECASE))
    cyrillic_count = len(re.findall(r"[а-яё]", value, flags=re.IGNORECASE))
    if latin_count > cyrillic_count:
        return "en"
    return DEFAULT_LANGUAGE


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


async def synthesize_speech(text: str, language: str | None = None) -> bytes:
    """Synthesize Asel's reply with the matching female Microsoft neural voice."""
    speech_text = clean_text_for_speech(text)
    if not speech_text:
        raise ValueError("Нет текста для озвучивания")

    lang = detect_language(speech_text, language)
    # If Microsoft's Dariya endpoint temporarily fails, fall back to the
    # previously working Russian female voice instead of returning text only.
    voices = [TTS_VOICES[lang]]
    if lang == "ru":
        voices.append("ru-RU-SvetlanaNeural")

    last_error = None
    for voice in voices:
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as output:
                temp_path = output.name

            communicate = edge_tts.Communicate(
                text=speech_text,
                voice=voice,
                rate="+0%",
                volume="+0%",
                pitch="+0Hz",
            )
            await communicate.save(temp_path)

            with open(temp_path, "rb") as audio_file:
                result = audio_file.read()

            if not result or len(result) <= 128:
                raise RuntimeError("Edge TTS вернул пустое аудио")

            logger.info("Asel Edge TTS selected language=%s voice=%s", lang, voice)
            return result
        except Exception as error:
            last_error = error
            logger.exception("Asel Edge TTS failed for voice %s", voice)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    logger.warning("Could not remove temporary TTS file: %s", temp_path)

    raise RuntimeError(
        f"Не удалось создать озвучку Асель: {type(last_error).__name__ if last_error else 'UnknownError'}"
    ) from last_error
