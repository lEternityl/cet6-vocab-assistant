from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "六级词汇学习助手"
    data_dir: Path = Path(__file__).resolve().parents[1] / "data"
    max_upload_mb: int = 50
    frontend_origin: str = "http://127.0.0.1:5173"
    parser_version: str = "2026.08.1"
    prompt_version: str = "translation-v1"

    model_config = SettingsConfigDict(
        env_prefix="CET6_", env_file=".env", extra="ignore"
    )

    @property
    def database_url(self) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.data_dir / 'cet6_assistant.db'}"

    @property
    def upload_dir(self) -> Path:
        path = self.data_dir / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()

