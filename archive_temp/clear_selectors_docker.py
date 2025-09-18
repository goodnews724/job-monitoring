#!/usr/bin/env python3
"""Docker 컨테이너 내에서 실행할 셀렉터 초기화 스크립트"""

import sys
import os
sys.path.append('/opt/airflow/dags')

from job_monitoring_logic import JobMonitoringDAG

def clear_problematic_selectors():
    """문제가 있었던 회사들의 셀렉터를 초기화합니다."""
    
    # 크롤링 실패한 회사들
    failed_companies = [
        '컴투스',
        '마이다스아이티',
        '삼성SDS',
        '아이엠뱅크'
    ]
    
    print(f"🗑️  {len(failed_companies)}개 회사의 셀렉터를 초기화합니다.")
    
    # JobMonitoringDAG 인스턴스 생성
    dag = JobMonitoringDAG('/opt/airflow')
    
    # Google Sheet에서 데이터 가져오기 (기본 시트)
    df = dag.sheet_manager.get_all_records_as_df()
    
    if df.empty:
        print("❌ Google Sheet에서 데이터를 가져올 수 없습니다.")
        return
    
    print(f"📊 현재 {len(df)}개 회사 데이터를 가져왔습니다.")
    
    # 실패한 회사들의 셀렉터 초기화
    updated = False
    for company in failed_companies:
        mask = df['company_name'] == company
        if mask.any():
            df.loc[mask, 'selector'] = ''
            print(f"🗑️  {company} 회사의 셀렉터를 초기화했습니다.")
            updated = True
        else:
            print(f"⚠️  {company} 회사를 찾을 수 없습니다.")
    
    if updated:
        # Google Sheet에 업데이트
        print("📝 Google Sheet 업데이트 중...")
        dag.sheet_manager.update_sheet_from_df(df)
        print("✅ 셀렉터 초기화가 완료되었습니다.")
        print("이제 DAG를 실행하면 해당 회사들의 셀렉터가 새로 분석됩니다.")
    else:
        print("⚠️  초기화할 셀렉터가 없습니다.")

if __name__ == "__main__":
    clear_problematic_selectors()