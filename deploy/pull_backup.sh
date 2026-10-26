#!/usr/bin/env bash
# 맥에서 실행: 서버의 최신 DB 백업을 맥 backup/ 으로 가져온다.  사용: bash deploy/pull_backup.sh
set -euo pipefail
HOST="${HOST:-upbit-bot}"
cd "$(dirname "$0")/.."
mkdir -p backup
rsync -az "$HOST:~/tech-radar/data/backups/" backup/
ls -lh backup | tail -n 8
