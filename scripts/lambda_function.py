import json
import boto3
import os
import urllib3

def lambda_handler(event, context):
    """
    CloudWatch Events로 트리거되는 EC2 스케줄러
    """

    # 환경 변수
    instance_id = os.environ['INSTANCE_ID']
    region = os.environ['REGION']
    slack_webhook = os.environ.get('SLACK_WEBHOOK_URL')

    # 액션 타입 확인 (run = 시작→작업실행→종료)
    action = event.get('action', 'run')

    # EC2 클라이언트 생성
    ec2 = boto3.client('ec2', region_name=region)

    try:
        # 1. 인스턴스 시작
        print(f"Starting instance {instance_id}...")
        response = ec2.start_instances(InstanceIds=[instance_id])

        # running 상태까지 대기
        waiter = ec2.get_waiter('instance_running')
        waiter.wait(InstanceIds=[instance_id])

        # 공인 IP 조회
        instances = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = instances['Reservations'][0]['Instances'][0].get('PublicIpAddress', 'No Public IP')

        # 2. 작업 완료까지 대기 (예: 30분)
        import time
        print("Waiting for job completion (30 minutes)...")
        time.sleep(1800)  # 30분 대기

        # 3. 인스턴스 종료
        print(f"Stopping instance {instance_id}...")
        ec2.stop_instances(InstanceIds=[instance_id])

        # stopped 상태까지 대기
        waiter = ec2.get_waiter('instance_stopped')
        waiter.wait(InstanceIds=[instance_id])

        message = f"✅ Job Monitoring 작업 완료\nIP: {public_ip}\n시작→실행→종료 완료"

        # Slack 알림
        if slack_webhook:
            send_slack_notification(slack_webhook, message)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Instance {instance_id} {action} completed',
                'action': action,
                'instance_id': instance_id
            })
        }

    except Exception as e:
        error_message = f"❌ EC2 {action} 실패: {str(e)}"

        if slack_webhook:
            send_slack_notification(slack_webhook, error_message)

        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'action': action,
                'instance_id': instance_id
            })
        }

def send_slack_notification(webhook_url, message):
    """Slack 웹훅으로 알림 전송"""
    try:
        http = urllib3.PoolManager()
        data = json.dumps({'text': message}).encode('utf-8')

        response = http.request(
            'POST',
            webhook_url,
            body=data,
            headers={'Content-Type': 'application/json'}
        )

        return response.status == 200
    except Exception as e:
        print(f"Slack notification failed: {e}")
        return False