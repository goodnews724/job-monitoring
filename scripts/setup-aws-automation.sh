#!/bin/bash

# AWS CloudWatch Events + Lambda 자동화 설정 스크립트

INSTANCE_ID="i-xxxxxxxxx"  # 실제 인스턴스 ID로 변경
REGION="ap-northeast-2"
FUNCTION_NAME="job-monitoring-scheduler"

echo "🚀 Setting up AWS automation for EC2 scheduling..."

# 1. IAM 역할 생성 (Lambda용)
echo "Creating IAM role for Lambda..."
aws iam create-role \
    --role-name lambda-ec2-scheduler-role \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "lambda.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }' \
    --region $REGION

# 2. IAM 정책 연결
echo "Attaching policies to role..."
aws iam attach-role-policy \
    --role-name lambda-ec2-scheduler-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam put-role-policy \
    --role-name lambda-ec2-scheduler-role \
    --policy-name EC2SchedulerPolicy \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "ec2:StartInstances",
                    "ec2:StopInstances",
                    "ec2:DescribeInstances"
                ],
                "Resource": "*"
            }
        ]
    }'

# 3. Lambda 함수 패키징
echo "Creating Lambda deployment package..."
zip lambda-deployment.zip lambda_function.py

# 4. Lambda 함수 생성
echo "Creating Lambda function..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws lambda create-function \
    --function-name $FUNCTION_NAME \
    --runtime python3.9 \
    --role arn:aws:iam::$ACCOUNT_ID:role/lambda-ec2-scheduler-role \
    --handler lambda_function.lambda_handler \
    --zip-file fileb://lambda-deployment.zip \
    --environment Variables="{INSTANCE_ID=$INSTANCE_ID,REGION=$REGION,SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL}" \
    --region $REGION

# 5. CloudWatch Events 규칙 생성 (9시 실행)
echo "Creating CloudWatch Events rule for 9 AM run..."
aws events put-rule \
    --name job-monitoring-9am \
    --schedule-expression "cron(0 0 * * ? *)" \
    --description "Run job monitoring at 9 AM KST" \
    --region $REGION

# 6. CloudWatch Events 규칙 생성 (15시 실행)
echo "Creating CloudWatch Events rule for 3 PM run..."
aws events put-rule \
    --name job-monitoring-3pm \
    --schedule-expression "cron(0 6 * * ? *)" \
    --description "Run job monitoring at 3 PM KST" \
    --region $REGION

# 7. Lambda 함수에 권한 부여
echo "Adding permissions to Lambda function..."
aws lambda add-permission \
    --function-name $FUNCTION_NAME \
    --statement-id 9am-rule \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn arn:aws:events:$REGION:$ACCOUNT_ID:rule/job-monitoring-9am \
    --region $REGION

aws lambda add-permission \
    --function-name $FUNCTION_NAME \
    --statement-id 3pm-rule \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn arn:aws:events:$REGION:$ACCOUNT_ID:rule/job-monitoring-3pm \
    --region $REGION

# 8. 이벤트 규칙에 Lambda 대상 추가
echo "Adding Lambda targets to CloudWatch Events..."
aws events put-targets \
    --rule job-monitoring-9am \
    --targets "Id"="1","Arn"="arn:aws:lambda:$REGION:$ACCOUNT_ID:function:$FUNCTION_NAME","Input"='{"action":"run"}' \
    --region $REGION

aws events put-targets \
    --rule job-monitoring-3pm \
    --targets "Id"="1","Arn"="arn:aws:lambda:$REGION:$ACCOUNT_ID:function:$FUNCTION_NAME","Input"='{"action":"run"}' \
    --region $REGION

# 정리
rm lambda-deployment.zip

echo "✅ AWS automation setup completed!"
echo ""
echo "설정된 스케줄:"
echo "- 매일 UTC 00:00 (한국시간 09:00): 작업 실행"
echo "- 매일 UTC 06:00 (한국시간 15:00): 작업 실행"
echo ""
echo "확인 방법:"
echo "- CloudWatch Events: aws events list-rules"
echo "- Lambda 함수: aws lambda list-functions"
echo "- 로그 확인: aws logs describe-log-groups --log-group-name-prefix /aws/lambda/$FUNCTION_NAME"