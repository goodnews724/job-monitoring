# 메모리 최적화 및 안정성 개선 (2025-12-29)

## 문제 상황
- 5000대 기업 DAG 실행 시 EC2(t4g.medium, 4GB RAM)에서 메모리 부족으로 SSH 접속 불가
- `Job was killed before it finished (likely due to running out of memory)` 에러 발생
- 19시간 동안 태스크가 stuck 상태로 유지

## 적용된 해결책

### 1. gc.collect() 추가
**파일:** `src/job_monitoring_logic.py`

청크 처리 후 Python 가비지 컬렉션을 강제 실행하여 메모리 누수 방지.

```python
import gc

# 청크 처리 후 (line 169 근처)
gc.collect()
self.logger.info("🧹 메모리 정리 완료 (gc.collect)")
```

### 2. 스왑 메모리 추가 (EC2)
RAM 부족 시 디스크를 메모리처럼 사용하여 OOM 방지.

```bash
# EC2에서 실행 (영구 적용됨)
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**확인 방법:**
```bash
free -h  # Swap: 4.0Gi 확인
```

### 3. PYTHONUNBUFFERED=1 설정
**파일:** `docker-compose.yml`

Python stdout 버퍼링 비활성화로 실시간 로그 출력.

```yaml
environment:
  - PYTHONUNBUFFERED=1
```

### 4. depends_on_past 제거
**파일:** `src/job_monitoring_airflow_dag.py`

이전 실행 실패 시 다음 태스크가 시작되지 않는 문제 해결.

**변경 전:**
```python
top5000_args.update({
    'depends_on_past': True,  # 이전 실행 성공해야 다음 실행 가능
})
```

**변경 후:**
```python
top5000_args = default_args.copy()  # depends_on_past=False 상속
```

**동시 실행 방지는 아래 설정으로 유지됨:**
- `max_active_runs=1` - DAG 동시 실행 1개 제한
- `task_concurrency=1` - 태스크 동시 실행 1개 제한

### 5. Airflow 로그 서버 설정
**파일:** `docker-compose.yml`

스케줄러 hostname 고정으로 웹서버에서 로그 접근 가능하도록 설정.

```yaml
airflow-scheduler:
  hostname: airflow-scheduler
  ports:
    - "8793:8793"
```

## 기존 메모리 최적화 설정 (유지)

### 청크 단위 처리
- 100개 기업씩 분할 처리
- 청크 간 30초 대기

### 메모리 모니터링
```python
# 10개 URL 처리마다 메모리 체크
if processed_count % 10 == 0:
    memory_percent = psutil.virtual_memory().percent
    if memory_percent > 85:
        time.sleep(5)  # 메모리 부족 시 대기
```

### Playwright 브라우저 정리
- 각 크롤링 후 `browser.close()`, `context.close()` 호출
- `--memory-pressure-off` 옵션 사용

## 권장 사항

### 추가 메모리가 필요한 경우
인스턴스 업그레이드 고려:
- t4g.large (8GB) - 월 ~$30 추가
- t4g.xlarge (16GB) - 월 ~$60 추가

### 모니터링
```bash
# 메모리 사용량 확인
free -h

# 스왑 사용량 확인
swapon --show

# 프로세스별 메모리 확인
ps aux --sort=-%mem | head -10
```
