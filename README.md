# Job Monitoring System

기업 채용홈페이지를 자동 모니터링하여 새로운 채용공고를 Slack으로 알림하는 시스템

## 시스템 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Container                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │   Airflow   │  │   Airflow   │  │  Playwright │          │
│  │  Scheduler  │  │  Webserver  │  │  (Chromium) │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
         │                                    │
         ▼                                    ▼
┌─────────────────┐                 ┌─────────────────┐
│  Google Sheets  │                 │  채용 홈페이지   │
│  (회사 목록)     │                 │  (크롤링 대상)   │
└─────────────────┘                 └─────────────────┘
         │
         ▼
┌─────────────────┐
│  Slack Webhook  │
│  (알림 전송)     │
└─────────────────┘
```

## 프로젝트 구조

```
kowork-scaper/
├── src/
│   ├── job_monitoring_logic.py      # 메인 크롤링 로직
│   ├── job_monitoring_airflow_dag.py # Airflow DAG 정의
│   ├── analyze_titles.py            # CSS 선택자 자동 생성
│   ├── google_sheet_utils.py        # Google Sheets 연동
│   └── utils.py                     # 유틸리티 함수
├── data/                            # 크롤링 결과 저장
├── logs/                            # Airflow 로그
├── key/
│   └── credentials.json             # Google API 인증 키
├── docs/                            # 트러블슈팅 문서
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## DAG 스케줄

| DAG | 실행 시간 | 대상 | Slack 채널 |
|-----|----------|------|-----------|
| `job_monitoring_dag` | 매일 10시, 15시 | 일반 채용홈페이지 | `SLACK_WEBHOOK_URL` |
| `top5000_company_monitoring_dag` | 매일 19시 | 5000대 기업 | `TOP5000COMPANY_URL` |

## 동작 흐름

```
1. Airflow 스케줄러가 DAG 실행
   ↓
2. Google Sheets에서 회사 목록 로드
   ↓
3. 각 회사 채용 페이지 크롤링
   ├── 정적 사이트: requests 사용
   └── 동적 사이트: Playwright 사용
   ↓
4. CSS 선택자로 채용공고 추출
   ├── 기존 선택자 재사용
   └── 없으면 자동 생성
   ↓
5. 이전 결과와 비교하여 새 공고 감지
   ↓
6. Slack으로 알림 전송
   ↓
7. Google Sheets에 선택자 업데이트
```

## 설치 및 실행

### 1. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일 편집:
```env
AIRFLOW_UID=50000
GOOGLE_SHEET_KEY=your_spreadsheet_id
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
TOP5000COMPANY_URL=https://hooks.slack.com/services/...
```

### 2. Google API 설정

1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트 생성
2. Google Sheets API 활성화
3. 서비스 계정 생성 → JSON 키 다운로드
4. `key/credentials.json`에 저장
5. 서비스 계정 이메일을 Google Sheets에 편집자로 추가

### 3. Docker 실행

```bash
docker-compose up -d

# 웹 UI: http://localhost:8080
# 계정: admin / admin
```

## Google Sheets 구조

| 컬럼 | 설명 | 자동 생성 |
|------|------|----------|
| `회사_한글_이름` | 회사명 | X |
| `job_posting_url` | 채용 페이지 URL | X |
| `selector` | CSS 선택자 | O |
| `selenium_required` | 크롤링 방식 (0: requests, 1: Playwright) | O |

**새 회사 추가**: `회사_한글_이름`과 `job_posting_url`만 입력하면 나머지는 자동 생성

## 운영

### 로그 확인

```bash
# 실시간 로그
docker-compose logs -f

# 특정 DAG 로그
ls logs/dag_id=job_monitoring_dag/
```

### 수동 실행

Airflow Web UI에서 DAG 선택 → `Trigger DAG` 클릭

### 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| 모든 크롤링 실패 | Playwright 스레드 문제 | 컨테이너 재시작 |
| 특정 회사 실패 | URL 변경 또는 사이트 구조 변경 | Google Sheets에서 selector 삭제 후 재실행 |
| 메모리 부족 | 대량 처리 중 OOM | 스왑 메모리 추가 |

## 기술 스택

- **스케줄링**: Apache Airflow
- **크롤링**: Playwright (동적), Requests (정적)
- **파싱**: BeautifulSoup
- **데이터**: Google Sheets API, Pandas
- **알림**: Slack Webhook
- **인프라**: Docker Compose

## 트러블슈팅 문서

- `docs/TROUBLESHOOTING_2025-12-29.md` - 메모리, DAG, 슬랙 알림 문제
- `docs/TROUBLESHOOTING_2025-12-31.md` - signal, ThreadPoolExecutor, greenlet 문제
