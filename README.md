# Job Monitoring System (채용공고 자동 모니터링 시스템)

## 목차
- [시스템 개요](#시스템-개요)
- [주요 기능](#주요-기능)
- [프로젝트 구조](#프로젝트-구조)
- [설치 및 설정](#설치-및-설정)
- [상세 기술 문서](#상세-기술-문서)
- [운영 가이드](#운영-가이드)
- [문제해결](#문제해결)
- [개발자 가이드](#개발자-가이드)

## 시스템 개요

**Job Monitoring System**은 기업 채용홈페이지를 자동으로 모니터링하여 새로운 채용공고를 실시간으로 감지하고 Slack으로 알림을 보내는 자동화 시스템입니다.

### 핵심 특징
- **지능형 크롤링**: 동적/정적 웹사이트 자동 구분하여 최적화된 방법으로 크롤링
- **자동 선택자 감지**: 패턴 분석 기반으로 채용공고 영역을 자동 식별
- **실시간 알림**: 새로운 채용공고 발견 시 Slack으로 즉시 알림
- **대용량 처리**: 5000대 기업 채용공고를 청크 단위로 안전하게 처리
- **웹 기반 설정**: Google Sheets를 통한 편리한 설정 관리

### 처리 대상
1. **일반 채용홈페이지**: 매일 10시, 15시 실행
2. **5000대 기업**: 매일 19시 실행 (100개씩 청크 처리)

## 주요 기능

### 1. 자동 채용공고 감지
- CSS 선택자 자동 생성 및 최적화
- 채용공고 패턴 학습을 통한 정확도 향상
- 동적 웹사이트(SPA/React) 자동 감지

### 2. 실시간 모니터링
- 기존 채용공고와 비교하여 변경사항 감지
- 새로운 채용공고 발견 시 즉시 Slack 알림
- 외국인 채용공고 키워드 필터링 및 하이라이트

### 3. 병렬 처리 및 성능 최적화
- ThreadPoolExecutor를 활용한 동시 처리 (최대 3개 스레드)
- 검증된 CSS 선택자 캐싱으로 성능 향상
- 대용량 데이터 청크 단위 처리

### 4. 안정적인 데이터 관리
- Google Sheets 연동을 통한 중앙화된 설정 관리
- CSV 파일을 통한 채용공고 이력 관리
- 실시간 데이터 동기화 및 백업

## 프로젝트 구조

```
job-monitoring/
├── src/                              # 메인 소스코드
│   ├── job_monitoring_logic.py       # 핵심 크롤링 로직 (979줄)
│   ├── analyze_titles.py             # 채용공고 선택자 패턴 분석기 (729줄)
│   ├── google_sheet_utils.py         # Google Sheets 연동 (119줄)
│   ├── utils.py                      # 유틸리티 함수들 (137줄)
│   └── job_monitoring_airflow_dag.py # Airflow 스케줄링 (66줄)
├── data/                             # 데이터 파일들
│   ├── job_postings_latest.csv       # 최신 채용공고 데이터
│   └── top_5000_postings_latest.csv  # 5000대 기업 채용공고
├── logs/                             # 로그 파일들
│   ├── dag_id=job_monitoring_dag/
│   ├── dag_id=top5000_company_monitoring_dag/
│   └── scheduler/
├── key/                              # 인증 파일들
│   └── credentials.json              # Google API 인증 키
├── scripts/                          # 배포 스크립트들
│   ├── lambda_function.py            # AWS Lambda 함수
│   └── setup-aws-automation.sh       # AWS 자동 설정
├── archive_temp/                     # 임시 보관 파일들 (17개 디버그 스크립트)
├── docker-compose.yml                # Docker 컨테이너 설정
├── Dockerfile                        # Docker 이미지 빌드
├── requirements.txt                  # Python 의존성
└── .env                              # 환경 변수 설정
```

## 설치 및 설정

### 1. 필수 요구사항

```bash
# Python 3.8+ 필요
python --version

# Docker & Docker Compose 설치 확인
docker --version
docker-compose --version
```

### 2. 프로젝트 클론 및 초기 설정

```bash
# 저장소 클론
git clone https://github.com/kowork-team/kowork-scaper.git
cd kowork-scaper

# 환경 변수 설정
cp .env.example .env
# .env 파일을 열어서 실제 값으로 수정 필요
```

### 3. 환경 변수 설정 (.env 파일)

```env
# Airflow 설정
AIRFLOW_UID=50000

# Google Sheets API 설정
GOOGLE_SHEET_KEY=1dBVxHQp3UjDY4RdDZxtC4j0yuxFeRO4sqhuo240432k

# Slack Webhook URL들
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR_WEBHOOK_URL
TOP5000COMPANY_URL=https://hooks.slack.com/services/YOUR_TOP5000_WEBHOOK_URL

# 크롤링 설정
MAX_WORKERS=3  # 병렬 처리 스레드 수
```

### 4. Google API 인증 설정

1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트 생성
2. Google Sheets API 활성화
3. 서비스 계정 생성 후 JSON 키 다운로드
4. 다운로드받은 파일을 `key/credentials.json`에 저장

### 5. Docker로 시스템 실행

```bash
# Docker 컨테이너 빌드 및 실행
docker-compose up -d

# 실행 상태 확인
docker-compose ps

# 로그 확인
docker-compose logs -f webserver
```

### 6. Airflow 웹 UI 접속

- URL: http://localhost:8080
- 기본 계정: admin / admin
- DAG 활성화: `job_monitoring_dag`, `top5000_company_monitoring_dag`

## 상세 기술 문서

### 핵심 클래스 및 함수 상세 설명

#### 1. JobMonitoringDAG 클래스 (src/job_monitoring_logic.py)

**역할**: 전체 채용공고 모니터링 프로세스 관리

##### 주요 메서드:

**`__init__(base_dir, worksheet_name, webhook_url_env, results_filename)`**
- 시스템 초기화 및 설정
- Google Sheets 연동을 위한 설정
- HTTP 세션 설정 (헤더, 재시도 로직 등)
- 병렬 처리를 위한 ThreadPoolExecutor 설정

**`run()`**
- 메인 실행 로직
- Google Sheets에서 회사 목록 로드
- 5000대 기업의 경우 청크 단위 처리 (100개씩)
- 일반 회사들은 전체 일괄 처리

**`process_companies_integrated(df)`**
- 회사 전처리와 크롤링을 통합 처리
- Selenium 필요성 자동 판단
- CSS 선택자 자동 생성
- 병렬 처리로 성능 최적화
- 반환값: (처리된_DataFrame, 현재_채용공고, 실패_회사_목록)

**`preprocess_companies(df)`**
- 회사별 웹사이트 분석 및 전처리
- 동적/정적 웹사이트 구분
- CSS 선택자 자동 감지 및 검증
- 기존 검증된 선택자 재활용으로 성능 향상

**`stabilize_selectors(df)`**
- CSS 선택자 안정화 처리
- 브라우저별 호환성 개선
- 선택자 최적화 (불필요한 속성 제거)

**`crawl_jobs(df_config)`**
- 실제 채용공고 크롤링 수행
- Playwright/Requests 방식 자동 선택
- 병렬 처리로 속도 향상
- 반환값: (채용공고_딕셔너리, 실패_회사_목록)

**`compare_and_notify(current_jobs, failed_companies, chunk_info, save, send_notifications)`**
- 이전 데이터와 비교하여 변경사항 감지
- 새로운 채용공고 발견 시 Slack 알림
- send_notifications=False일 때는 알림 없이 데이터만 수집 (청크 처리용)

**`get_html_content(url, use_selenium, selector)`**
- 웹페이지 HTML 가져오기 (선택자 분석용)
- 정적 사이트: requests 사용
- 동적 사이트: Playwright 브라우저 자동화 사용

**`get_html_content_for_crawling(url, use_selenium, selector)`**
- 실제 크롤링용 HTML 가져오기
- 현실적인 브라우저 헤더 사용
- 타임아웃 및 재시도 로직 포함

**`send_slack_notification(new_jobs, warnings, failed_companies, chunk_info)`**
- Slack으로 알림 메시지 전송
- 외국인 채용공고 키워드 하이라이트 처리
- 회사별 상세 시간 정보 포함 (월일(요일) 시분 형식)
- 마크다운 형식으로 가독성 향상

#### 2. JobPostingSelectorAnalyzer 클래스 (src/analyze_titles.py)

**역할**: 채용공고 영역을 자동으로 감지하고 최적의 CSS 선택자 생성

##### 주요 메서드:

**`find_best_selector(soup)`**
- BeautifulSoup 객체에서 채용공고 영역 자동 탐지
- 다양한 선택자 후보군 생성 및 평가
- 가중치 기반 최적 선택자 선택
- 반환값: (최적_선택자, 신뢰도_점수)

**`_is_potential_job_posting(text)`**
- 텍스트가 채용공고인지 패턴 기반 판단
- 채용 관련 키워드 패턴 매칭
- 블랙리스트 필터링 (네비게이션, 광고 등 제외)

**`_calculate_job_posting_weight(element)`**
- HTML 요소의 채용공고 적합도 점수 계산
- 클래스명, ID, 텍스트 내용 종합 분석
- 패턴 매칭을 통한 가중치 부여

**`_find_job_posting_containers(soup)`**
- 채용공고를 포함할 가능성이 높은 컨테이너 탐지
- 계층적 구조 분석
- 반복 패턴 감지

**`_validate_selector(soup, selector)`**
- 선택자의 유효성 및 품질 검증
- 채용공고 비율 계산
- 중복 제거 및 정확도 측정

#### 3. GoogleSheetManager 클래스 (src/google_sheet_utils.py)

**역할**: Google Sheets와의 데이터 동기화 관리

##### 주요 메서드:

**`_authorize()`**
- Google Sheets API 인증 처리
- credentials.json 파일 기반 인증
- 자동 토큰 갱신 처리

**`get_all_records_as_df(worksheet_name)`**
- 지정된 워크시트의 모든 데이터를 Pandas DataFrame으로 변환
- 헤더 자동 인식 및 데이터 타입 최적화

**`update_sheet_from_df(df, worksheet_name)`**
- DataFrame 데이터를 Google Sheets에 업데이트
- 헤더 보존하며 안전한 업데이트
- 대용량 데이터 배치 처리

**`safe_update_rows(df, worksheet_name)`**
- 행별 안전한 업데이트 (데이터 손실 방지)
- 중간 저장 기능으로 안정성 보장

#### 4. SeleniumRequirementChecker 클래스 (src/utils.py)

**역할**: 웹사이트별 최적 크롤링 방법 자동 결정

##### 주요 메서드:

**`check_selenium_requirement(url)`**
- 웹사이트 분석하여 Selenium 필요성 자동 판단
- SPA(Single Page Application) 감지
- JavaScript 의존도 분석
- 반환값: 0(requests), 1(Selenium 필요), -1(오류)

**`_is_spa_site(url)`**
- React, Vue, Angular 등 SPA 프레임워크 사용 감지
- JavaScript 렌더링 필요성 판단

**`stabilize_selector(selector, conservative)`**
- CSS 선택자 정규화 및 안정화
- 브라우저 호환성 향상
- conservative=True: 안전한 최소 변경
- conservative=False: 적극적 최적화

### 데이터 흐름도

```
1. Google Sheets 로드
   ↓
2. 회사별 전처리
   ├─ Selenium 필요성 체크
   ├─ CSS 선택자 자동 생성
   └─ 선택자 검증 및 안정화
   ↓
3. 병렬 크롤링 실행
   ├─ HTML 콘텐츠 추출
   ├─ 채용공고 파싱
   └─ 데이터 정제
   ↓
4. 변경사항 비교
   ├─ 기존 데이터와 대조
   ├─ 새 채용공고 감지
   └─ 의심스러운 변경사항 체크
   ↓
5. 알림 및 저장
   ├─ Slack 알림 전송
   ├─ CSV 파일 업데이트
   └─ Google Sheets 동기화
```

## 운영 가이드

### 일상 운영 작업

#### 1. 시스템 상태 확인

```bash
# Docker 컨테이너 상태 확인
docker-compose ps

# 로그 실시간 모니터링
docker-compose logs -f webserver scheduler

# 디스크 사용량 확인
du -sh data/ logs/
```

#### 2. Airflow DAG 관리

**웹 UI에서 확인할 항목:**
- DAG 실행 상태 (Success/Failed/Running)
- 최근 실행 기록
- 실행 시간 및 성능 지표

**DAG 수동 실행:**
```bash
# 일반 채용홈페이지 모니터링
docker-compose exec webserver airflow dags trigger job_monitoring_dag

# 5000대 기업 모니터링
docker-compose exec webserver airflow dags trigger top5000_company_monitoring_dag
```

#### 3. Google Sheets 설정 관리

**시트 구조:**
- **[등록]채용홈페이지 모음**: 일반 기업 설정
  - 회사_한글_이름: 회사명
  - job_posting_url: 채용홈페이지 URL
  - selector: CSS 선택자 (자동 생성)
  - selenium_required: 크롤링 방식 (0: requests, 1: Selenium, -1: 실패)

- **5000대_기업**: 대기업 설정 (동일 구조)

- **외국인_공고_키워드**: 외국인 채용공고 키워드 관리

#### 4. 새로운 회사 추가

1. Google Sheets에서 회사 정보 추가
   ```
   회사_한글_이름: 신규회사명
   job_posting_url: https://company.com/careers
   selector: (비워둠 - 자동 생성됨)
   selenium_required: (비워둠 - 자동 판단됨)
   ```

2. 다음 실행 시 자동으로 선택자 생성됨

3. 실행 후 Google Sheets에서 결과 확인
   - selector: 생성된 CSS 선택자
   - selenium_required: 판단된 크롤링 방식

#### 5. 문제 있는 회사 처리

**selenium_required 값의 의미:**
- `0`: requests 방식으로 크롤링 가능
- `1`: Selenium 브라우저 자동화 필요
- `-1`: HTML 가져오기 실패 (접근 불가, 차단 등)
- `-2`: 선택자 생성 실패 (채용공고 영역 찾을 수 없음)

**문제 해결 방법:**
1. `-1` (HTML 실패): URL 확인, 사이트 접근 가능성 체크
2. `-2` (선택자 실패): 사이트 구조 변경 확인, 수동 선택자 입력 고려

### 성능 최적화

#### 1. 병렬 처리 설정

```env
# .env 파일에서 조정
MAX_WORKERS=3  # 동시 처리 스레드 수 (너무 높으면 차단 위험)
```

#### 2. 청크 크기 조정

```python
# src/job_monitoring_logic.py 106라인
chunk_size = 100  # 5000대 기업 청크 크기 (메모리 사용량과 성능 트레이드오프)
```

#### 3. 대기 시간 조정

```python
# src/job_monitoring_logic.py 145라인
time.sleep(120)  # 청크 간 대기시간 (초) - 서버 부하 방지
```

### 백업 및 복구

#### 1. 데이터 백업

```bash
# 중요 데이터 백업
cp -r data/ backup/data_$(date +%Y%m%d)/
cp key/credentials.json backup/
cp .env backup/
```

#### 2. 설정 복구

```bash
# Google Sheets 재연동
# 1. key/credentials.json 복원
# 2. .env 파일의 GOOGLE_SHEET_KEY 확인
# 3. Docker 컨테이너 재시작
docker-compose restart
```

### 모니터링 및 알림

#### 1. 시스템 건강도 체크

**확인할 지표:**
- DAG 실행 성공률 (95% 이상 유지)
- 평균 실행 시간 (일반: ~30분, 5000대기업: ~2시간)
- 메모리 사용량 (8GB 이하)
- 디스크 사용량 (로그 정리 필요 시 경고)

**로그 파일 정리:**
```bash
# 30일 이상 된 로그 정리
find logs/ -name "*.log" -mtime +30 -delete

# 대용량 로그 압축
find logs/ -name "*.log" -size +100M -exec gzip {} \;
```

#### 2. Slack 알림 설정

**알림 채널 분리:**
- 일반 채용홈페이지: `SLACK_WEBHOOK_URL`
- 5000대 기업: `TOP5000COMPANY_URL`

**알림 내용:**
- 새 채용공고 발견 시 즉시 알림
- 외국인 채용공고 키워드 하이라이트
- 시간 정보 포함 (월일(요일) 시분)
- 확인 필요 공고 및 크롤링 실패 요약

## 문제해결

### 자주 발생하는 문제들

#### 1. Docker 관련 문제

**문제**: 컨테이너 시작 실패
```bash
# 해결방법
docker-compose down
docker system prune -f  # 사용하지 않는 이미지/컨테이너 정리
docker-compose up -d --build
```

**문제**: 포트 충돌 (8080, 5432 등)
```bash
# 사용 중인 포트 확인
lsof -i :8080
# 또는 docker-compose.yml에서 포트 변경
```

**문제**: ARM64(M1 Mac) 호환성 문제
```bash
# Dockerfile에서 아키텍처별 처리 이미 구현됨
# 필요시 플랫폼 명시적 지정
docker-compose build --build-arg TARGETARCH=arm64
```

#### 2. 크롤링 관련 문제

**문제**: 특정 사이트 접근 차단
- 증상: selenium_required가 -1로 설정됨
- 해결: User-Agent 변경, 요청 간격 증가 고려
- 임시방편: 해당 회사의 selenium_required를 수동으로 1로 설정

**문제**: 선택자 생성 실패
- 증상: selenium_required가 -2로 설정됨
- 원인: 사이트 구조 변경, 채용공고 영역 인식 실패
- 해결: 사이트 직접 확인 후 수동으로 선택자 입력

**문제**: 채용공고 중복/누락
- 원인: 선택자 부정확, 사이트 구조 변경
- 해결: Google Sheets에서 해당 회사의 selector 값 삭제 (자동 재생성됨)

#### 3. Google Sheets 연동 문제

**문제**: 인증 실패
```
google.auth.exceptions.DefaultCredentialsError
```
- 해결: key/credentials.json 파일 확인
- Google Cloud Console에서 서비스 계정 권한 확인

**문제**: 시트 접근 권한 오류
- 해결: 서비스 계정 이메일을 Google Sheets에 편집자로 추가

**문제**: API 할당량 초과
- 증상: API quota exceeded 에러
- 해결: Google Cloud Console에서 API 사용량 확인, 필요시 할당량 증가 요청

#### 4. Slack 알림 문제

**문제**: 알림 전송 실패
- Webhook URL 유효성 확인
- Slack 앱 권한 설정 확인

**문제**: 마크다운 형식 오류
- 특수문자 있는 회사명에서 발생 가능
- 로그에서 실제 전송된 메시지 형식 확인

### 로그 분석

#### 1. 주요 로그 위치
```
logs/dag_id=job_monitoring_dag/          # 일반 모니터링 로그
logs/dag_id=top5000_company_monitoring_dag/  # 5000대 기업 로그
logs/scheduler/                          # 스케줄러 로그
```

#### 2. 에러 패턴별 해결방법

**타임아웃 에러:**
```
playwright._impl._api_structures.TimeoutError
```
- 해결: 네트워크 상태 확인, 타임아웃 값 증가 고려

**메모리 부족:**
```
MemoryError 또는 OOMKilled
```
- 해결: chunk_size 감소, MAX_WORKERS 감소

**CSV 파일 권한 오류:**
```
PermissionError: [Errno 13]
```
- 해결: 파일 권한 확인, Docker 볼륨 마운트 문제 확인

### 응급 상황 대처

#### 1. 시스템 완전 중단 시

```bash
# 1. 모든 컨테이너 중지
docker-compose down

# 2. 로그 백업
cp -r logs/ emergency_backup/logs_$(date +%Y%m%d_%H%M)/

# 3. 시스템 재시작
docker-compose up -d

# 4. 상태 확인
docker-compose ps
docker-compose logs webserver | tail -50
```

#### 2. 데이터 손실 위험 시

```bash
# 즉시 중요 데이터 백업
tar -czf emergency_backup_$(date +%Y%m%d_%H%M).tar.gz data/ key/ .env

# Google Sheets 수동 백업 (웹에서)
# File -> Download -> Excel (.xlsx)
```

#### 3. 성능 급격히 저하 시

```bash
# 리소스 사용량 확인
docker stats

# 대용량 로그 파일 확인
find logs/ -size +1G -ls

# 임시 성능 향상 (재시작)
docker-compose restart scheduler webserver
```

## 개발자 가이드

### 개발 환경 설정

```bash
# 로컬 개발용 Python 환경
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 코드 포맷팅
pip install black isort
black src/
isort src/
```

### 코드 구조 이해

#### 1. 새로운 기능 추가

**새로운 선택자 패턴 추가:**
```python
# src/analyze_titles.py의 KNOWN_PATTERNS에 추가
KNOWN_PATTERNS = [
    # 기존 패턴들...
    {'pattern': 'new_pattern_regex', 'weight': 0.8}
]
```

**새로운 필터링 키워드 추가:**
- Google Sheets의 '외국인_공고_키워드' 시트에 직접 추가
- 시스템 재시작 없이 즉시 반영

#### 2. 성능 최적화 포인트

**병렬 처리 개선:**
```python
# src/job_monitoring_logic.py 36라인
self.max_workers = int(os.getenv('MAX_WORKERS', '3'))
```

**캐싱 활용:**
```python
# src/job_monitoring_logic.py 453라인
existing_selectors = self._get_existing_selectors(df)
```

**메모리 최적화:**
```python
# 청크 크기 조정으로 메모리 사용량 제어
chunk_size = 100  # 필요시 50으로 감소
```

### 테스트

#### 1. 단위 테스트

```python
# 선택자 분석기 테스트
from src.analyze_titles import JobPostingSelectorAnalyzer
analyzer = JobPostingSelectorAnalyzer()

# HTML 샘플로 테스트
with open('test_sample.html', 'r') as f:
    html = f.read()
    soup = BeautifulSoup(html, 'html.parser')
    selector, score = analyzer.find_best_selector(soup)
    print(f"Generated selector: {selector}, Score: {score}")
```

#### 2. 통합 테스트

```python
# 전체 파이프라인 테스트
from src.job_monitoring_logic import JobMonitoringDAG

# 테스트용 DAG 생성
dag = JobMonitoringDAG(
    base_dir='/path/to/test',
    worksheet_name='테스트시트',
    webhook_url_env='TEST_WEBHOOK_URL'
)

# 소규모 데이터로 테스트
test_df = pd.DataFrame([{
    '회사_한글_이름': '테스트회사',
    'job_posting_url': 'https://test.com/careers',
    'selector': '',
    'selenium_required': ''
}])

result = dag.process_companies_integrated(test_df)
```

### 배포

#### 1. 프로덕션 배포

```bash
# Git 최신화
git pull origin main

# 컨테이너 재빌드 (코드 변경 시)
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# 배포 확인
docker-compose logs -f webserver
```

#### 2. 설정 변경 시 주의사항

- `.env` 파일 변경 시 컨테이너 재시작 필요
- Google Sheets 구조 변경 시 호환성 확인
- Slack Webhook URL 변경 시 테스트 메시지 전송으로 확인

### 확장 가능성

#### 1. 새로운 알림 채널 추가
```python
# src/job_monitoring_logic.py의 send_slack_notification 참고
def send_teams_notification(self, ...):
    # Microsoft Teams 알림 구현
    pass

def send_email_notification(self, ...):
    # 이메일 알림 구현
    pass
```

#### 2. 새로운 데이터 소스 연동
```python
# src/google_sheet_utils.py 참고하여 새 매니저 클래스 구현
class AirtableManager:
    def get_company_list(self):
        # Airtable에서 회사 목록 가져오기
        pass
```

#### 3. 패턴 분석 기능 강화
```python
# src/analyze_titles.py에 고급 패턴 분석 추가
def enhanced_pattern_analysis(self, html_content):
    # 더 정교한 패턴 매칭을 통한 선택자 생성
    pass
```

---

## 지원 및 연락처

이 시스템의 유지보수나 문제 해결이 필요한 경우:

1. **즉시 해결이 필요한 경우**: 이 README의 [문제해결](#문제해결) 섹션 참조
2. **시스템 로그 확인**: `logs/` 디렉토리의 최신 로그 파일 분석
3. **Google Sheets 접근**: 서비스 계정에 편집 권한이 있는지 확인
4. **백업 복구**: `backup/` 디렉토리에서 최신 백업 활용

이 문서는 시스템의 모든 기능과 운영 방법을 상세히 설명합니다. 추가 질문이나 개선 사항이 있다면 코드의 주석과 로그를 참조하여 문제를 해결할 수 있습니다.

---
**마지막 업데이트**: 2024년 9월 25일
**시스템 버전**: v2.1.0
**문서 버전**: v1.0.0
