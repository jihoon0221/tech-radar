# tech-radar

매일 GitHub에서 새로 뜨는 저장소를 모아 두고(스타 증가량 추적), 나중에 AI가 카드로 정리하고 챗봇이 "이거 하려는데 쓸 거 있어?"에 답하게 만드는 개인 도구.

## 왜 만드나
쏟아지는 신기술 트렌드를 따라가지 못한다는 고민을 작은 자동화로 풀어 보려는 프로젝트. 진행 기록은 `docs/log.md`, 설계 결정은 `docs/decisions/`.

## 현재 단계: 1단계 시드 + 수집기
LLM 없이 두 종류의 저장소를 DB에 쌓는다.

- **시드** (`python -m techradar.seed`): `config/topics.txt`의 관심 토픽마다 검증된 저장소(스타 1,000+, 최근 1년 커밋) 상위 30개를 한 번 채운다. 월 1회 갱신.
- **수집기** (`python -m techradar`): 매일 새로 뜨는 저장소를 모은다.

1. 최근 N일 안에 만들어진 저장소를 스타 순으로 검색
2. 이미 본 저장소는 개별 조회로 오늘 스타 수 기록 (스타 증가량 계산용)
3. 처음 본 저장소의 README를 한 번만 저장

같은 날 여러 번 실행해도 결과가 겹치지 않고, GitHub 호출 한도에 걸리면 저장한 것은 남기고 멈춘 뒤 알림을 보낸다.

## 실행
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # GITHUB_TOKEN 입력 (커밋 금지)
pytest -q                   # 테스트 (GitHub 실제 접속 없음)
python -m techradar.seed    # 시드 적재 (토픽 41개: 검색 약 2분 + README 약 1,000개 5~10분)
python -m techradar         # 매일 수집 1회 실행
```

## 구성
- `src/techradar/github_client.py` GitHub API (재시도, 한도 감지)
- `src/techradar/store.py` SQLite (repos, star_snapshots, readmes, runs)
- `src/techradar/collector.py` 하루치 수집 흐름
- `src/techradar/seed.py` 검증된 저장소 시드 적재
- `src/techradar/notifier.py` 텔레그램 실패 알림 (선택)
- `config/topics.txt` 관심 토픽 목록 (내 관심사 정의)
