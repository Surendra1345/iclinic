"""Sarvam AI service — Speech-to-Text (Saaras v3) and Text-to-Speech (Bulbul v3)."""
import audioop
import base64
import io
import logging
import mimetypes
import time
from typing import Optional
import wave
import httpx

from src.config.settings import settings
from src.observability.metrics import provider_request_duration_seconds

logger = logging.getLogger(__name__)


class SarvamService:

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.SARVAM_API_KEY
        self.stt_url = settings.SARVAM_STT_URL
        self.tts_url = settings.SARVAM_TTS_URL
        self.stt_model = settings.SARVAM_STT_MODEL
        self.tts_model = settings.SARVAM_TTS_MODEL

    async def speech_to_text(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        language_code: str = "unknown",
        content_type: Optional[str] = None,
    ) -> tuple[str, str, float]:
        """
        Convert audio bytes (WAV) to text transcript using Sarvam Saaras v3.
        """
        if not self.api_key:
            logger.warning("SARVAM_API_KEY not configured. Returning empty transcript.")
            return "", "en-IN", 0.0

        headers = {
            "api-subscription-key": self.api_key,
        }
        data = {
            "model": self.stt_model,
            "language_code": language_code,
        }
        files = {
            # Browser MediaRecorder commonly sends WebM; preserve its actual
            # type so the provider can decode it and detect Tamil/Telugu.
            "file": (filename, audio_bytes, content_type or mimetypes.guess_type(filename)[0] or "audio/wav"),
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            started = time.perf_counter()
            try:
                response = await client.post(
                    self.stt_url,
                    headers=headers,
                    data=data,
                    files=files,
                )
                response.raise_for_status()
                result = response.json()
                provider_request_duration_seconds.labels("sarvam", "speech_to_text").observe(
                    time.perf_counter() - started
                )
                detected_language = result.get("language_code") or result.get("language") or "en-IN"
                confidence = float(result.get("confidence") or 1.0)
                return result.get("transcript", "").strip(), detected_language, confidence
            except Exception as e:
                provider_request_duration_seconds.labels("sarvam", "speech_to_text").observe(
                    time.perf_counter() - started
                )
                logger.error(f"Sarvam STT failed: {e}")
                return "", "en-IN", 0.0

    async def text_to_speech(self, text: str, target_language_code: Optional[str] = None) -> bytes:
        """
        Convert text into WAV/audio bytes using Sarvam Bulbul v3 at 8000Hz (Twilio telephone native).
        Returns WAV audio bytes.
        """
        if not self.api_key:
            logger.warning("SARVAM_API_KEY not configured. Returning empty audio bytes.")
            return b""

        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json",
        }
        lang = target_language_code or settings.SARVAM_LANGUAGE
        payload = {
            "text": text,
            "language_code": lang,
            "model": "bulbul:v3",
            "speaker": settings.SARVAM_SPEAKER,
            "speech_sample_rate": 8000,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            started = time.perf_counter()
            try:
                response = await client.post(
                    self.tts_url,
                    headers=headers,
                    json=payload,
                )
                if response.status_code == 200:
                    data = response.json()
                    audios = data.get("audios", [])
                    if audios:
                        provider_request_duration_seconds.labels("sarvam", "text_to_speech").observe(
                            time.perf_counter() - started
                        )
                        return base64.b64decode(audios[0])

                # Fallback format if primary returns non-200
                logger.warning(f"Sarvam primary TTS returned status {response.status_code}; trying fallback payload")
                fallback_payload = {
                    "inputs": [text],
                    "target_language_code": lang,
                    "speaker": settings.SARVAM_SPEAKER,
                    "model": "bulbul:v3",
                    "enable_preprocessing": True,
                }
                fb_res = await client.post(self.tts_url, headers=headers, json=fallback_payload)
                if fb_res.status_code == 200:
                    fb_data = fb_res.json()
                    audios = fb_data.get("audios", [])
                    if audios:
                        provider_request_duration_seconds.labels("sarvam", "text_to_speech").observe(
                            time.perf_counter() - started
                        )
                        return base64.b64decode(audios[0])
                logger.error(f"Sarvam TTS failed ({response.status_code}): {response.text}")
                return b""
            except Exception as e:
                provider_request_duration_seconds.labels("sarvam", "text_to_speech").observe(
                    time.perf_counter() - started
                )
                logger.error(f"Sarvam TTS failed: {e}")
                return b""

    @staticmethod
    def mulaw_to_wav(mulaw_bytes: bytes) -> bytes:
        """
        Convert Twilio 8kHz 8-bit mu-law audio to 16kHz 16-bit mono WAV for Sarvam STT.
        Ultra-fast lossless conversion via audioop.
        """
        # Convert 8-bit mu-law to 16-bit linear PCM (at 8000 Hz)
        pcm_data = audioop.ulaw2lin(mulaw_bytes, 2)
        # Resample from 8000 Hz to 16000 Hz for optimal STT accuracy
        pcm_16k, _ = audioop.ratecv(pcm_data, 2, 1, 8000, 16000, None)

        out_buf = io.BytesIO()
        with wave.open(out_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm_16k)
        return out_buf.getvalue()

    @staticmethod
    def wav_to_mulaw(wav_bytes: bytes) -> bytes:
        """
        Convert Sarvam WAV output to Twilio 8kHz 8-bit mu-law audio.
        Ensures exact format required by Twilio Media Streams.
        """
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        # Convert to mono if stereo
        if nchannels == 2:
            frames = audioop.tomono(frames, sampwidth, 0.5, 0.5)

        # Ensure 16-bit sample width
        if sampwidth != 2:
            frames = audioop.lin2lin(frames, sampwidth, 2)
            sampwidth = 2

        # Resample to 8000 Hz if needed
        if framerate != 8000:
            frames, _ = audioop.ratecv(frames, sampwidth, 1, framerate, 8000, None)

        # Convert 16-bit linear PCM to 8-bit mu-law
        return audioop.lin2ulaw(frames, 2)
