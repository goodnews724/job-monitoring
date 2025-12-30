# 트러블슈팅 기록 (2025-12-30)

## 개요
5000대 기업 DAG가 15시간 이상 100% CPU 사용하며 stuck 상태 문제 해결

---

## CPU 100% 무한 대기 문제

### 증상
- 태스크가 15시간 이상 100% CPU 사용하며 stuck 상태
- `top` 명령어로 확인 시 904분(15시간+) 동안 CPU 점유
- 로그에 특정 청크(11/27)에서 마지막 출력 후 진행 없음
- 마지막 처리 회사: "현대종합특수강 주식회사"

### 원인 분석
1. **Playwright 타임아웃은 이미 설정되어 있었음** (60초/90초)
2. **하지만 JavaScript 무한 루프는 타임아웃 발동 안됨**
   - 타임아웃은 "응답 대기 중"일 때만 작동
   - 브라우저가 JavaScript 실행 중이면 "작업 중"으로 간주
   - CPU 100% 사용하면서 무한 루프

### 해결책

#### 즉시 해결 (stuck 프로세스 종료)
```bash
docker restart kowork-scaper-airflow-scheduler-1
```

#### 근본 해결 - 스레드 기반 강제 타임아웃
**파일:** `src/job_monitoring_logic.py`

`ThreadPoolExecutor`로 프로세스 레벨 강제 종료:

```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# _crawl_single_url_with_browser 함수 내
hard_timeout = 180 if 'toss.im' in url else 120  # 2~3분

with ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(
        self.get_html_content_for_crawling_with_browser,
        url, use_selenium, context, selector
    )
    html_content = future.result(timeout=hard_timeout)
```

#### 추가 버그 수정
`selector` 파라미터가 전달되지 않던 버그 수정:

```python
# 변경 전
html_content = self.get_html_content_for_crawling_with_browser(url, use_selenium, context)

# 변경 후
html_content = self.get_html_content_for_crawling_with_browser(url, use_selenium, context, selector)
```

---

## 모니터링

```bash
# CPU 사용률이 높은 프로세스 확인
top -o %CPU

# Airflow 태스크 프로세스 확인
ps aux | grep "airflow task"
```

---

## 변경된 파일

| 파일 | 변경 내용 |
|------|----------|
| `src/job_monitoring_logic.py` | ThreadPoolExecutor 강제 타임아웃 추가, selector 파라미터 전달 수정 |
