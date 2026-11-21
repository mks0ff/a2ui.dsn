from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DSN_", env_file=ROOT / ".env", extra="ignore")

    project_id: str = Field(default="", pattern=r"^([a-z][a-z0-9-]{4,61}[a-z0-9])?$")
    dataset_id: str = Field(default="dsn_demo", pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    bigquery_location: str = ""
    vertex_location: str = ""
    model: str = ""
    prompt_file: Path = ROOT / "config" / "prompts.json"
    max_bytes_billed: int = Field(default=100 * 1024 * 1024, ge=10 * 1024 * 1024)
    max_result_rows: int = Field(default=10_000, ge=1)
    max_chart_points: int = Field(default=5_000, ge=1)
    max_sql_attempts: int = Field(default=2, ge=1, le=2)

    @property
    def dataset(self) -> str:
        return f"{self.project_id}.{self.dataset_id}"

    @property
    def approved_views(self) -> set[str]:
        return {
            f"{self.dataset}.{name}"
            for name in ("reporting_payroll", "reporting_contributions", "reporting_employment")
        }

    @property
    def missing(self) -> list[str]:
        return [
            f"DSN_{key.upper()}"
            for key in ("project_id", "bigquery_location", "vertex_location", "model")
            if not getattr(self, key)
        ]
