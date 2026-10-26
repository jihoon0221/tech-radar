import httpx
import pytest


def repo(name: str, stars: int, topics=("ai",), lang="Python") -> dict:
    return {
        "full_name": name,
        "html_url": f"https://github.com/{name}",
        "description": f"{name} description",
        "language": lang,
        "topics": list(topics),
        "license": {"spdx_id": "MIT"},
        "created_at": "2026-10-20T00:00:00Z",
        "stargazers_count": stars,
    }


class FakeGitHub:
    """GitHub API 흉내. state 를 바꿔 가며 여러 날을 시뮬레이션한다."""

    def __init__(self):
        self.search_items: list[dict] = []
        self.repos: dict[str, dict] = {}          # 개별 조회용
        self.missing: set[str] = set()            # 404 로 응답할 저장소
        self.no_readme: set[str] = set()
        self.readme_calls: list[str] = []
        self.rate_limit_search = False
        self.topic_items: dict[str, list[dict]] = {}   # 시드용 topic: 검색 결과
        self.search_queries: list[str] = []
        self.server_errors = 0                    # 처음 N번은 500

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.server_errors > 0:
            self.server_errors -= 1
            return httpx.Response(500, text="boom")
        path = request.url.path
        if path == "/search/repositories":
            if self.rate_limit_search:
                return httpx.Response(
                    403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000000"},
                    text="API rate limit exceeded",
                )
            q = request.url.params.get("q", "")
            self.search_queries.append(q)
            if "topic:" in q:
                topic = q.split("topic:", 1)[1].split()[0]
                return httpx.Response(200, json={"items": self.topic_items.get(topic, [])})
            return httpx.Response(200, json={"items": self.search_items})
        parts = path.strip("/").split("/")
        if parts[0] == "repos" and len(parts) >= 3:
            name = f"{parts[1]}/{parts[2]}"
            if name in self.missing:
                return httpx.Response(404, json={"message": "Not Found"})
            if len(parts) == 4 and parts[3] == "readme":
                self.readme_calls.append(name)
                if name in self.no_readme:
                    return httpx.Response(404, json={"message": "Not Found"})
                return httpx.Response(200, text=f"# {name}\n\n한글 README 내용")
            if name in self.repos:
                return httpx.Response(200, json=self.repos[name])
        return httpx.Response(404, json={"message": "Not Found"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def gh():
    return FakeGitHub()
