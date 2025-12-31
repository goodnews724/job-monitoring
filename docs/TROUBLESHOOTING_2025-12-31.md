# 트러블슈팅 기록 (2025-12-31)

## 배경지식: 스레드, Greenlet, Context

오늘 발생한 에러를 이해하려면 이 개념들을 알아야 한다.

### 스레드 (Thread)

**비유**: 식당의 직원

```
[프로세스 = 식당]
├── 스레드1 (주방장) - 요리 담당
├── 스레드2 (서빙직원) - 서빙 담당
└── 스레드3 (카운터) - 계산 담당
```

- **프로세스**: 실행 중인 프로그램 (식당 전체)
- **스레드**: 프로세스 안에서 동시에 실행되는 작업 단위 (각 직원)
- 같은 식당(프로세스) 안에서 일하지만, 각자 독립적으로 움직임
- **문제**: 주방장이 쓰던 칼을 서빙직원이 갑자기 가져가면 충돌 발생

```python
# ThreadPoolExecutor = 임시 직원 고용
with ThreadPoolExecutor(max_workers=1) as executor:
    # 새 직원(다른 스레드)에게 일 시킴
    future = executor.submit(do_work, context)
```

### Greenlet

**비유**: 한 직원이 여러 일을 번갈아 하는 것

```
[일반 스레드]
직원A가 요리 → 직원B가 서빙 → 직원C가 계산
(3명이 동시에)

[Greenlet]
직원A가 요리 → (잠깐 멈춤) → 서빙 → (잠깐 멈춤) → 계산
(1명이 번갈아가며)
```

- **Greenlet**: "경량 스레드" 또는 "코루틴"
- 실제 OS 스레드가 아니라, 프로그램 내에서 **협력적으로 전환**하는 방식
- 한 번에 하나만 실행되지만, 빠르게 전환해서 동시에 하는 것처럼 보임
- **Playwright는 내부적으로 greenlet 사용** → 생성된 스레드에서만 작동

### Context (Playwright)

**비유**: 브라우저의 시크릿 창

```
Chrome 브라우저 (browser)
├── 시크릿 창1 (context) - 쿠키A, 설정A
│   ├── 탭1 (page)
│   ├── 탭2 (page)
│   └── 탭3 (page)
│
└── 시크릿 창2 (context) - 쿠키B, 설정B
    ├── 탭1 (page)
    └── 탭2 (page)
```

- **Browser**: 크롬 프로그램 자체
- **Context**: 독립된 브라우저 세션 (시크릿 창처럼 쿠키/설정이 분리됨)
- **Page**: 탭 하나

**이 코드에서:**
```python
# 1. 브라우저 실행
playwright = sync_playwright().start()
browser = playwright.chromium.launch(headless=True)

# 2. Context 생성 (시크릿 창 열기)
context = browser.new_context()
context.set_default_timeout(30000)  # 이 창의 모든 탭에 30초 타임아웃 적용

# 3. Page 생성 (탭 열기)
page = context.new_page()
page.goto("https://samsung.com/careers")
```

**왜 Context를 재사용하나?**
```python
# ❌ 비효율적: 매번 브라우저 새로 실행
for url in 2700개_URL:
    browser = playwright.chromium.launch()  # 매번 2~3초 소요
    # ...
# 총: 2700 × 3초 = 2시간+ 낭비

# ✅ 효율적: Context 재사용
context = browser.new_context()  # 1번만
for url in 2700개_URL:
    page = context.new_page()    # 탭만 새로 열기 (빠름)
    page.goto(url)
    page.close()
```

### 오늘 문제의 핵심

```
[메인 스레드]에서 Playwright context 생성
     │
     ▼
[ThreadPoolExecutor가 새 스레드 생성]
     │
     ▼
새 스레드에서 context 사용하려고 함
     │
     ▼
💥 "Cannot switch to a different thread"
```

Context는 태어난 스레드(메인)에 묶여있어서, 다른 스레드에서 쓰려고 하면 에러 발생.
마치 "A 식당 직원증으로 B 식당에서 일하려는 것"과 같음.

---

## signal.alarm()으로 인한 전체 크롤링 실패

### 증상
- 5000대 기업 DAG에서 **모든** 크롤링이 실패
- 로그에 동일한 에러 반복:
  ```
  ERROR - 크롤링용 HTML 가져오기 실패 (기타 오류): [URL] - ValueError: signal only works in main thread
  ```
- 성공한 크롤링 0개, 실패 2670개

### 원인
- `get_html_content_for_crawling_with_browser` 함수에서 `signal.alarm()` 사용
- `signal.alarm()`은 **메인 스레드에서만** 동작
- Airflow 워커가 멀티스레드 환경에서 실행되어 메인 스레드가 아닌 곳에서 호출됨
- 결과: 모든 크롤링이 시작 즉시 ValueError로 실패

### 문제 코드
```python
# job_monitoring_logic.py (1326~1345번 줄)
import signal

def timeout_handler(signum, frame):
    raise TimeoutError("크롤링 타임아웃")

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(timeout_seconds)  # ❌ 메인 스레드가 아니면 실패
```

### 해결책
`signal.alarm()` 코드 제거, Playwright 내장 타임아웃만 사용:

```python
# 변경 후 - signal 관련 코드 모두 제거
def get_html_content_for_crawling_with_browser(self, url, use_selenium, context=None, selector=None):
    try:
        # Playwright 자체 타임아웃만 사용
        if 'toss.im' in url:
            page_timeout = 60000  # 60초
            wait_time = 3
        else:
            page_timeout = 20000  # 20초
            wait_time = 1
        # ... (signal 코드 없음)
```

### 수정된 함수
- `get_html_content_for_crawling_with_browser()` - signal 제거
- `get_html_content_for_crawling_old()` - signal 제거 (DEPRECATED 함수)

### 교훈
- `signal` 모듈은 메인 스레드 전용이므로 Airflow, Celery 등 워커 환경에서 사용 불가
- 타임아웃은 라이브러리 내장 기능(Playwright `timeout` 파라미터) 또는 `threading` 기반으로 구현해야 함

---

---

## ThreadPoolExecutor로 인한 Playwright greenlet 스레드 충돌

### 증상
- 크롤링 시작 직후 모든 요청 실패
- 로그에 동일한 에러 반복:
  ```
  ERROR - 크롤링용 HTML 가져오기 실패 (기타 오류): [URL] - error: Cannot switch to a different thread
  Current:  <greenlet.greenlet object at 0xffff904c5b40 ...>
  Expected: <greenlet.greenlet object at 0xffffa301fe40 ...>
  ```

### 원인
- `_crawl_single_url_with_browser` 함수에서 `ThreadPoolExecutor`를 사용해 크롤링 실행
- Playwright `context`를 다른 스레드로 전달
- Playwright sync API는 내부적으로 greenlet을 사용하며, 생성된 스레드에서만 사용 가능
- 다른 스레드에서 context 사용 시 greenlet 충돌 발생

### 문제 코드
```python
# ThreadPoolExecutor에서 context를 다른 스레드로 전달
with ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(
        self.get_html_content_for_crawling_with_browser,
        url, use_selenium, context, selector  # ❌ context는 다른 스레드에서 사용 불가
    )
    html_content = future.result(timeout=hard_timeout)
```

### 해결책
ThreadPoolExecutor 제거, Playwright 내장 타임아웃만 사용:

```python
# 직접 호출 - 같은 스레드에서 실행
html_content = self.get_html_content_for_crawling_with_browser(
    url, use_selenium, context, selector
)
```

### 교훈
- Playwright sync API는 생성된 스레드에서만 사용 가능
- ThreadPoolExecutor 등으로 다른 스레드에 Playwright 객체 전달 금지
- 타임아웃은 Playwright 자체 타임아웃(`page.goto(timeout=)`, `context.set_default_timeout()`)에 의존

---

## 변경된 파일

| 파일 | 변경 내용 |
|------|----------|
| `src/job_monitoring_logic.py` | signal.alarm() 제거, ThreadPoolExecutor 제거 |

## 커밋
- `4422080` - fix: signal.alarm() 제거로 Airflow 워커 스레드 호환성 해결
- `07c73f1` - fix: ThreadPoolExecutor 제거 - Playwright greenlet 스레드 충돌 해결
