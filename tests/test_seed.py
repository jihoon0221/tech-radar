from datetime import date

from techradar.github_client import GitHubClient
from techradar.seed import TopicSpec, load_topics, seed
from techradar.store import Store

from conftest import repo

TODAY = date(2026, 11, 2)


def make(gh):
    sleeps = []
    client = GitHubClient("t", transport=gh.transport(), sleep=sleeps.append)
    return client, Store(":memory:"), sleeps


def test_load_topics_parses_comments_min_stars_and_duplicates(tmp_path):
    f = tmp_path / "topics.txt"
    f.write_text("# 주석\nllm\n\nspring-boot 500  # 자바\nLLM\n", encoding="utf-8")
    assert load_topics(f) == [TopicSpec("llm", 1000), TopicSpec("spring-boot", 500)]


def test_seed_saves_repos_with_topic_and_query_filters(gh):
    gh.topic_items = {
        "fastapi": [repo("tiangolo/fastapi", 80000), repo("encode/starlette", 10000)],
        "cli": [repo("jesseduffield/lazygit", 50000), repo("encode/starlette", 10000)],
    }
    client, store, sleeps = make(gh)
    topics = [TopicSpec("fastapi", 1000), TopicSpec("cli", 1000)]

    res = seed(client, store, topics, today=TODAY, sleep=sleeps.append)

    assert res.status == "ok"
    assert res.per_topic == {"fastapi": 2, "cli": 2}
    assert res.new_repos == 3 and res.readmes == 3
    assert store.counts()["seeds"] == 3
    # 여러 토픽에 걸친 저장소는 처음 잡힌 토픽 유지
    row = store.db.execute("SELECT seed_topic FROM repos WHERE full_name='encode/starlette'").fetchone()
    assert row["seed_topic"] == "fastapi"
    q = gh.search_queries[0]
    assert "topic:fastapi" in q and "stars:>=1000" in q and "pushed:>=2025-11-02" in q and "archived:false" in q
    assert sleeps == [2.1]   # 검색 사이에만 쉰다


def test_seed_rerun_is_idempotent(gh):
    gh.topic_items = {"llm": [repo("a/a", 3000)]}
    client, store, sleeps = make(gh)
    topics = [TopicSpec("llm", 1000)]
    seed(client, store, topics, today=TODAY, sleep=sleeps.append)
    res = seed(client, store, topics, today=TODAY, sleep=sleeps.append)
    assert res.new_repos == 0 and res.readmes == 0
    assert gh.readme_calls == ["a/a"]


def test_seed_stops_on_rate_limit_and_keeps_saved(gh):
    gh.topic_items = {"llm": [repo("a/a", 3000)]}
    client, store, sleeps = make(gh)

    def limited(request):
        if "topic:rag" in request.url.params.get("q", ""):
            import httpx
            return httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, text="rate limit")
        return gh.handler(request)

    from techradar.github_client import GitHubClient as C
    import httpx
    client = C("t", transport=httpx.MockTransport(limited), sleep=sleeps.append)
    res = seed(client, store, [TopicSpec("llm", 1000), TopicSpec("rag", 1000)], today=TODAY, sleep=sleeps.append)
    assert res.status == "rate_limited"
    assert res.per_topic == {"llm": 1}
    assert store.counts()["seeds"] == 1


def test_topics_file_in_repo_is_valid():
    topics = load_topics("config/topics.txt")
    assert len(topics) >= 30
    assert all(t.min_stars > 0 for t in topics)
