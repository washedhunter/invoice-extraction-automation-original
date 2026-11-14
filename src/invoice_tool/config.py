"""Load settings from config/*.toml with INVOICE_* environment-variable overrides."""

from __future__ import annotations

import json
import os
import tomllib
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_CONFIG_DIR = Path("config")
ENV_PREFIX = "INVOICE_"


class RatePeriod(BaseModel):
    name: str
    valid_from: date
    valid_to: date | None = None
    rates: list[float]

    def covers(self, d: date) -> bool:
        return self.valid_from <= d and (self.valid_to is None or d <= self.valid_to)


class Settings(BaseModel):
    model: str
    amount_tolerance: float = 1.0
    near_duplicate_days: int = 7
    cache_dir: Path = Path(".cache/extractions")
    max_retries: int = 6
    initial_backoff_seconds: float = 4.0
    max_backoff_seconds: float = 90.0
    request_timeout_seconds: float = 120.0
    categories: list[str]
    required_fields_invoice: list[str]
    required_fields_receipt: list[str]
    gst_periods: list[RatePeriod] = Field(default_factory=list)

    def valid_rates_on(self, d: date) -> list[float] | None:
        for period in self.gst_periods:
            if period.covers(d):
                return period.rates
        return None


def _env_overrides(fields: set[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for name in fields:
        raw = os.environ.get(ENV_PREFIX + name.upper())
        if raw is None or raw == "":
            continue
        # lists can be given as JSON, everything else is parsed by pydantic
        out[name] = json.loads(raw) if raw.strip().startswith("[") else raw
    return out


def load_settings(config_dir: Path | str | None = None, **overrides: object) -> Settings:
    config_dir = Path(config_dir or os.environ.get(ENV_PREFIX + "CONFIG_DIR") or DEFAULT_CONFIG_DIR)
    settings_file = config_dir / "settings.toml"
    rates_file = config_dir / "gst_rates.toml"
    if not settings_file.exists():
        raise FileNotFoundError(
            f"{settings_file} not found. Run from the repo root or pass --config-dir."
        )
    data: dict[str, object] = tomllib.loads(settings_file.read_text(encoding="utf-8"))
    if rates_file.exists():
        data["gst_periods"] = tomllib.loads(rates_file.read_text(encoding="utf-8"))["periods"]
    data.update(_env_overrides(set(Settings.model_fields) - {"gst_periods"}))
    data.update({k: v for k, v in overrides.items() if v is not None})
    return Settings.model_validate(data)
