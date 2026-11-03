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
    # Comma-separated phone numbers the call trigger may dial. Empty means no restriction.
    OUTBOUND_CALL_ALLOWED_NUMBERS: str = os.getenv("OUTBOUND_CALL_ALLOWED_NUMBERS", "")

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
    GEMINI_FALLBACK_MODEL: str = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.8-flash")
    GEMINI_RETRY_DELAY_SECONDS: float = float(os.getenv("GEMINI_RETRY_DELAY_SECONDS", "0.5"))
    GEMINI_QUOTA_CIRCUIT_SECONDS: float = float(os.getenv("GEMINI_QUOTA_CIRCUIT_SECONDS", "900"))
    GEMINI_CIRCUIT_SECONDS: float = float(os.getenv("GEMINI_CIRCUIT_SECONDS", "60"))
    GEMINI_STRUCTURED_TIMEOUT_SECONDS: float = float(os.getenv("GEMINI_STRUCTURED_TIMEOUT_SECONDS", "3"))
    GEMINI_DISABLE_THINKING: bool = os.getenv("GEMINI_DISABLE_THINKING", "true").lower() in {"1", "true", "yes"}
    GEMINI_ANSWER_MAX_TOKENS: int = int(os.getenv("GEMINI_ANSWER_MAX_TOKENS", "200"))
    GEMINI_TIMEOUT_SECONDS: float = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "5"))
    VOICE_ASSISTANT_TRANSLATION_TIMEOUT_SECONDS: float = float(
        os.getenv("VOICE_ASSISTANT_TRANSLATION_TIMEOUT_SECONDS", "12")
    )
    NOTIFICATION_RETRY_ATTEMPTS: int = int(os.getenv("NOTIFICATION_RETRY_ATTEMPTS", "3"))
    NOTIFICATION_RETRY_DELAY_SECONDS: float = float(os.getenv("NOTIFICATION_RETRY_DELAY_SECONDS", "1"))
    VOICE_ASSISTANT_TRANSLATION_ATTEMPTS: int = int(os.getenv("VOICE_ASSISTANT_TRANSLATION_ATTEMPTS", "2"))
    VOICE_ASSISTANT_TURN_TIMEOUT_SECONDS: float = float(
        os.getenv("VOICE_ASSISTANT_TURN_TIMEOUT_SECONDS", "35")
    )
    OUTBOUND_CALL_TURN_TIMEOUT_SECONDS: float = float(
        os.getenv("OUTBOUND_CALL_TURN_TIMEOUT_SECONDS", "20")
    )
    OUTBOUND_TTS_TIMEOUT_SECONDS: float = float(
        os.getenv("OUTBOUND_TTS_TIMEOUT_SECONDS", "2.5")
    )
    AUDIO_STORAGE_DIR: str = os.getenv("AUDIO_STORAGE_DIR", "audio_cache")
    AUDIO_CACHE_TTL_SECONDS: int = int(os.getenv("AUDIO_CACHE_TTL_SECONDS", "900"))
    DIAGNOSTICS_API_KEY: str = os.getenv("DIAGNOSTICS_API_KEY", "")

    # ── Gemini LLM ────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

    # ── Groq LLM (OpenAI-compatible API) ───────────────────────────────────
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    # Comma-separated, tried in order: if the first model fails, the next is tried before giving up on Groq.
    GROQ_MODELS: str = os.getenv("GROQ_MODELS", "qwen/qwen3.8-27b,openai/gpt-oss-120b,openai/gpt-oss-20b")
    GROQ_MAX_RETRY_WAIT_SECONDS: float = float(os.getenv("GROQ_MAX_RETRY_WAIT_SECONDS", "4"))
    GROQ_BASE_URL: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

    # ── Conversation agent models ──────────────────────────────────────────
    # One model runs the conversation: it reads the patient, calls tools and writes the reply. A turn is a
    # short loop of model calls (LLM_AGENT_MAX_STEPS at most). Which provider answers first depends on the
    # channel: each list is tried in order, and a provider without an API key or that failed a moment ago is
    # skipped. An empty LLM_AGENT_MODEL falls back to GEMINI_MODEL. GEMINI_FALLBACK_MODEL (comma-separated)
    # lists backup Gemini models tried in order when the primary fails or is out of quota.
    LLM_PROVIDERS_CHAT: str = os.getenv("LLM_PROVIDERS_CHAT", "groq,gemini")
    LLM_PROVIDERS_CALL: str = os.getenv("LLM_PROVIDERS_CALL", "groq,gemini")
    LLM_PROVIDERS_VOICE: str = os.getenv("LLM_PROVIDERS_VOICE", "gemini,groq")
    LLM_PROVIDER_COOLDOWN_SECONDS: float = float(os.getenv("LLM_PROVIDER_COOLDOWN_SECONDS", "60"))
    LLM_AGENT_MODEL: str = os.getenv("LLM_AGENT_MODEL", "")
    LLM_AGENT_TIMEOUT_SECONDS: float = float(os.getenv("LLM_AGENT_TIMEOUT_SECONDS", "10"))
    LLM_AGENT_MAX_TOKENS: int = int(os.getenv("LLM_AGENT_MAX_TOKENS", "700"))
    LLM_AGENT_TEMPERATURE: float = float(os.getenv("LLM_AGENT_TEMPERATURE", "0.3"))
    LLM_AGENT_MAX_STEPS: int = int(os.getenv("LLM_AGENT_MAX_STEPS", "8"))
    LLM_CONTEXT_MESSAGES: int = int(os.getenv("LLM_CONTEXT_MESSAGES", "20"))

    # ── ngrok & Public Domain (tunnel for Twilio webhooks) ─────────────────
    PUBLIC_DOMAIN: str = os.getenv("PUBLIC_DOMAIN", os.getenv("NGROK_URL", ""))
    NGROK_URL: str = os.getenv("NGROK_URL", os.getenv("PUBLIC_DOMAIN", ""))

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
    OUTBOUND_CALL_RETRY_DELAY_MINUTES: int = int(os.getenv("OUTBOUND_CALL_RETRY_DELAY_MINUTES", "5"))
    OUTBOUND_CALL_MAX_ATTEMPTS: int = int(os.getenv("OUTBOUND_CALL_MAX_ATTEMPTS", "3"))
    OUTBOUND_CALL_STATUS_RECONCILE_MINUTES: int = int(os.getenv("OUTBOUND_CALL_STATUS_RECONCILE_MINUTES", "2"))
    RESCHEDULE_CANCEL_CUTOFF_HOURS: int = 24   # block if appt < 24h away

    # ── Misc ──────────────────────────────────────────────────────────────
    APP_ENV: str = os.getenv("APP_ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "text")
    # Front desk dashboard login. Set these in the environment, never in code.
    FRONTDESK_EMAIL: str = os.getenv("FRONTDESK_EMAIL", "")
    FRONTDESK_PASSWORD: str = os.getenv("FRONTDESK_PASSWORD", "")
    AUTH_SECRET: str = os.getenv("AUTH_SECRET", "")
    AUTH_TOKEN_TTL_MINUTES: int = int(os.getenv("AUTH_TOKEN_TTL_MINUTES", "480"))


settings = Settings()
