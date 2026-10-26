#!/usr/bin/env bash
# 서버에서 처음 한 번 실행:  ssh -t <host> 'bash ~/tech-radar/deploy/setup_server.sh'
# 다시 실행해도 안전하다. (apt upgrade 는 하지 않는다: NCP 커널 업데이트 미지원)
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(id -un)"
echo "== 앱 위치 $APP_DIR · 실행 사용자 $RUN_USER"

echo "== 1. 서버 경량화 (가상서버에 필요 없는 기본 서비스 끄기, 로그 100MB 제한)"
sudo systemctl disable --now fwupd ModemManager udisks2 upower 2>/dev/null || true
sudo systemctl mask fwupd >/dev/null 2>&1 || true
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=100M\n' | sudo tee /etc/systemd/journald.conf.d/size.conf >/dev/null
sudo systemctl restart systemd-journald

echo "== 2. 파이썬 환경"
cd "$APP_DIR"
if ! test -d .venv; then
  python3 -m venv .venv || { echo "venv 생성 실패: sudo apt install -y python3-venv 후 다시 실행하세요"; exit 1; }
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e .
mkdir -p data
chmod +x deploy/*.sh
if test -f .env; then chmod 600 .env; else echo "주의: .env 가 없습니다 (scp 로 먼저 올리세요)"; fi

echo "== 3. systemd 타이머 등록"
for f in deploy/systemd/*.service deploy/systemd/*.timer; do
  sed -e "s#@APP_DIR@#$APP_DIR#g" -e "s#@USER@#$RUN_USER#g" "$f" \
    | sudo tee "/etc/systemd/system/$(basename "$f")" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now techradar-collect.timer techradar-seed.timer

echo "== 4. 확인"
timedatectl | grep -i "time zone" || true
systemctl list-timers 'techradar-*' --no-pager
free -m | sed -n 1,2p
