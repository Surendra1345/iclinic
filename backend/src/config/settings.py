import os
# pyrefly: ignore[missing-import]
from dotenv import load_dotenv
# pyrefly: ignore[missing-import]
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    DB_ECHO: bool = False

    # ── Twilio ────────────────────────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")

    # ── Email notifications (SMTP) ───────────────────────────────────────
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    # SMTP credentials must come from environment configuration; never bake a
    # clinic mailbox or app password into source defaults.
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", os.getenv("SMTP_USERNAME", ""))
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    # ── Sarvam AI (STT + TTS via HTTP) ───────────────────────────────────
    SARVAM_API_KEY: str = os.getenv("SARVAM_API_KEY", "")
    SARVAM_STT_URL: str = "https://api.sarvam.ai/speech-to-text"
    SARVAM_TTS_URL: str = "https://api.sarvam.ai/text-to-speech"
    SARVAM_STT_MODEL: str = os.getenv("SARVAM_STT_MODEL", "saaras:v3")
    SARVAM_TTS_MODEL: str = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
    SARVAM_SPEAKER: str = os.getenv("SARVAM_SPEAKER", "shubh")
    SARVAM_LANGUAGE: str = "en-IN"
    SARVAM_TTS_ENABLED: bool = os.getenv("SARVAM_TTS_ENABLED", "false").lower() == "true"
    VOICE_ASSISTANT_SUPPORTED_LANGUAGES: str = os.getenv(
        "VOICE_ASSISTANT_SUPPORTED_LANGUAGES", "en-IN,ta-IN,te-IN"
    )
    VOICE_ASSISTANT_LANGUAGE_CONFIDENCE_THRESHOLD: float = float(
        os.getenv("VOICE_ASSISTANT_LANGUAGE_CONFIDENCE_THRESHOLD", "0.80")
    )
    VOICE_ASSISTANT_TTS_ENABLED: bool = os.getenv(
        "VOICE_ASSISTANT_TTS_ENABLED", "true"
    ).lower() == "true"

    # ── Gemini LLM ────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

    # ── ngrok & Public Domain (tunnel for Twilio webhooks) ─────────────────
    PUBLIC_DOMAIN: str = os.getenv("PUBLIC_DOMAIN", os.getenv("NGROK_URL", "foam-jury-quality.ngrok-free.dev"))
    NGROK_URL: str = os.getenv("NGROK_URL", os.getenv("PUBLIC_DOMAIN", "foam-jury-quality.ngrok-free.dev"))

    # ── Front Desk ────────────────────────────────────────────────────────
    FRONT_DESK_EMAIL: str = os.getenv("FRONT_DESK_EMAIL", "")
    FRONT_DESK_PHONE: str = os.getenv("FRONT_DESK_PHONE", "")

    # ── Clinic Config ─────────────────────────────────────────────────────
    CLINIC_NAME: str = os.getenv("CLINIC_NAME", "City Care Clinic")
    AGENT_NAME: str = os.getenv("AGENT_NAME", "Happy")
    # Hours in 24h format (IST)
    CLINIC_HOURS_START: int = int(os.getenv("CLINIC_HOURS_START", "9"))
    CLINIC_HOURS_END: int = int(os.getenv("CLINIC_HOURS_END", "18"))

    # ── Agent Behaviour ───────────────────────────────────────────────────
    SLOT_RESERVATION_TIMEOUT_MINUTES: int = 5
    MAX_VERIFY_ATTEMPTS: int = 2
    MAX_SILENCE_TURNS: int = 3
    RESCHEDULE_CANCEL_CUTOFF_HOURS: int = 24   # block if appt < 24h away

    # ── Misc ──────────────────────────────────────────────────────────────
    APP_ENV: str = os.getenv("APP_ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
