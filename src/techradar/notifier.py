from __future__ import annotations

import httpx


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """텔레그램으로 한 줄 알림. 설정이 없거나 실패해도 수집 자체는 멈추지 않는다."""
    if not token or not chat_id:
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:3500]},
            timeout=15.0,
        )
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def ping_healthcheck(url: str, ok: bool) -> bool:
    """헬스체크 서비스(예: healthchecks.io)에 '오늘도 돌았다'를 알린다.
    정해진 시간 안에 핑이 안 오면 그 서비스가 알림을 보내 준다 → 서버가 꺼져 아예 안 돈 경우도 잡힌다."""
    if not url:
        return False
    try:
        r = httpx.get(url if ok else url.rstrip("/") + "/fail", timeout=10.0)
        return r.status_code < 400
    except httpx.HTTPError:
        return False
