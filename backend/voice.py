import os
import re
import html
import tempfile
import logging
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL

logger = logging.getLogger("asel.voice")

# One TTS voice is deliberately used for Russian and Kazakh so Asel keeps
# the same recognizable vocal identity when the conversation changes language.
TTS_MODEL = "gpt-4o-mini-tts"
TTS_VOICE = "coral"
TTS_INSTRUCTIONS = (
    "You are voicing Asel, the same young adult female personal assistant in every language. "
    "Use one consistent, clearly feminine voice identity: warm, soft, gentle, bright, "
    "friendly and naturally lively. Speak the supplied text in its original language. "
    "For Russian, use fluent native-sounding Russian pronunciation and natural conversational "
    "intonation. For Kazakh, pronounce Kazakh words and sounds carefully and naturally; "
    "do not read Kazakh with a Russian accent. Keep a light feminine timbre, moderate pace "
    "and smooth connected speech. Avoid a low, husky, harsh, masculine, elderly, robotic, "
    "monotonous or exaggeratedly theatrical delivery. Do not imitate or impersonate any "
    "real person or celebrity. Preserve the same vocal identity across Russian and Kazakh."
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
    # 'language' remains accepted for backwards compatibility with existing callers.
    # The same voice is intentionally used regardless of language.
    speech_text = clean_text_for_speech(text)
    if not speech_text:
        raise ValueError("Нет текста для озвучивания")

    try:
        response = await _client_instance().audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=speech_text,
            instructions=TTS_INSTRUCTIONS,
            response_format="mp3",
        )
        result = response.content
        if result and len(result) > 128:
            logger.info("Asel unified TTS: %s/%s", TTS_MODEL, TTS_VOICE)
            return result
        raise RuntimeError("TTS вернул пустое аудио")
    except Exception as error:
        logger.exception("Asel unified TTS failed")
        raise RuntimeError(
            f"Не удалось создать озвучку Асель: {type(error).__name__}"
        ) from error
