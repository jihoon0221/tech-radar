"""검증된 저장소 시드 적재.

내 관심 토픽마다 '스타가 충분하고 최근 1년 안에 관리된' 저장소 상위 N개를 한 번 채워 둔다.
다시 실행해도 겹치지 않으며(멱등), 한도에 걸려 멈추면 다시 실행해 이어서 진행한다.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from .collector import today_kst
from .config import Settings, load_env
from .github_client import GitHubClient, GitHubError, RateLimited
from .store import Store

DEFAULT_MIN_STARS = 1000


@dataclass(frozen=True)
class TopicSpec:
    name: str
    min_stars: int


def load_topics(path: str | Path, default_min_stars: int = DEFAULT_MIN_STARS) -> list[TopicSpec]:
    specs: list[TopicSpec] = []
    seen: set[str] = set()
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        name = parts[0].lower()
        if name in seen:
            continue
        seen.add(name)
        min_stars = int(parts[1]) if len(parts) > 1 else default_min_stars
        specs.append(TopicSpec(name, min_stars))
    return specs


@dataclass
class SeedResult:
    status: str = "ok"  # ok | rate_limited | error
    per_topic: dict[str, int] = field(default_factory=dict)
    new_repos: int = 0
    readmes: int = 0
    message: str = ""


def seed(
    client: GitHubClient,
    store: Store,
    topics: list[TopicSpec],
    *,
    today: date,
    per_topic: int = 30,
    pushed_days: int = 365,
    readme_max_chars: int = 20000,
    sleep: Callable[[float], None] = time.sleep,
    search_interval: float = 2.1,  # 검색 API 는 분당 30회
    progress: Callable[[str], object] = lambda _msg: None,
) -> SeedResult:
    res = SeedResult()
    pushed_since = today - timedelta(days=pushed_days)
    try:
        for i, t in enumerate(topics):
            if i:
                sleep(search_interval)
            q = (
                f"topic:{t.name} stars:>={t.min_stars} pushed:>={pushed_since.isoformat()} "
                "archived:false fork:false"
            )
            items = client.search_repos(q, limit=per_topic)
            for info in items:
                if store.upsert_repo(info, today, source="seed", seed_topic=t.name):
                    res.new_repos += 1
            res.per_topic[t.name] = len(items)
            progress(f"  검색 {i + 1}/{len(topics)} {t.name}: {len(items)}개")

        pending = store.repos_without_readme(limit=10_000)
        if pending:
            progress(f"README {len(pending)}개 받는 중 (중간에 멈춰도 다시 실행하면 이어서 받아요)")
        for j, name in enumerate(pending, 1):
            text = client.get_readme(name, readme_max_chars)
            store.save_readme(name, text or "")
            res.readmes += 1
            if j % 50 == 0 or j == len(pending):
                progress(f"  README {j}/{len(pending)}")
    except RateLimited as e:
        res.status, res.message = "rate_limited", str(e)
    except GitHubError as e:
        res.status, res.message = "error", str(e)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="관심 토픽의 검증된 저장소를 DB에 채운다")
    ap.add_argument("--topics", default="config/topics.txt")
    ap.add_argument("--per-topic", type=int, default=30)
    ap.add_argument("--pushed-days", type=int, default=365, help="최근 며칠 안에 커밋된 것만")
    args = ap.parse_args(argv)

    load_env()
    s = Settings.from_env()
    if not s.github_token:
        print("경고: GITHUB_TOKEN 이 없어 시간당 60회 제한이 적용됩니다. 곧 멈출 거예요.", file=sys.stderr)
    topics = load_topics(args.topics)
    client = GitHubClient(s.github_token)
    store = Store(s.db_path)
    print(f"토픽 {len(topics)}개 × 최대 {args.per_topic}개 적재 시작 (검색 간격 2초)…")
    try:
        res = seed(
            client, store, topics, today=today_kst(), per_topic=args.per_topic,
            pushed_days=args.pushed_days, readme_max_chars=s.readme_max_chars,
            progress=lambda m: print(m, flush=True),
        )
    finally:
        client.close()

    width = max((len(n) for n in res.per_topic), default=10)
    for name, n in sorted(res.per_topic.items(), key=lambda kv: kv[1]):
        flag = "  ← 0개: 토픽 이름 확인" if n == 0 else ""
        print(f"  {name:<{width}} {n:>3}{flag}")
    c = store.counts()
    print(
        f"[{res.status}] 신규 {res.new_repos}개 · README {res.readmes}개 | "
        f"DB 총 {c['repos']}개 (시드 {c['seeds']})"
    )
    if res.message:
        print(res.message, file=sys.stderr)
        if res.status == "rate_limited":
            print("한도가 풀린 뒤 같은 명령을 다시 실행하면 이어서 진행돼요.", file=sys.stderr)
    store.close()
    return 1 if res.status == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
