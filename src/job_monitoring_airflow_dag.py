from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
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
}

# 기본 채용홈페이지 모음 DAG - 매일 오전 11시와 오후 4시 실행
with DAG(
    'job_monitoring_dag',
    default_args=default_args,
    description='A simple DAG to monitor job postings',
    schedule_interval='0 11,16 * * *',  # 매일 11시, 16시 (UTC)
    start_date=datetime(2025, 1, 1),
    catchup=False,
) as dag:
    run_task = PythonOperator(
        task_id='run_job_monitoring',
        python_callable=run_job_monitoring,
    )

# 5000대 기업 DAG - 매일 오전 11시와 오후 4시 실행
with DAG(
    'top5000_company_monitoring_dag',
    default_args=default_args,
    description='A DAG to monitor top 5000 company job postings',
    schedule_interval='0 11,16 * * *',  # 매일 11시, 16시 (UTC)
    start_date=datetime(2025, 1, 1),
    catchup=False,
) as top5000_dag:
    run_top5000_task = PythonOperator(
        task_id='run_top5000_monitoring',
        python_callable=run_top5000_monitoring,
    )