#!/usr/bin/env bash
# 맥에서 실행: 테스트 → 코드 전송 → 서버 의존성 갱신.  사용: bash deploy/push.sh
set -euo pipefail
HOST="${HOST:-upbit-bot}"
APP="tech-radar"
cd "$(dirname "$0")/.."

echo "== 1. 테스트"
.venv/bin/pytest -q

echo "== 2. 코드 전송 ($HOST:~/$APP)"
ssh "$HOST" "mkdir -p ~/$APP/data"
rsync -az --delete \
  --exclude '.git/' --exclude '.env' --exclude 'data/' --exclude '.venv/' \
  --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude 'backup/' --exclude '*.egg-info/' \
  ./ "$HOST:~/$APP/"

echo "== 3. 서버 의존성 갱신"
ssh "$HOST" "cd ~/$APP && if test -d .venv; then .venv/bin/pip install -q -e .; else echo '첫 배포: setup_server.sh 를 실행하세요'; fi"

echo "== 4. 타이머 상태"
ssh "$HOST" "systemctl list-timers 'techradar-*' --no-pager 2>/dev/null || true"
