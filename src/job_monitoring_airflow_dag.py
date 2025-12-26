from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import timedelta
import pendulum
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__)))

from job_monitoring_logic import JobMonitoringDAG

def run_job_monitoring():
    base_dir = '/opt/airflow'
    dag_runner = JobMonitoringDAG(
        base_dir=base_dir,
        worksheet_name='[등록]채용홈페이지 모음',
        webhook_url_env='SLACK_WEBHOOK_URL',
        results_filename='job_postings_latest.csv'
    )
    dag_runner.run()

def run_top5000_monitoring():
    base_dir = '/opt/airflow'
    dag_runner = JobMonitoringDAG(
        base_dir=base_dir,
        worksheet_name='5000대_기업',
        webhook_url_env='TOP5000COMPANY_URL',
        results_filename='top_5000_postings_latest.csv'
    )
    dag_runner.run()

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'task_concurrency': 1,  # 동시 실행 태스크 1개로 제한
}

# 기본 채용홈페이지 모음 DAG - 매일 오전 10시와 오후 3시 실행 (한국시간)
with DAG(
    'job_monitoring_dag',
    default_args=default_args,
    description='A simple DAG to monitor job postings',
    schedule_interval='0 10,15 * * *',  # 매일 10시, 15시 (KST)
    start_date=pendulum.datetime(2025, 1, 1, tz="Asia/Seoul"),
    catchup=False,
    max_active_runs=1,  # 동시 실행 방지
    is_paused_upon_creation=True,  # 생성 시 일시정지 상태
) as dag:
    run_task = PythonOperator(
        task_id='run_job_monitoring',
        python_callable=run_job_monitoring,
    )

# 5000대 기업 DAG 전용 설정
top5000_args = default_args.copy()
top5000_args.update({
    'depends_on_past': True,  # 이전 실행 성공해야 다음 실행 가능
})

# 5000대 기업 DAG - 매일 19시 실행
with DAG(
    'top5000_company_monitoring_dag',
    default_args=top5000_args,
    schedule_interval='0 19 * * *',  # 매일 19시 (KST)
    start_date=pendulum.datetime(2025, 1, 1, tz="Asia/Seoul"),
    catchup=False,
    max_active_runs=1,  # 동시 실행 방지
    is_paused_upon_creation=True,  # 생성 시 일시정지 상태
) as top5000_dag:
    run_top5000_task = PythonOperator(
        task_id='run_top5000_monitoring',
        python_callable=run_top5000_monitoring,
        execution_timeout=timedelta(hours=14),  # 14시간 초과 시 강제 종료 (다음 일반 DAG 10시 전 09시까지)
    )