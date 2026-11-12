"""Settings read from the environment once. Nothing secret is ever logged or stored in the database."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "DATABASE_URL", "postgres://postgres@127.0.0.1:54339/market"))
    mode: str = field(default_factory=lambda: os.environ.get("MODE", "demo"))  # demo | live
    public_demo: bool = field(default_factory=lambda: _flag("PUBLIC_DEMO"))
    auth_mode: str = field(default_factory=lambda: os.environ.get("AUTH_MODE", "demo"))  # demo | header
    write_key: str = field(default_factory=lambda: os.environ.get("WRITE_KEY", ""))
    # Results webhook: HMAC SHA-256. Unset means a random secret for this process only, refused in live mode.
    webhook_secret: str = field(default_factory=lambda: os.environ.get("WEBHOOK_SECRET") or secrets.token_hex(32))
    webhook_secret_set: bool = field(default_factory=lambda: bool(os.environ.get("WEBHOOK_SECRET")))
    access_team_domain: str = field(default_factory=lambda: os.environ.get("CF_ACCESS_TEAM_DOMAIN", ""))
    access_aud: str = field(default_factory=lambda: os.environ.get("CF_ACCESS_AUD", ""))
    seller: str = field(default_factory=lambda: os.environ.get("SELLER", "Lumen Ledger"))
    anthropic_live: bool = field(default_factory=lambda: _flag("ANTHROPIC_LIVE"))
    worker_inline: bool = field(default_factory=lambda: not _flag("NO_WORKER"))

    def validate(self) -> None:
        if self.mode == "live" and not self.webhook_secret_set:
            raise SystemExit("MODE=live needs WEBHOOK_SECRET set. Refusing to start.")
        if self.auth_mode == "header" and not (self.access_team_domain and self.access_aud):
            raise SystemExit("AUTH_MODE=header needs CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD to verify the signed token.")
        if self.public_demo and self.mode == "live":
            raise SystemExit("The public demo holds invented data only. Unset MODE=live.")


CONFIG = Config()
