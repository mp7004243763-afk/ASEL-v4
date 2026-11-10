import os
import re
import html
import tempfile
import logging
import edge_tts
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL

logger = logging.getLogger("asel.voice")

# Edge TTS voices retained for Kazakh/English and as a Russian emergency fallback.
VOICE_BY_LANGUAGE = {
    "kk": "kk-KZ-AidaNeural",
    "en": "en-US-AriaNeural",
}
RU_FALLBACK_VOICE = "ru-RU-SvetlanaNeural"

# Russian voice direction: use the user's 2GIS Liza reference as a style target,
# not as a claim of cloning that proprietary voice.
RU_TTS_MODEL = "gpt-4o-mini-tts"
RU_TTS_VOICE = "coral"
RU_TTS_INSTRUCTIONS = (
    "Speak in natural, standard Russian with a distinctly feminine young-adult voice. "
    "The voice should feel warm, soft, gentle, bright and pleasant, like a friendly "
    "young personal assistant. Use clear native Russian pronunciation, smooth connected "
    "speech, natural conversational intonation and moderate pace. Keep the timbre light "
    "and feminine; avoid a low, husky, harsh, masculine or elderly-sounding voice. "
    "Avoid exaggerated acting, robotic rhythm, over-enunciation and foreign accent. "
    "Sound calm, affectionate and lively without becoming childish or breathy."
)

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
    text = re.sub(r"```[\\s\\S]*?```", " ", text)
    text = re.sub(r"!\\[([^\\]]*)\\]\\([^)]*\\)", r"\\1", text)
    text = re.sub(r"\\[([^\\]]+)\\]\\((?:[^()]|\\([^()]*\\))*\\)", r"\\1", text)
    text = re.sub(r"https?://\\S+|www\\.\\S+", " ", text)
    text = re.sub(r"^\\s{0,3}#{1,6}\\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\\s*[-*+]\\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\\s*>\\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\\*\\*(.*?)\\*\\*|__(.*?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"\\*(.*?)\\*|_(.*?)_", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"~~(.*?)~~", r"\\1", text)
    text = re.sub(r"[\`*_~]", "", text)
    text = re.sub(r'["“”„«»「」『』]', "", text)
    text = re.sub(r"\\s+([,.;:!?])", r"\\1", text)
    text = re.sub(r"([,;:!?])(?=\\S)", r"\\1 ", text)
    text = re.sub(r"\\n{2,}", ". ", text)
    text = re.sub(r"\\s+", " ", text)
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
    if any("\\u0400" <= ch <= "\\u04ff" for ch in lower):
        return "ru"
    return "en"


async def _edge_speech(speech_text: str, voice: str) -> bytes:
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name
        await edge_tts.Communicate(
            text=speech_text,
            voice=voice,
            rate="-8%",
            pitch="+1Hz",
        ).save(path)
        with open(path, "rb") as audio:
            result = audio.read()
        if not result or len(result) <= 128:
            raise RuntimeError("Edge TTS вернул пустое аудио")
        return result
    finally:
        if path:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass


async def synthesize_speech(text: str, language: str | None = None) -> bytes:
    lang = language or detect_language(text)
    speech_text = clean_text_for_speech(text)
    if not speech_text:
        raise ValueError("Нет текста для озвучивания")

    # Russian replies use one consistent expressive TTS engine and voice.
    # Do not silently fall back to the old Nova voice.
    if lang == "ru":
        try:
            response = await _client_instance().audio.speech.create(
                model=RU_TTS_MODEL,
                voice=RU_TTS_VOICE,
                input=speech_text,
                instructions=RU_TTS_INSTRUCTIONS,
                response_format="mp3",
            )
            result = response.content
            if result and len(result) > 128:
                logger.info("Russian TTS: %s/%s", RU_TTS_MODEL, RU_TTS_VOICE)
                return result
            raise RuntimeError("OpenAI TTS вернул пустое аудио")
        except Exception as primary_error:
            logger.exception("Primary Russian TTS failed; trying female Edge fallback")
            try:
                result = await _edge_speech(speech_text, RU_FALLBACK_VOICE)
                logger.warning("Russian TTS fallback used: %s", RU_FALLBACK_VOICE)
                return result
            except Exception as fallback_error:
                raise RuntimeError(
                    "Не удалось создать русскую озвучку: "
                    f"основной TTS: {type(primary_error).__name__}; "
                    f"резервный TTS: {type(fallback_error).__name__}"
                ) from fallback_error

    voice = VOICE_BY_LANGUAGE.get(lang, VOICE_BY_LANGUAGE["en"])
    return await _edge_speech(speech_text, voice)
