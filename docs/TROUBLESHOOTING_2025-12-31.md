# 트러블슈팅 기록 (2025-12-31)

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
