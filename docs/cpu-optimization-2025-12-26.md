# CPU 100% 문제 해결 기록

**날짜**: 2025-12-26
**문제**: 5000대 기업 DAG 실행 시 CPU 100% 점유, 43시간 이상 실행
**해결**: Playwright 브라우저 재사용 패턴 적용

---

## 문제 분석

### 증상
- CPU 사용률: 111% (scheduler container)
- 실행 시간: 43시간+ (정상: 5시간)
- DAG 상태: running (진행 안 됨)
- DB lock 발생

### 원인
`src/job_monitoring_logic.py`의 크롤링 메서드가 매번 Playwright 브라우저를 새로 생성하고 종료

```python
# 기존 코드
def get_html_content_for_crawling(self, url, use_selenium):
    if use_selenium:
        playwright, browser = self.create_playwright_browser()  # 매번 생성
        try:
            # 크롤링
            ...
        finally:
            browser.close()  # 매번 종료
            playwright.stop()
```

5000개 기업 처리 시 수천 번의 브라우저 생성/종료 → CPU 과부하

---

## 해결 방법

### 1. 브라우저 재사용 패턴 구현

#### `process_companies_with_cache()` 메서드 수정
```python
def process_companies_with_cache(self, df: pd.DataFrame):
    playwright, browser = None, None
    try:
        # 브라우저 1회 생성
        playwright, browser = self.create_playwright_browser()

        # 모든 URL에 대해 브라우저 재사용
        for url, company_list in url_company_map.items():
            result = self._crawl_single_url_with_browser(url, representative_row, browser)

    finally:
        # 모든 작업 완료 후 1회 종료
        if browser:
            browser.close()
        if playwright:
            playwright.stop()
```

#### 신규 메서드 추가
- `_crawl_single_url_with_browser()`: browser 파라미터를 받는 크롤링 메서드
- `get_html_content_for_crawling_with_browser()`: 브라우저 재사용 버전

### 2. DAG 안전장치 추가

`src/job_monitoring_airflow_dag.py`:
```python
# 5000대 기업 DAG
top5000_args = default_args.copy()
top5000_args.update({
    'depends_on_past': True,  # 이전 실행 성공해야 다음 실행
})

with DAG(
    'top5000_company_monitoring_dag',
    default_args=top5000_args,
    schedule_interval='0 19 * * *',
    max_active_runs=1,  # 동시 실행 방지
    ...
) as top5000_dag:
    run_top5000_task = PythonOperator(
        task_id='run_top5000_monitoring',
        python_callable=run_top5000_monitoring,
        execution_timeout=timedelta(hours=14),  # 14시간 초과 시 종료
    )
```

---

## 테스트

### 테스트 DAG 생성
`src/test_cpu_fix_dag.py`: 50개 기업만 처리하는 테스트 DAG

### 결과
- 실행 시간: 2분 57초
- 브라우저 생성: 1회
- 브라우저 종료: 1회
- 상태: Success

---

## 개선 효과

| 항목 | Before | After |
|-----|--------|-------|
| 실행 시간 (5000개) | 43시간+ | ~5시간 예상 |
| 브라우저 생성 횟수 | 5000+ 회 | 1회 |
| CPU 사용률 | 100% stuck | 정상 |

---

## 배포

### Git
```bash
git checkout -b fix/cpu-100-playwright-optimization
# 3개 커밋 작성
git checkout main
git merge fix/cpu-100-playwright-optimization
git push origin main
```

### EC2
```bash
# 파일 배포
scp src/job_monitoring_logic.py job-monitoring-ec2:~/
scp src/job_monitoring_airflow_dag.py job-monitoring-ec2:~/

# Docker 컨테이너에 복사
docker cp ~/job_monitoring_logic.py kowork-scaper-airflow-scheduler-1:/opt/airflow/dags/
docker cp ~/job_monitoring_airflow_dag.py kowork-scaper-airflow-scheduler-1:/opt/airflow/dags/
# webserver에도 동일하게 복사
```

### Stuck DAG 정리
```sql
UPDATE dag_run SET state='failed', end_date=NOW()
WHERE dag_id='top5000_company_monitoring_dag'
  AND run_id='scheduled__2025-12-24T10:00:00+00:00'
  AND state='running';
```

---

## 최종 상태

- 5000대 기업 DAG: 활성화됨
- 다음 스케줄 실행: 매일 19시
- 예상 실행 시간: 5시간
- Timeout 설정: 14시간
