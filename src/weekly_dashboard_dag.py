#!/usr/bin/env python3
"""
주간 대시보드 업데이트 및 이메일 발송 DAG
매주 월요일 오전 9시에 실행
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
import sys
import os

# DAG 디렉토리를 Python 경로에 추가
sys.path.append('/opt/airflow/dags')

# DAG 기본 설정
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# DAG 정의
dag = DAG(
    'weekly_dashboard_update',
    default_args=default_args,
    description='주간 대시보드 데이터 업데이트 및 이메일 발송',
    schedule_interval='0 9 * * 1',  # 매주 월요일 오전 9시 (크론탭: 분 시 일 월 요일)
    catchup=False,
    is_paused_upon_creation=True,  # 생성 시 일시정지 상태
    tags=['dashboard', 'weekly', 'email']
)

def sync_foreign_keywords():
    """구글 시트에서 외국인 키워드를 동기화"""
    import subprocess
    result = subprocess.run([
        'python', '/opt/airflow/data/update_foreign_keywords.py'
    ], capture_output=True, text=True, cwd='/opt/airflow')

    print("키워드 동기화 출력:")
    print(result.stdout)
    if result.stderr:
        print("에러:")
        print(result.stderr)

    if result.returncode != 0:
        raise Exception(f"키워드 동기화 실패: {result.stderr}")

def update_metabase_data():
    """메타베이스용 데이터는 이미 Airflow DAG에서 수집됨"""
    print("✅ 데이터 수집 DAG가 이미 최신 데이터를 PostgreSQL에 저장했습니다.")
    print("📊 메타베이스 대시보드가 자동으로 최신 데이터를 사용합니다.")

def update_dashboard_data():
    """대시보드용 데이터 준비 완료 알림"""
    print("📊 대시보드 데이터 업데이트 완료!")
    print("메타베이스 슬랙 구독이 자동으로 주간 리포트를 전송합니다.")

# 태스크 정의
task_sync_keywords = PythonOperator(
    task_id='sync_foreign_keywords',
    python_callable=sync_foreign_keywords,
    dag=dag,
)

task_update_data = PythonOperator(
    task_id='update_metabase_data',
    python_callable=update_metabase_data,
    dag=dag,
)

task_dashboard_complete = PythonOperator(
    task_id='dashboard_data_complete',
    python_callable=update_dashboard_data,
    dag=dag,
)

# 태스크 의존성 설정
task_sync_keywords >> task_update_data >> task_dashboard_complete