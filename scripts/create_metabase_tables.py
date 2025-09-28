#!/usr/bin/env python3
"""
CSV 데이터를 PostgreSQL로 가져와서 메타베이스용 테이블 생성
"""

import pandas as pd
from sqlalchemy import create_engine, text
import os
from datetime import datetime, timedelta

def create_database_connection():
    """PostgreSQL 연결"""
    engine = create_engine('postgresql://airflow:airflow@localhost:5432/airflow')
    return engine

def load_csv_to_postgres():
    """CSV 파일들을 PostgreSQL 테이블로 로드"""
    engine = create_database_connection()

    # 5000대 기업 데이터
    try:
        df_5000 = pd.read_csv('/Users/goodnews/Documents/projects/test/job-monitoring/data/top_5000_postings_latest.csv')
        df_5000['crawl_datetime'] = pd.to_datetime(df_5000['crawl_datetime'])
        df_5000['dag_type'] = '5000대_기업'
        df_5000.to_sql('job_postings_5000', engine, if_exists='replace', index=False)
        print(f"✅ 5000대 기업 데이터 로드 완료: {len(df_5000)}개 레코드")
    except Exception as e:
        print(f"❌ 5000대 기업 데이터 로드 실패: {e}")

    # 등록 채용홈페이지 데이터
    try:
        df_general = pd.read_csv('/Users/goodnews/Documents/projects/test/job-monitoring/data/job_postings_latest.csv')
        df_general['crawl_datetime'] = pd.to_datetime(df_general['crawl_datetime'])
        df_general['dag_type'] = '등록_채용홈페이지'
        df_general.to_sql('job_postings_general', engine, if_exists='replace', index=False)
        print(f"✅ 등록 채용홈페이지 데이터 로드 완료: {len(df_general)}개 레코드")
    except Exception as e:
        print(f"❌ 등록 채용홈페이지 데이터 로드 실패: {e}")

    # 통합 뷰 생성
    create_unified_view(engine)

def create_unified_view(engine):
    """분석용 통합 뷰 생성"""

    # 외국인 키워드 체크 함수
    foreign_keywords_sql = """
    CREATE OR REPLACE FUNCTION is_foreign_job(job_title TEXT)
    RETURNS BOOLEAN AS $$
    BEGIN
        RETURN (
            job_title ILIKE '%외국인%' OR
            job_title ILIKE '%글로벌%' OR
            job_title ILIKE '%해외%' OR
            job_title ILIKE '%영어%' OR
            job_title ILIKE '%중국어%' OR
            job_title ILIKE '%일본어%' OR
            job_title ILIKE '%international%' OR
            job_title ILIKE '%global%' OR
            job_title ILIKE '%english%'
        );
    END;
    $$ LANGUAGE plpgsql;
    """

    # 통합 데이터 뷰
    unified_view_sql = """
    CREATE OR REPLACE VIEW job_postings_unified AS
    SELECT
        회사_한글_이름 as company_name,
        job_posting_title,
        crawl_datetime,
        dag_type,
        is_foreign_job(job_posting_title) as is_foreign_job,
        DATE(crawl_datetime) as crawl_date,
        EXTRACT(DOW FROM crawl_datetime) as day_of_week,
        EXTRACT(HOUR FROM crawl_datetime) as hour_of_day
    FROM (
        SELECT * FROM job_postings_5000
        UNION ALL
        SELECT * FROM job_postings_general
    ) combined;
    """

    # 주간 요약 뷰
    weekly_summary_sql = """
    CREATE OR REPLACE VIEW weekly_company_summary AS
    SELECT
        company_name,
        dag_type,
        COUNT(*) as total_jobs,
        COUNT(CASE WHEN is_foreign_job THEN 1 END) as foreign_jobs,
        ROUND(
            COUNT(CASE WHEN is_foreign_job THEN 1 END) * 100.0 / COUNT(*), 2
        ) as foreign_job_ratio,
        MIN(crawl_datetime) as first_posting,
        MAX(crawl_datetime) as last_posting,
        COUNT(DISTINCT crawl_date) as active_days
    FROM job_postings_unified
    WHERE crawl_datetime >= CURRENT_DATE - INTERVAL '7 days'
    GROUP BY company_name, dag_type
    ORDER BY total_jobs DESC;
    """

    try:
        with engine.connect() as conn:
            conn.execute(text(foreign_keywords_sql))
            conn.execute(text(unified_view_sql))
            conn.execute(text(weekly_summary_sql))
            conn.commit()
        print("✅ 분석용 뷰 생성 완료")
    except Exception as e:
        print(f"❌ 뷰 생성 실패: {e}")

if __name__ == "__main__":
    print("🚀 메타베이스용 데이터 로딩 시작...")
    load_csv_to_postgres()
    print("✅ 데이터 로딩 완료!")