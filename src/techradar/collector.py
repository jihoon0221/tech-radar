from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from .config import Settings
from .github_client import GitHubClient, GitHubError, RateLimited
from .store import Store


@dataclass
class RunResult:
    status: str  # ok | partial | rate_limited | error
    found: int = 0
    tracked: int = 0
    new_repos: int = 0
    readmes: int = 0
    failures: list[str] = field(default_factory=list)  # 개별 저장소 실패 "이름: 이유"
    message: str = ""


KST = timezone(timedelta(hours=9))


def today_kst() -> date:
    """기록 날짜는 한국 시간 기준 (새벽 3시 실행이 UTC 로는 전날이 되는 문제 방지)."""
    return datetime.now(KST).date()


def run(
    settings: Settings,
    client: GitHubClient,
    store: Store,
    *,
    today: date | None = None,
    notify: Callable[[str], object] | None = None,
) -> RunResult:
    """하루치 수집: 새 저장소 검색 → 추적 중인 저장소 스타 갱신 → 새 저장소 README 저장.

    같은 날 여러 번 실행해도 결과가 겹치지 않는다(멱등). 한도에 걸리면 지금까지 저장한 것은 남기고 멈춘다.
    """
    today = today or today_kst()
    notify = notify or (lambda _msg: None)
    res = RunResult(status="ok")
    run_id = store.start_run()

    try:
        # 1) 최근 만들어진 저장소 중 스타 많은 순 (이게 실패하면 그날 수집 자체가 실패)
        since = today - timedelta(days=settings.search_days)
        found = client.search_new_repos(
            since=since, min_stars=settings.min_stars, limit=settings.search_limit
        )
        seen: set[str] = set()
        for info in found:
            if store.upsert_repo(info, today):
                res.new_repos += 1
            store.add_snapshot(info.full_name, today, info.stars)
            seen.add(info.full_name)
        res.found = len(found)

        # 2) 이미 추적 중인 저장소의 오늘 스타 수. 한 저장소 실패가 나머지를 막지 않는다.
        for name in store.tracked_repos(today, settings.track_days):
            if name in seen:
                continue
            try:
                info = client.get_repo(name)
            except RateLimited:
                raise
            except GitHubError as e:
                res.failures.append(f"{name}: {e}")
                continue
            if info is None:  # 삭제·비공개
                continue
            if info.full_name != name:  # 이름이 바뀐 저장소 (301 을 따라가면 새 이름으로 온다)
                store.rename_repo(name, info.full_name)
            store.upsert_repo(info, today)
            store.add_snapshot(info.full_name, today, info.stars)
            res.tracked += 1

        # 3) README 는 처음 한 번만. 실패한 저장소는 건너뛰고 다음 날 다시 시도한다.
        for name in store.repos_without_readme(limit=settings.search_limit * 2):
            try:
                text = client.get_readme(name, settings.readme_max_chars)
            except RateLimited:
                raise
            except GitHubError as e:
                res.failures.append(f"{name}: {e}")
                continue
            store.save_readme(name, text or "")
            res.readmes += 1

    except RateLimited as e:
        res.status = "rate_limited"
        res.message = str(e)
        notify(f"[tech-radar] GitHub 호출 한도에 걸려 중간에 멈췄어요. 저장된 것은 유지됩니다. ({e})")
    except GitHubError as e:
        res.status = "error"
        res.message = str(e)
        notify(f"[tech-radar] 수집 실패: {e}")
    except Exception as e:  # 예상 못 한 오류도 기록하고 알린 뒤 다시 던진다
        store.finish_run(run_id, "error", res.found, res.tracked, res.readmes, repr(e))
        notify(f"[tech-radar] 수집 중 예외: {e!r}")
        raise

    if res.status == "ok" and res.failures:
        res.status = "partial"
        head = "; ".join(res.failures[:3])
        res.message = f"개별 실패 {len(res.failures)}건: {head}"
        notify(f"[tech-radar] 수집은 됐지만 일부 저장소 {len(res.failures)}건 실패. {head}")

    # 데이터 품질 검사: 수집 건수가 기준보다 적으면 조용히 넘어가지 않는다
    if res.status in ("ok", "partial") and res.found < settings.min_found:
        notify(f"[tech-radar] 오늘 검색 결과가 {res.found}건으로 기준({settings.min_found}건)보다 적어요.")
        if not res.message:
            res.message = f"검색 결과 {res.found}건 < 기준 {settings.min_found}건"

    store.finish_run(run_id, res.status, res.found, res.tracked, res.readmes, res.message)
    return res
