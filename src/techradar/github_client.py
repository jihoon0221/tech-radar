from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Callable

import httpx

API = "https://api.github.com"


class GitHubError(Exception):
    pass


class RateLimited(GitHubError):
    """GitHub API 호출 한도에 걸렸다. 지금까지 모은 데이터는 보존하고 멈춘다."""

    def __init__(self, message: str, reset_at: int | None = None):
        super().__init__(message)
        self.reset_at = reset_at


@dataclass(frozen=True)
class RepoInfo:
    full_name: str
    html_url: str
    description: str
    language: str
    topics: tuple[str, ...]
    license: str
    created_at: str
    stars: int


def parse_repo(d: dict) -> RepoInfo:
    lic = d.get("license") or {}
    return RepoInfo(
        full_name=d["full_name"],
        html_url=d["html_url"],
        description=d.get("description") or "",
        language=d.get("language") or "",
        topics=tuple(d.get("topics") or ()),
        license=lic.get("spdx_id") or "",
        created_at=d.get("created_at") or "",
        stars=int(d.get("stargazers_count") or 0),
    )


class GitHubClient:
    def __init__(
        self,
        token: str = "",
        *,
        transport: httpx.BaseTransport | None = None,
        base_url: str = API,
        retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "tech-radar",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=base_url, headers=headers, transport=transport,
            timeout=httpx.Timeout(20.0, connect=10.0),
        )
        self._retries = retries
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    @staticmethod
    def _is_rate_limited(resp: httpx.Response) -> bool:
        if resp.headers.get("x-ratelimit-remaining") == "0":
            return True
        if resp.headers.get("retry-after"):
            return True
        return "rate limit" in resp.text.lower()

    def _get(self, path: str, params: dict | None = None, accept: str | None = None) -> httpx.Response:
        headers = {"Accept": accept} if accept else None
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                resp = self._http.get(path, params=params, headers=headers)
            except httpx.TransportError as e:
                last = e
                self._sleep(2**attempt)
                continue
            if resp.status_code >= 500:
                last = GitHubError(f"{resp.status_code} {path}")
                self._sleep(2**attempt)
                continue
            if resp.status_code in (403, 429) and self._is_rate_limited(resp):
                reset = resp.headers.get("x-ratelimit-reset")
                raise RateLimited(
                    f"rate limited: {path}", int(reset) if reset and reset.isdigit() else None
                )
            return resp
        raise GitHubError(f"요청 실패(재시도 {self._retries}회): {path}: {last}")

    def search_repos(self, q: str, *, limit: int) -> list[RepoInfo]:
        """검색어 q 로 스타가 많은 순 상위 limit 개 (최대 100)."""
        resp = self._get(
            "/search/repositories",
            params={"q": q, "sort": "stars", "order": "desc", "per_page": min(limit, 100)},
        )
        if resp.status_code != 200:
            raise GitHubError(f"검색 실패 {resp.status_code}: {resp.text[:200]}")
        return [parse_repo(item) for item in resp.json().get("items", [])][:limit]

    def search_new_repos(self, *, since: date, min_stars: int, limit: int) -> list[RepoInfo]:
        """since 이후 만들어진 저장소 중 스타가 많은 순."""
        q = f"created:>={since.isoformat()} stars:>={min_stars} fork:false archived:false"
        return self.search_repos(q, limit=limit)

    def get_repo(self, full_name: str) -> RepoInfo | None:
        """저장소 현재 정보. 삭제되거나 비공개가 됐으면 None."""
        resp = self._get(f"/repos/{full_name}")
        if resp.status_code in (404, 451):
            return None
        if resp.status_code != 200:
            raise GitHubError(f"조회 실패 {full_name} {resp.status_code}")
        return parse_repo(resp.json())

    def get_readme(self, full_name: str, max_chars: int = 20000, *, deadline_s: float = 30.0) -> str | None:
        """README 원문 앞부분. 없으면 None.

        필요한 만큼(max_chars)만 스트리밍으로 받고 끊는다. 아주 큰 README 가 느리게 와도
        한 저장소에서 deadline_s 이상 붙잡히지 않는다.
        """
        path = f"/repos/{full_name}/readme"
        limit = max_chars * 4  # UTF-8 한 글자는 최대 4바이트
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                with self._http.stream(
                    "GET", path, headers={"Accept": "application/vnd.github.raw+json"}
                ) as resp:
                    if resp.status_code >= 500:
                        last = GitHubError(f"{resp.status_code} {path}")
                        self._sleep(2**attempt)
                        continue
                    if resp.status_code in (403, 429):
                        resp.read()
                        if self._is_rate_limited(resp):
                            reset = resp.headers.get("x-ratelimit-reset")
                            raise RateLimited(
                                f"rate limited: {path}", int(reset) if reset and reset.isdigit() else None
                            )
                    if resp.status_code in (404, 451):
                        return None
                    if resp.status_code != 200:
                        raise GitHubError(f"README 조회 실패 {full_name} {resp.status_code}")
                    buf = bytearray()
                    end = time.monotonic() + deadline_s
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) >= limit or time.monotonic() > end:
                            break
                    return bytes(buf).decode("utf-8", errors="replace")[:max_chars]
            except httpx.TransportError as e:
                last = e
                self._sleep(2**attempt)
        raise GitHubError(f"README 요청 실패(재시도 {self._retries}회): {full_name}: {last}")
