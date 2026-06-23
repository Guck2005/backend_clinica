from functools import lru_cache
import os


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


class Settings:
    def __init__(self) -> None:
        self.database_url = normalize_database_url(
            os.getenv("DATABASE_URL", "sqlite:///./caissetrace.db")
        )
        self.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
        self.access_token_minutes = int(os.getenv("ACCESS_TOKEN_MINUTES", "720"))
        cors = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        self.cors_origins = [origin.strip() for origin in cors.split(",") if origin.strip()]
        self.public_app_url = os.getenv("PUBLIC_APP_URL", "http://localhost:8000").rstrip("/")
        self.fedapay_env = os.getenv("FEDAPAY_ENV", "sandbox").strip().lower()
        self.fedapay_secret_key = os.getenv("FEDAPAY_SECRET_KEY", "")
        self.fedapay_webhook_secret = os.getenv("FEDAPAY_WEBHOOK_SECRET", "")
        self.fedapay_timeout_seconds = int(os.getenv("FEDAPAY_TIMEOUT_SECONDS", "20"))
        default_base_url = (
            "https://api.fedapay.com"
            if self.fedapay_env == "live"
            else "https://sandbox-api.fedapay.com"
        )
        self.fedapay_base_url = os.getenv("FEDAPAY_BASE_URL", default_base_url)
        self.fedapay_method_mtn = os.getenv("FEDAPAY_METHOD_MTN", "mtn_open").strip()
        self.fedapay_method_moov = os.getenv("FEDAPAY_METHOD_MOOV", "moov").strip()
        self.fedapay_method_celtiis = os.getenv("FEDAPAY_METHOD_CELTIIS", "celtiis").strip()
        self.brevo_api_key = os.getenv("BREVO_API_KEY", "").strip()
        self.brevo_sms_sender = os.getenv("BREVO_SMS_SENDER", "").strip()
        self.brevo_email_from = os.getenv("BREVO_EMAIL_FROM", "").strip()
        self.brevo_alert_email_to = os.getenv("BREVO_ALERT_EMAIL_TO", "").strip()
        self.brevo_base_url = os.getenv("BREVO_BASE_URL", "https://api.brevo.com/v3").rstrip("/")
        self.brevo_timeout_seconds = int(os.getenv("BREVO_TIMEOUT_SECONDS", "20"))
        self.background_workers_enabled = os.getenv("PYTEST_CURRENT_TEST", "").strip() == "" and os.getenv(
            "BACKGROUND_WORKERS_ENABLED",
            "1",
        ).strip() not in {"0", "false", "False"}
        self.sync_worker_interval_seconds = int(os.getenv("SYNC_WORKER_INTERVAL_SECONDS", "20"))
        self.alert_sweep_interval_seconds = int(os.getenv("ALERT_SWEEP_INTERVAL_SECONDS", "120"))
        self.backup_worker_interval_seconds = int(os.getenv("BACKUP_WORKER_INTERVAL_SECONDS", "60"))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
