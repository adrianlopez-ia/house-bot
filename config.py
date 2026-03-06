from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent


class UserData(BaseModel):
    """Personal data used to auto-fill web forms."""

    full_name: str = ""
    email: str = ""
    phone: str = ""
    dni: str = ""
    address: str = ""
    city: str = "Madrid"
    postal_code: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "dni": self.dni,
            "address": self.address,
            "city": self.city,
            "postal_code": self.postal_code,
        }


class Settings(BaseSettings):
    """Validated, type-safe application settings loaded from .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_dir: Path = _BASE_DIR
    db_path: Path = _BASE_DIR / "house_bot.db"
    screenshots_dir: Path = _BASE_DIR / "screenshots"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    zones: str = "norte,este,oeste"

    scrape_interval_hours: int = 6
    discovery_interval_hours: int = 24
    form_fill_interval_hours: int = 12

    playwright_timeout_ms: int = 30_000
    max_page_text_chars: int = 50_000
    max_page_html_chars: int = 80_000

    user_full_name: str = ""
    user_email: str = ""
    user_phone: str = ""
    user_dni: str = ""
    user_address: str = ""
    user_city: str = "Madrid"
    user_postal_code: str = ""

    def model_post_init(self, __context: object) -> None:
        self.screenshots_dir.mkdir(exist_ok=True)

    @property
    def zone_list(self) -> list[str]:
        return [z.strip() for z in self.zones.split(",") if z.strip()]

    @property
    def user_data(self) -> UserData:
        return UserData(
            full_name=self.user_full_name,
            email=self.user_email,
            phone=self.user_phone,
            dni=self.user_dni,
            address=self.user_address,
            city=self.user_city,
            postal_code=self.user_postal_code,
        )

    def validate_required(self) -> list[str]:
        """Return a list of missing-but-required configuration keys."""
        errors: list[str] = []
        if not self.gemini_api_key:
            errors.append("GEMINI_API_KEY")
        if not self.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_chat_id:
            errors.append("TELEGRAM_CHAT_ID")
        return errors


def load_settings() -> Settings:
    return Settings()
