#!/bin/bash

# 사용법: ./unpause_dags.sh
# Docker Compose로 실행 중인 Airflow의 두 DAG를 unpause

docker-compose exec airflow-scheduler airflow dags unpause job_monitoring_dag
docker-compose exec airflow-scheduler airflow dags unpause top5000_company_monitoring_dag