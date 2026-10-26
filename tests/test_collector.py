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
