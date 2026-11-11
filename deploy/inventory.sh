#!/usr/bin/env bash
# 서버 상태 점검 (읽기 전용). 맥에서:  ssh radar 'bash -s' < deploy/inventory.sh
APP=~/tech-radar
sec(){ printf '\n== %s\n' "$1"; }

sec "1. 서버 기본"
. /etc/os-release && echo "$PRETTY_NAME · 커널 $(uname -r)"
timedatectl | grep -i "time zone"
python3 --version
df -h / | tail -1 | awk '{print "디스크: 전체 "$2" · 사용 "$3" · 남음 "$4" ("$5")"}'
free -m | awk 'NR==2{print "메모리: 전체 "$2"MB · 사용 "$3"MB · 가용 "$7"MB"} NR==3{print "스왑: "$2"MB 중 "$3"MB 사용"}'

sec "2. 꺼 둔 기본 서비스"
for s in fwupd ModemManager udisks2 upower; do printf '  %-14s %s\n' "$s" "$(systemctl is-enabled $s 2>/dev/null || echo 없음)"; done
cat /etc/systemd/journald.conf.d/size.conf 2>/dev/null | grep -v '^\[' | sed 's/^/  로그 상한 /'
journalctl --disk-usage 2>/dev/null | sed 's/^/  /'

sec "3. 실행 예약 (systemd timer)"
systemctl list-timers 'techradar-*' --no-pager | head -3
grep -h -E '^(ExecStart|ExecStopPost|MemoryMax|OnCalendar)' /etc/systemd/system/techradar-* 2>/dev/null | sort -u | sed 's/^/  /'
echo "  crontab: $(crontab -l 2>/dev/null | grep -vc '^#') 줄"

sec "4. 앱 폴더 $APP"
cd "$APP" 2>/dev/null || { echo "앱 폴더 없음"; exit 0; }
ls -1 | sed 's/^/  /'
echo "  git 커밋: (서버에는 .git 없음, push.sh 로 파일만 전송)"
.venv/bin/pip list 2>/dev/null | grep -i -E '^(httpx|tech-radar|psycopg|pgvector) ' | sed 's/^/  패키지 /'

sec "5. 설정 (.env, 값은 숨김)"
[ -f .env ] && sed -E 's/^([A-Z_]+) *=.*/\1/;/^#/d;/^$/d' .env | while read k; do
  v=$(grep -E "^$k *=" .env | head -1 | cut -d= -f2- | sed -E 's/ #.*//; s/^ +| +$//g')
  printf '  %-20s %s\n' "$k" "$([ -n "$v" ] && echo "설정됨" || echo "비어 있음")"; done
ls -l .env | awk '{print "  권한 "$1}'

sec "6. DB (SQLite)"
ls -lh data/techradar.db 2>/dev/null | awk '{print "  파일 "$9" · "$5}'
.venv/bin/python - <<'PY'
import sqlite3
db = sqlite3.connect("file:data/techradar.db?mode=ro", uri=True)
q = lambda s: db.execute(s).fetchone()
for t in ("repos", "star_snapshots", "readmes", "runs", "adoptions"):
    print(f"  {t:<15} {q(f'select count(*) from {t}')[0]:>6} 행")
print("  저장소 구성:", dict(db.execute("select source, count(*) from repos group by source").fetchall()))
print("  README 없는 저장소:", q("select count(*) from repos r left join readmes m on m.full_name=r.full_name where m.full_name is null")[0])
print("  스냅샷 기간:", q("select min(date), max(date), count(distinct date) from star_snapshots"))
print("  최근 실행:")
for r in db.execute("select started_at, status, found, tracked, readmes from runs order by id desc limit 5"):
    print("   ", tuple(r))
print("  상태별 실행 수:", dict(db.execute("select status, count(*) from runs group by status").fetchall()))
PY

sec "7. 백업"
ls -lh data/backups 2>/dev/null | tail -n +2 | awk '{print "  "$9"  "$5}'

sec "8. 열린 포트 / 방화벽 / PostgreSQL"
ss -tln 2>/dev/null | awk 'NR>1{print "  LISTEN "$4}'
echo "  ufw: $(sudo -n ufw status 2>/dev/null | head -1 || echo '확인 불가(sudo 필요) 또는 미사용')"
echo "  PostgreSQL: $(command -v psql >/dev/null && psql --version || echo '설치 안 됨')"
