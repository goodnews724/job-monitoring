# 트러블슈팅 기록 (2025-12-29)

## 개요
5000대 기업 DAG 실행 시 발생한 문제들과 해결 과정을 정리한 문서입니다.

---

## 1. 메모리 부족 (OOM) 문제

### 증상
- EC2 t4g.medium (4GB RAM)에서 5000대 기업 DAG 실행 시 SSH 접속 불가
- `Job was killed before it finished (likely due to running out of memory)` 에러
- 19시간 동안 태스크가 stuck 상태

### 원인
- 2700개 이상의 기업을 처리하면서 메모리 누적
- Playwright 브라우저 인스턴스의 메모리 사용량
- Python 가비지 컬렉션이 제때 실행되지 않음

### 해결책

#### 1-1. gc.collect() 추가
**파일:** `src/job_monitoring_logic.py`

```python
import gc

# 청크 처리 후
gc.collect()
self.logger.info("🧹 메모리 정리 완료 (gc.collect)")
```

#### 1-2. EC2 스왑 메모리 추가 (4GB)
```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**확인:**
```bash
free -h  # Swap: 4.0Gi 확인
```

---

## 2. DAG 태스크가 시작되지 않는 문제

### 증상
- 5000대 기업 DAG가 queued 상태에서 진행 안 됨
- 이전 실행 실패 후 다음 실행이 시작되지 않음

### 원인
- `depends_on_past=True` 설정으로 인해 이전 실행이 성공해야 다음 실행 가능

### 해결책
**파일:** `src/job_monitoring_airflow_dag.py`

```python
# 변경 전
top5000_args.update({
    'depends_on_past': True,
})

# 변경 후
top5000_args = default_args.copy()  # depends_on_past=False 상속
```

**동시 실행 방지는 아래 설정으로 유지:**
- `max_active_runs=1`
- `task_concurrency=1`

---

## 3. 슬랙 알림에 회사명이 안 보이는 문제

### 증상
- 5000대 기업 DAG 슬랙 알림: "(1-100번째 기업) (15:06)" 만 표시
- 회사명과 채용공고 내용이 보이지 않음

### 원인
- Slack Block Kit 형식 사용 시 content 블록이 제대로 렌더링 안 됨

### 해결책
**파일:** `src/job_monitoring_logic.py`

Block Kit 형식 → 단순 텍스트 형식으로 변경:

```python
# 변경 전 (Block Kit)
blocks = [
    {"type": "section", "text": {"type": "mrkdwn", "text": header}},
    {"type": "divider"},
    {"type": "section", "text": {"type": "mrkdwn", "text": full_content}}
]
payload = {"blocks": blocks, ...}

# 변경 후 (단순 텍스트)
full_message = f"{header}\n\n{full_content}"
payload = {"text": full_message, "username": "채용공고 알리미", "icon_emoji": ":robot_face:"}
```

---

## 변경된 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `src/job_monitoring_logic.py` | gc.collect() 추가, 슬랙 텍스트 형식 변경 |
| `src/job_monitoring_airflow_dag.py` | depends_on_past 제거 |
| `docker-compose.yml` | PYTHONUNBUFFERED 설정 |

---

## 권장 모니터링

```bash
# 메모리 확인
free -h
swapon --show

# 프로세스별 메모리
ps aux --sort=-%mem | head -10
```

---

## 현재 최적화 설정

- 100개 기업씩 청크 분할 처리
- 청크 간 30초 대기
- 10개 URL 처리마다 메모리 체크 (85% 초과 시 5초 대기)
- Playwright `--memory-pressure-off` 옵션
