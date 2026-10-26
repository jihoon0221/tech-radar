from datetime import date

from techradar.github_client import parse_repo
from techradar.store import Store

from conftest import repo

D1, D2 = date(2026, 10, 27), date(2026, 10, 28)


def test_upsert_returns_true_only_for_new_repo():
    s = Store(":memory:")
    info = parse_repo(repo("a/a", 100))
    assert s.upsert_repo(info, D1) is True
    assert s.upsert_repo(info, D2) is False
    row = s.db.execute("SELECT first_seen, last_seen FROM repos").fetchone()
    assert (row["first_seen"], row["last_seen"]) == (D1.isoformat(), D2.isoformat())


def test_top_rising_uses_previous_snapshot_and_skips_repos_without_one():
    s = Store(":memory:")
    for name, before, after in [("a/a", 100, 150), ("b/b", 60, 90)]:
        s.upsert_repo(parse_repo(repo(name, before)), D1)
        s.add_snapshot(name, D1, before)
        s.add_snapshot(name, D2, after)
    s.upsert_repo(parse_repo(repo("c/c", 80)), D2)
    s.add_snapshot("c/c", D2, 80)  # 어제 기록이 없으니 증가량을 알 수 없다

    top = s.top_rising(D2, 10)
    assert [t["full_name"] for t in top] == ["a/a", "b/b"]
    assert [t["growth"] for t in top] == [50, 30]


def test_snapshot_same_day_is_replaced_not_duplicated():
    s = Store(":memory:")
    s.add_snapshot("a/a", D1, 100)
    s.add_snapshot("a/a", D1, 120)
    assert s.counts()["snapshots"] == 1
    assert s.db.execute("SELECT stars FROM star_snapshots").fetchone()["stars"] == 120


def test_tracked_repos_window():
    s = Store(":memory:")
    s.upsert_repo(parse_repo(repo("old/old", 10)), date(2026, 10, 1))
    s.upsert_repo(parse_repo(repo("new/new", 10)), date(2026, 10, 25))
    assert s.tracked_repos(D2, 14) == ["new/new"]


def test_top_rising_divides_by_days_between_snapshots():
    s = Store(":memory:")
    d1, d2, d3 = date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)
    s.add_snapshot("a/a", d1, 100)
    s.add_snapshot("a/a", d3, 160)   # 이틀 공백: 60개 → 하루 30개
    s.add_snapshot("b/b", d2, 100)
    s.add_snapshot("b/b", d3, 140)   # 하루: 40개
    top = s.top_rising(d3, 10)
    assert [t["full_name"] for t in top] == ["b/b", "a/a"]
    assert top[1]["growth"] == 60 and top[1]["days"] == 2 and top[1]["per_day"] == 30


def test_seed_is_never_downgraded_and_not_tracked():
    s = Store(":memory:")
    s.upsert_repo(parse_repo(repo("x/x", 5000)), D1, source="seed", seed_topic="fastapi")
    s.upsert_repo(parse_repo(repo("x/x", 5100)), D2)                 # 트렌딩에서 다시 봄
    row = s.db.execute("SELECT source, seed_topic, stars FROM repos").fetchone()
    assert (row["source"], row["seed_topic"], row["stars"]) == ("seed", "fastapi", 5100)
    assert s.tracked_repos(D2, 14) == []


def test_trending_repo_can_be_promoted_to_seed():
    s = Store(":memory:")
    s.upsert_repo(parse_repo(repo("y/y", 2000)), D1)
    s.upsert_repo(parse_repo(repo("y/y", 2000)), D2, source="seed", seed_topic="cli")
    assert s.db.execute("SELECT source FROM repos").fetchone()["source"] == "seed"


def test_adoption_is_one_row_per_tech_and_project():
    s = Store(":memory:")
    s.record_adoption("Tailscale", "tech-radar", "tried", "맥-서버 연결")
    s.record_adoption("tailscale", "tech-radar", "adopted")          # 메모는 비우면 유지
    s.record_adoption("httpx", "upbit-bot", "adopted", origin="scan")
    rows = s.list_adoptions("tech-radar")
    assert len(rows) == 1
    assert (rows[0]["tech"], rows[0]["status"], rows[0]["note"]) == ("tailscale", "adopted", "맥-서버 연결")
    assert len(s.list_adoptions()) == 2


def test_old_db_without_new_columns_is_migrated(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE repos (full_name TEXT PRIMARY KEY, html_url TEXT NOT NULL, "
               "description TEXT NOT NULL DEFAULT '', language TEXT NOT NULL DEFAULT '', "
               "topics TEXT NOT NULL DEFAULT '[]', license TEXT NOT NULL DEFAULT '', "
               "created_at TEXT NOT NULL DEFAULT '', stars INTEGER NOT NULL DEFAULT 0, "
               "first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)")
    db.commit(); db.close()
    s = Store(path)
    s.upsert_repo(parse_repo(repo("a/a", 1)), D1, source="seed", seed_topic="llm")
    assert s.counts()["seeds"] == 1
