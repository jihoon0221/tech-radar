#!/usr/bin/env bash
# 서버에서 DB 를 하루 한 번 압축 백업하고 최근 7개만 남긴다. (수집 직후 자동 실행)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/backups
day=$(TZ=Asia/Seoul date +%F)
.venv/bin/python - "$day" <<'PY'
import sqlite3, sys
src = sqlite3.connect("data/techradar.db")
dst = sqlite3.connect(f"data/backups/techradar-{sys.argv[1]}.db")
src.backup(dst)   # 실행 중에도 안전한 일관된 사본
dst.close(); src.close()
PY
gzip -f "data/backups/techradar-$day.db"
ls -1t data/backups/techradar-*.db.gz | tail -n +8 | xargs -r rm --
echo "백업 완료: data/backups/techradar-$day.db.gz"
