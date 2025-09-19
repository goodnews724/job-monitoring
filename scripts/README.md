# EC2 자동 스케줄링 설정

## 필요한 정보

### 1. 설정 전 준비사항
- [ ] AWS CLI 설치 및 설정 (`aws configure`)
- [ ] EC2 인스턴스 생성 완료
- [ ] 인스턴스 ID 확인 (예: `i-0123456789abcdef0`)
- [ ] Slack 웹훅 URL (선택사항)

### 2. 수정해야 할 값들

**setup-aws-automation.sh 파일에서:**
```bash
INSTANCE_ID="i-xxxxxxxxx"  # ← 실제 인스턴스 ID로 변경
REGION="ap-northeast-2"    # ← 필요시 리전 변경
```

**환경변수 설정:**
```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."  # 선택사항
```

### 3. 실행 방법
```bash
cd scripts
chmod +x setup-aws-automation.sh
./setup-aws-automation.sh
```

### 4. 스케줄
- **09:00**: 시작 → 30분 작업 → 자동 종료
- **15:00**: 시작 → 30분 작업 → 자동 종료

### 5. 확인 방법
```bash
# CloudWatch Events 확인
aws events list-rules

# Lambda 함수 확인
aws lambda list-functions

# 로그 확인
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/job-monitoring-scheduler
```

## 비용 절약
- 기존: 24시간 × 30일 = 720시간/월
- 스케줄: 8시간 × 22일 = 176시간/월
- **약 75% 절약**