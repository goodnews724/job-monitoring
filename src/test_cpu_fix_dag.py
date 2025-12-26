from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import timedelta
import pendulum
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__)))

from job_monitoring_logic import JobMonitoringDAG

def run_test_monitoring():
    """
    소규모 테스트용 함수
    - 5000대 기업 중 처음 50개만 처리
    - CPU 사용률 및 브라우저 재사용 로직 검증
    """
    base_dir = '/opt/airflow'
    dag_runner = JobMonitoringDAG(
        base_dir=base_dir,
        worksheet_name='5000대_기업',
        webhook_url_env='TOP5000COMPANY_URL',
        results_filename='test_cpu_fix_results.csv'
    )

    # Google Sheets에서 데이터 로드
    import pandas as pd
    df_config = dag_runner.sheet_manager.get_all_records_as_df('5000대_기업')

    if df_config.empty:
        dag_runner.logger.error("Google Sheets에서 설정 정보를 가져오지 못했습니다.")
        return

    # 처음 50개만 선택 (테스트용)
    df_test = df_config.head(50).copy()
    dag_runner.logger.info(f"[TEST] 전체 {len(df_config)}개 중 50개만 처리합니다.")

    # 선택자 안정화
    df_test = dag_runner.stabilize_selectors(df_test)

    # 통합 처리 (브라우저 재사용 로직 테스트)
    df_result, current_jobs, failed_companies = dag_runner.process_companies_with_cache(df_test)

    # 결과 로깅
    dag_runner.logger.info(f"[TEST] 완료: 성공 {len(current_jobs)}개, 실패 {len(failed_companies)}개")

    # 슬랙 알림
    if dag_runner.webhook_url:
        import requests
        message = f"""[TEST] CPU 최적화 테스트 완료

처리: 50개 기업
성공: {len(current_jobs)}개
실패: {len(failed_companies)}개

브라우저 재사용 로직 검증 완료"""

        payload = {"text": message}
        try:
            requests.post(dag_runner.webhook_url, json=payload)
        except Exception as e:
            dag_runner.logger.warning(f"슬랙 알림 실패: {e}")

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 0,
    'retry_delay': timedelta(minutes=1),
}

# 테스트용 DAG - 수동 실행만 가능
with DAG(
    'test_cpu_fix_dag',
    default_args=default_args,
    description='CPU 최적화 테스트용 DAG (50개 기업)',
    schedule_interval=None,  # 수동 실행만
    start_date=pendulum.datetime(2025, 1, 1, tz="Asia/Seoul"),
    catchup=False,
    is_paused_upon_creation=False,
    tags=['test', 'cpu-optimization'],
) as test_dag:
    test_task = PythonOperator(
        task_id='run_test_monitoring',
        python_callable=run_test_monitoring,
    )
