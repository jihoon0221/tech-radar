from datetime import date

import pytest

from techradar.collector import run
from techradar.config import Settings
from techradar.github_client import GitHubClient, GitHubError
from techradar.store import Store

from conftest import repo

D1, D2 = date(2026, 10, 27), date(2026, 10, 28)


def make(gh):
    sleeps = []
    client = GitHubClient("t", transport=gh.transport(), sleep=sleeps.append)
    return Settings(search_limit=50), client, Store(":memory:"), sleeps


def test_first_day_saves_repos_snapshots_and_readmes(gh):
    gh.search_items = [repo("a/a", 100), repo("b/b", 60)]
    s, client, store, _ = make(gh)

    res = run(s, client, store, today=D1)

    assert res.status == "ok" and res.found == 2 and res.new_repos == 2 and res.readmes == 2
    assert store.counts() == {"repos": 2, "seeds": 0, "snapshots": 2, "readmes": 2}
    assert "한글 README" in store.db.execute("SELECT content FROM readmes WHERE full_name='a/a'").fetchone()["content"]


def test_second_day_tracks_old_repo_and_fetches_readme_only_for_new(gh):
    gh.search_items = [repo("a/a", 100), repo("b/b", 60)]
    s, client, store, _ = make(gh)
    run(s, client, store, today=D1)

    gh.search_items = [repo("a/a", 150), repo("c/c", 80)]   # b 는 검색에서 빠짐
    gh.repos["b/b"] = repo("b/b", 90)
    res = run(s, client, store, today=D2)

    assert res.tracked == 1 and res.new_repos == 1 and res.readmes == 1
    assert gh.readme_calls == ["a/a", "b/b", "c/c"]          # a, b 는 첫날 한 번만
    top = store.top_rising(D2, 10)
    assert [(t["full_name"], t["growth"]) for t in top] == [("a/a", 50), ("b/b", 30)]


def test_same_day_rerun_is_idempotent(gh):
    gh.search_items = [repo("a/a", 100)]
    s, client, store, _ = make(gh)
    run(s, client, store, today=D1)
    before = store.counts()
    run(s, client, store, today=D1)
    assert store.counts() == before
    assert gh.readme_calls == ["a/a"]


def test_deleted_repo_is_skipped_without_crashing(gh):
    gh.search_items = [repo("a/a", 100), repo("b/b", 60)]
    s, client, store, _ = make(gh)
    run(s, client, store, today=D1)

    gh.search_items = [repo("a/a", 110)]
    gh.missing = {"b/b"}
    res = run(s, client, store, today=D2)
    assert res.status == "ok" and res.tracked == 0


def test_repo_without_readme_is_not_refetched(gh):
    gh.search_items = [repo("a/a", 100)]
    gh.no_readme = {"a/a"}
    s, client, store, _ = make(gh)
    run(s, client, store, today=D1)
    run(s, client, store, today=D2)
    assert gh.readme_calls == ["a/a"]
    assert store.db.execute("SELECT content FROM readmes").fetchone()["content"] == ""


def test_rate_limit_stops_cleanly_and_notifies(gh):
    gh.rate_limit_search = True
    s, client, store, _ = make(gh)
    msgs = []
    res = run(s, client, store, today=D1, notify=msgs.append)
    assert res.status == "rate_limited"
    assert len(msgs) == 1 and "한도" in msgs[0]
    assert store.db.execute("SELECT status FROM runs").fetchone()["status"] == "rate_limited"


def test_transient_server_error_is_retried(gh):
    gh.search_items = [repo("a/a", 100)]
    gh.server_errors = 2
    s, client, store, sleeps = make(gh)
    res = run(s, client, store, today=D1)
    assert res.status == "ok"
    assert sleeps == [1, 2]       # 1초, 2초 뒤 재시도


def test_persistent_server_error_becomes_error_status(gh):
    gh.server_errors = 99
    s, client, store, _ = make(gh)
    msgs = []
    res = run(s, client, store, today=D1, notify=msgs.append)
    assert res.status == "error" and msgs and "수집 실패" in msgs[0]


def test_one_broken_readme_does_not_stop_the_rest(gh):
    """10/28~11/8 장애 재현: 스타 1위 저장소의 README 가 매일 실패해서 README 단계 전체가 0개였다."""
    gh.search_items = [repo("top/blocked", 900), repo("b/b", 60), repo("c/c", 50)]
    gh.broken_readme = {"top/blocked"}
    s, client, store, _ = make(gh)
    msgs = []

    res = run(s, client, store, today=D1, notify=msgs.append)

    assert res.status == "partial"
    assert res.readmes == 2 and len(res.failures) == 1 and "top/blocked" in res.failures[0]
    assert store.counts()["readmes"] == 2           # 실패한 건 저장하지 않아 다음 날 다시 시도
    assert sum("1건 실패" in m for m in msgs) == 1
    assert store.db.execute("SELECT status FROM runs").fetchone()["status"] == "partial"


def test_renamed_repo_redirect_is_followed(gh):
    gh.search_items = [repo("old/name", 100)]
    gh.moved = {"old/name": "new/name"}
    s, client, store, _ = make(gh)
    res = run(s, client, store, today=D1)
    assert res.status == "ok" and res.readmes == 1
    assert "new/name" in store.db.execute("SELECT content FROM readmes").fetchone()["content"]


def test_low_count_triggers_quality_alert(gh):
    gh.search_items = [repo("a/a", 100)]
    s, client, store, _ = make(gh)
    msgs = []
    res = run(s, client, store, today=D1, notify=msgs.append)
    assert res.status == "ok"                       # 수집 자체는 성공
    assert any("기준(10건)" in m for m in msgs)      # 하지만 조용히 넘어가지 않는다


def test_normal_day_sends_no_alert(gh):
    gh.search_items = [repo(f"r/{i}", 100 + i) for i in range(12)]
    s, client, store, _ = make(gh)
    msgs = []
    assert run(s, client, store, today=D1, notify=msgs.append).status == "ok"
    assert msgs == []


def test_renamed_tracked_repo_does_not_stop_run_and_keeps_history(gh):
    """11/8 확인한 실제 원인: 추적 중인 NVIDIA/flare-local-inference 가 이름이 바뀌어 301 → 수집 전체 중단."""
    gh.search_items = [repo("old/name", 100), repo("b/b", 60)]
    s, client, store, _ = make(gh)
    run(s, client, store, today=D1)

    gh.search_items = [repo("b/b", 70)]
    gh.moved = {"old/name": "new/name"}
    gh.repos["new/name"] = repo("new/name", 130)
    res = run(s, client, store, today=D2)

    assert res.status == "ok" and res.tracked == 1 and res.failures == []
    names = [r["full_name"] for r in store.db.execute("SELECT full_name FROM repos ORDER BY 1")]
    assert names == ["b/b", "new/name"]                       # 옛 이름 행이 남지 않는다
    snaps = store.db.execute("SELECT date, stars FROM star_snapshots WHERE full_name='new/name' ORDER BY date").fetchall()
    assert [tuple(r) for r in snaps] == [(D1.isoformat(), 100), (D2.isoformat(), 130)]  # 이력 유지
    assert store.top_rising(D2, 5)[0]["full_name"] == "new/name"
