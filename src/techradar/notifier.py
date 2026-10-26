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
