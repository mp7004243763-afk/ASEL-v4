"""Optional Gemini TTS diagnostics for finding and previewing the requested Lyra voice.

This module does not change ASEL's active voice provider. It is only used by
secret-protected diagnostic endpoints until a voice ID is verified and audio
playback compatibility is tested.
"""
import base64
import os
from typing import Any

import httpx

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.8-flash-tts"


def _api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY не настроен в Render Environment")
    return key


async def list_gemini_voices(search: str = "Lyra") -> list[dict[str, Any]]:
    """Search Google's voice catalog; never expose the API key in errors."""
    params = {"type": "prebuilt", "search": search[:100], "pageSize": "50"}
    headers = {"x-goog-api-key": _api_key()}
    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.get(f"{API_ROOT}/voices", params=params, headers=headers)
    if response.is_error:
        raise RuntimeError(f"Gemini Voices API вернул HTTP {response.status_code}")
    payload = response.json()
    voices = payload.get("voices", [])
    if not isinstance(voices, list):
        raise RuntimeError("Gemini Voices API вернул неожиданный формат")
    # Return only public catalogue metadata, never arbitrary response fields.
    result = []
    for voice in voices:
        if not isinstance(voice, dict):
            continue
        result.append({
            "id": voice.get("id") or voice.get("name"),
            "display_name": voice.get("displayName") or voice.get("display_name"),
            "type": voice.get("type"),
            "language_code": voice.get("languageCode") or voice.get("language_code"),
            "gender": voice.get("gender"),
            "description": voice.get("description"),
            "accent": voice.get("accent"),
            "persona": voice.get("persona"),
        })
    return result


async def synthesize_gemini_preview(text: str, voice_id: str) -> bytes:
    """Generate a WAV preview for an explicitly selected catalog voice ID."""
    clean_text = (text or "").strip()
    selected_voice = (voice_id or "").strip()
    if not clean_text or len(clean_text) > 2000:
        raise ValueError("Текст для теста должен содержать от 1 до 2000 символов")
    if not selected_voice or len(selected_voice) > 200:
        raise ValueError("Некорректный ID голоса")
    payload = {
        "contents": [{"parts": [{"text": clean_text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": selected_voice}
                }
            },
        },
    }
    headers = {"x-goog-api-key": _api_key(), "content-type": "application/json"}
    model = os.getenv("GEMINI_TTS_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{API_ROOT}/models/{model}:generateContent",
            headers=headers,
            json=payload,
        )
    if response.is_error:
        raise RuntimeError(f"Gemini TTS вернул HTTP {response.status_code}")
    data = response.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        audio_part = next(
            part for part in parts
            if isinstance(part, dict) and isinstance(part.get("inlineData"), dict)
            and str(part["inlineData"].get("mimeType", "")).startswith("audio/")
        )
        audio = base64.b64decode(audio_part["inlineData"]["data"], validate=True)
    except (KeyError, IndexError, StopIteration, TypeError, ValueError) as exc:
        raise RuntimeError("Gemini TTS не вернул аудиоданные") from exc
    if not audio.startswith(b"RIFF") or b"WAVE" not in audio[:16]:
        raise RuntimeError("Gemini TTS вернул аудио не в формате WAV")
    return audio
