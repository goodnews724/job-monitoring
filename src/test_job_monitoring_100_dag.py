from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import timedelta
import pendulum
import os
import sys

# Add the src directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__)))

from job_monitoring_logic import JobMonitoringDAG

def run_top100_test_monitoring():
    """
    A test function to run the job monitoring DAG for the top 100 companies.
    """
    base_dir = '/opt/airflow'
    dag_runner = JobMonitoringDAG(
        base_dir=base_dir,
        worksheet_name='5000대_기업',
        webhook_url_env='TOP5000COMPANY_URL',
        results_filename='top_100_test_postings.csv',  # Use a different results file for testing
        limit=100  # Limit the run to the first 100 companies
    )
    dag_runner.run()

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 0,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    'test_100_company_monitoring_dag',
    default_args=default_args,
    description='A test DAG to monitor the top 100 job postings from the 5000 companies list.',
    schedule_interval=None,  # This DAG will only be triggered manually
    start_date=pendulum.datetime(2025, 1, 1, tz="Asia/Seoul"),
    catchup=False,
    is_paused_upon_creation=True,  # Pause the DAG upon creation
    tags=['test'],
) as dag:
    run_test_task = PythonOperator(
        task_id='run_top100_test_monitoring',
        python_callable=run_top100_test_monitoring,
        execution_timeout=timedelta(hours=2),  # Set a reasonable timeout for the test run
    )
