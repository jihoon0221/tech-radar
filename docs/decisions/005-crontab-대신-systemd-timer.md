# 005. 매일 실행은 crontab 대신 systemd timer 를 쓴다

- 날짜: 2026-11-11
- 결정: 매일 수집(03:00 KST)과 월간 시드 갱신을 systemd timer 로 실행한다.
- 이유 (004 장애에서 실제로 쓰인 것)
  - `journalctl -u techradar-collect` 로 날짜별 결과와 오류 문장을 바로 찾았다. 원인(301) 을 로그 한 줄로 확인했다.
  - `ExecStopPost` 로 수집이 실패한 날에도 백업이 돈다. crontab 은 성공·실패에 따라 후처리를 나누려면 스크립트를 따로 짜야 한다.
  - `Persistent=true` 로 서버가 꺼져 있던 시간의 실행을 켜지자마자 보충한다.
  - `MemoryMax=300M` 으로 1GB 서버에서 한 작업이 폭주해도 SSH 는 살아 있다.
- 대안: crontab — 설정은 한 줄로 더 간단하지만 위 네 가지를 직접 구현해야 한다.
