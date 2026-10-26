from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env(path: str | Path = ".env") -> None:
    """.env 를 읽어 환경변수에 넣는다. 이미 있는 환경변수는 덮어쓰지 않는다."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #")[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


@dataclass(frozen=True)
class Settings:
    github_token: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    db_path: str = "data/techradar.db"
    search_days: int = 7
    min_stars: int = 50
    search_limit: int = 50
    track_days: int = 14
    readme_max_chars: int = 20000

    @classmethod
    def from_env(cls) -> "Settings":
        g = os.environ.get
        return cls(
            github_token=g("GITHUB_TOKEN", ""),
            telegram_bot_token=g("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=g("TELEGRAM_CHAT_ID", ""),
            db_path=g("DB_PATH", "data/techradar.db"),
            search_days=int(g("SEARCH_DAYS", "7")),
            min_stars=int(g("MIN_STARS", "50")),
            search_limit=int(g("SEARCH_LIMIT", "50")),
            track_days=int(g("TRACK_DAYS", "14")),
            readme_max_chars=int(g("README_MAX_CHARS", "20000")),
        )
