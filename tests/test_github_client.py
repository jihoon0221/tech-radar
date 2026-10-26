import httpx
import pytest

from techradar.github_client import GitHubClient, RateLimited


def client_for(handler):
    return GitHubClient("t", transport=httpx.MockTransport(handler), sleep=lambda _s: None)


def test_huge_readme_is_cut_to_max_chars():
    big = "가" * 500_000
    c = client_for(lambda req: httpx.Response(200, text=big))
    text = c.get_readme("a/a", max_chars=1000)
    assert text == "가" * 1000


def test_readme_404_returns_none():
    c = client_for(lambda req: httpx.Response(404, json={"message": "Not Found"}))
    assert c.get_readme("a/a") is None


def test_readme_rate_limit_raises():
    c = client_for(lambda req: httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, text="rate limit"))
    with pytest.raises(RateLimited):
        c.get_readme("a/a")


def test_readme_server_error_then_success():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(502) if calls["n"] == 1 else httpx.Response(200, text="# ok")

    assert client_for(handler).get_readme("a/a") == "# ok"
