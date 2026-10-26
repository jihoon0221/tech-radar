from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from .github_client import RepoInfo

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    full_name   TEXT PRIMARY KEY,
    html_url    TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    language    TEXT NOT NULL DEFAULT '',
    topics      TEXT NOT NULL DEFAULT '[]',
    license     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT '',
    stars       INTEGER NOT NULL DEFAULT 0,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'trending',  -- seed | trending
    seed_topic  TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS star_snapshots (
    full_name TEXT NOT NULL,
    date      TEXT NOT NULL,
    stars     INTEGER NOT NULL,
    PRIMARY KEY (full_name, date)
);
CREATE TABLE IF NOT EXISTS readmes (
    full_name  TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    found       INTEGER NOT NULL DEFAULT 0,
    tracked     INTEGER NOT NULL DEFAULT 0,
    readmes     INTEGER NOT NULL DEFAULT 0,
    message     TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS adoptions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tech           TEXT NOT NULL,
    project        TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL CHECK (status IN ('tried', 'adopted', 'dropped')),
    note           TEXT NOT NULL DEFAULT '',
    origin         TEXT NOT NULL DEFAULT 'manual',  -- manual | scan
    repo_full_name TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE (tech, project)
);
"""

MIGRATIONS = {  # 예전 DB 에 없는 컬럼을 추가
    "repos": {
        "source": "TEXT NOT NULL DEFAULT 'trending'",
        "seed_topic": "TEXT NOT NULL DEFAULT ''",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = "data/techradar.db"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for col, ddl in cols.items():
                if col not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # --- 저장소 / 스타 스냅샷 ---
    def upsert_repo(self, info: RepoInfo, today: date, *, source: str = "trending", seed_topic: str = "") -> bool:
        """저장하고, 처음 보는 저장소면 True.

        한 번 seed 가 된 저장소는 trending 으로 내려가지 않는다(검증된 저장소로 유지).
        """
        exists = self.db.execute("SELECT 1 FROM repos WHERE full_name=?", (info.full_name,)).fetchone()
        self.db.execute(
            """
            INSERT INTO repos (full_name, html_url, description, language, topics, license,
                               created_at, stars, first_seen, last_seen, source, seed_topic)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(full_name) DO UPDATE SET
                html_url=excluded.html_url, description=excluded.description,
                language=excluded.language, topics=excluded.topics, license=excluded.license,
                stars=excluded.stars, last_seen=excluded.last_seen,
                source=CASE WHEN repos.source = 'seed' THEN 'seed' ELSE excluded.source END,
                seed_topic=CASE WHEN repos.seed_topic != '' THEN repos.seed_topic ELSE excluded.seed_topic END
            """,
            (
                info.full_name, info.html_url, info.description, info.language,
                json.dumps(list(info.topics), ensure_ascii=False), info.license,
                info.created_at, info.stars, today.isoformat(), today.isoformat(),
                source, seed_topic,
            ),
        )
        self.db.commit()
        return exists is None

    def add_snapshot(self, full_name: str, day: date, stars: int) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO star_snapshots (full_name, date, stars) VALUES (?, ?, ?)",
            (full_name, day.isoformat(), stars),
        )
        self.db.commit()

    def tracked_repos(self, today: date, days: int) -> list[str]:
        """처음 본 지 days 일 이내인 트렌딩 저장소 (스타 추이를 따라가는 대상). 시드는 제외."""
        rows = self.db.execute(
            "SELECT full_name FROM repos WHERE source = 'trending' AND first_seen >= date(?, ?) "
            "ORDER BY full_name",
            (today.isoformat(), f"-{days} days"),
        ).fetchall()
        return [r["full_name"] for r in rows]

    def top_rising(self, day: date, n: int = 10) -> list[dict]:
        """day 의 스냅샷과 직전 스냅샷을 비교해 하루당 스타 증가량이 큰 순.

        서버가 며칠 쉬어서 직전 기록이 오래됐더라도 하루당으로 나눠 공정하게 비교한다.
        """
        rows = self.db.execute(
            """
            SELECT t.full_name AS full_name, t.stars AS stars, t.stars - p.stars AS growth,
                   CAST(julianday(t.date) - julianday(p.date) AS INTEGER) AS days,
                   (t.stars - p.stars) * 1.0 / (julianday(t.date) - julianday(p.date)) AS per_day
            FROM star_snapshots t
            JOIN star_snapshots p
              ON p.full_name = t.full_name
             AND p.date = (SELECT MAX(date) FROM star_snapshots
                           WHERE full_name = t.full_name AND date < t.date)
            WHERE t.date = ?
            ORDER BY per_day DESC, t.stars DESC
            LIMIT ?
            """,
            (day.isoformat(), n),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- README ---
    def repos_without_readme(self, limit: int = 100) -> list[str]:
        rows = self.db.execute(
            """
            SELECT r.full_name FROM repos r
            LEFT JOIN readmes m ON m.full_name = r.full_name
            WHERE m.full_name IS NULL
            ORDER BY r.stars DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [r["full_name"] for r in rows]

    def save_readme(self, full_name: str, content: str) -> None:
        """README 가 없는 저장소는 빈 문자열로 저장해 다음 실행에서 다시 조회하지 않는다."""
        self.db.execute(
            "INSERT OR REPLACE INTO readmes (full_name, content, fetched_at) VALUES (?, ?, ?)",
            (full_name, content, _now()),
        )
        self.db.commit()

    # --- 실행 기록 ---
    def start_run(self) -> int:
        cur = self.db.execute("INSERT INTO runs (started_at, status) VALUES (?, 'running')", (_now(),))
        self.db.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, found: int, tracked: int, readmes: int, message: str = "") -> None:
        self.db.execute(
            "UPDATE runs SET finished_at=?, status=?, found=?, tracked=?, readmes=?, message=? WHERE id=?",
            (_now(), status, found, tracked, readmes, message, run_id),
        )
        self.db.commit()

    # --- 기술 적용 기록 ---
    def record_adoption(
        self, tech: str, project: str, status: str, note: str = "", *,
        origin: str = "manual", repo_full_name: str = "",
    ) -> None:
        """(기술, 프로젝트) 하나당 한 줄. 다시 기록하면 상태와 메모를 갱신한다."""
        now = _now()
        self.db.execute(
            """
            INSERT INTO adoptions (tech, project, status, note, origin, repo_full_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tech, project) DO UPDATE SET
                status=excluded.status,
                note=CASE WHEN excluded.note != '' THEN excluded.note ELSE adoptions.note END,
                origin=excluded.origin, repo_full_name=excluded.repo_full_name,
                updated_at=excluded.updated_at
            """,
            (tech.strip().lower(), project.strip(), status, note, origin, repo_full_name, now, now),
        )
        self.db.commit()

    def list_adoptions(self, project: str | None = None) -> list[dict]:
        if project is None:
            rows = self.db.execute("SELECT * FROM adoptions ORDER BY updated_at DESC, id DESC").fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM adoptions WHERE project = ? ORDER BY updated_at DESC, id DESC", (project,)
            ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        q = lambda t: self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        seeds = self.db.execute("SELECT COUNT(*) FROM repos WHERE source = 'seed'").fetchone()[0]
        return {"repos": q("repos"), "seeds": seeds, "snapshots": q("star_snapshots"), "readmes": q("readmes")}
