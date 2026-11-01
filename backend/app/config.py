"""Application settings. Everything is overridable through EXPLORER_* environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EXPLORER_", env_file=".env", extra="ignore")

    # Branding (the product name is configurable)
    app_name: str = "Yatra"

    # Storage
    data_dir: Path = Path("./data")
    max_upload_mb: int = 50
    upload_ttl_hours: int = 24          # uploaded files older than this are removed
    max_rows: int = 3_000_000           # hard cap on parsed table rows

    # Execution
    max_workers: int = 2

    # Archives
    offline: bool = False               # serve archive responses from bundled test fixtures
    cache_ttl_hours: int = 24
    http_timeout_s: float = 30.0
    contact_email: str = ""             # optional; appended to the User-Agent so archives can reach you
    nasa_tap_url: str = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
    mast_invoke_url: str = "https://mast.stsci.edu/api/v0/invoke"
    mast_download_url: str = "https://mast.stsci.edu/api/v0.1/Download/file"
    exomast_url: str = "https://exo.mast.stsci.edu/api/v0.1"
    max_product_mb: int = 100           # refuse to download archive products larger than this

    # Web
    cors_origins: str = "http://localhost:3000"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "explorer.db"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
