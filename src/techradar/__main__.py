from __future__ import annotations

import sys

from .collector import run
from .config import Settings, load_env
from .github_client import GitHubClient
from .notifier import ping_healthcheck, send_telegram
from .store import Store


def main() -> int:
    load_env()
    s = Settings.from_env()
    if not s.github_token:
        print("경고: GITHUB_TOKEN 이 없어 시간당 60회 제한이 적용됩니다.", file=sys.stderr)

    client = GitHubClient(s.github_token)
    store = Store(s.db_path)
    notify = lambda msg: send_telegram(s.telegram_bot_token, s.telegram_chat_id, msg)
    try:
        res = run(s, client, store, notify=notify)
    finally:
        client.close()

    c = store.counts()
    print(
        f"[{res.status}] 검색 {res.found}개(신규 {res.new_repos}) · 추적 갱신 {res.tracked}개 · "
        f"README {res.readmes}개 | DB 총 저장소 {c['repos']} · 스냅샷 {c['snapshots']}"
    )
    if res.message:
        print(res.message, file=sys.stderr)
    ping_healthcheck(s.healthcheck_url, ok=res.status != "error")
    store.close()
    return 1 if res.status == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
