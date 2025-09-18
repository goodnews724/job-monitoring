#!/usr/bin/env python3
"""문제가 있는 회사들의 URL과 셀렉터를 수정하는 스크립트"""

import sys
import os
sys.path.append('/opt/airflow/dags')

from job_monitoring_logic import JobMonitoringDAG

def fix_company_urls():
    """문제가 있는 회사들의 URL을 수정합니다."""
    
    print("🔧 문제 회사들 URL 수정 시작")
    
    # JobMonitoringDAG 인스턴스 생성
    dag = JobMonitoringDAG('/opt/airflow')
    
    # Google Sheet에서 데이터 가져오기
    df = dag.sheet_manager.get_all_records_as_df()
    
    if df.empty:
        print("❌ Google Sheet에서 데이터를 가져올 수 없습니다.")
        return
    
    print(f"📊 현재 {len(df)}개 회사 데이터를 가져왔습니다.")
    
    # 수정할 회사들의 정보
    updates = [
        {
            "company": "삼성SDS",
            "new_url": "https://www.samsungsds.com/us/careers/about_careers.html",
            "reason": "한국 페이지 접근 불가, 영어 채용 페이지로 변경"
        },
        {
            "company": "마이다스아이티", 
            "new_url": "",  # URL을 비워서 크롤링 비활성화
            "reason": "도메인 접근 불가능, 크롤링 비활성화"
        }
    ]
    
    updated = False
    for update in updates:
        company = update["company"]
        new_url = update["new_url"]
        reason = update["reason"]
        
        mask = df['company_name'] == company
        if mask.any():
            # URL 업데이트
            df.loc[mask, 'url'] = new_url
            # 셀렉터 초기화 (새로 분석하도록)
            df.loc[mask, 'selector'] = ''
            print(f"🔧 {company}: {reason}")
            print(f"   새 URL: {new_url if new_url else '(비활성화)'}")
            updated = True
        else:
            print(f"⚠️  {company} 회사를 찾을 수 없습니다.")
    
    if updated:
        # Google Sheet에 업데이트
        print("📝 Google Sheet 업데이트 중...")
        dag.sheet_manager.update_sheet_from_df(df)
        print("✅ URL 수정이 완료되었습니다.")
        print("이제 DAG를 실행하면 수정된 URL로 크롤링을 시도합니다.")
    else:
        print("⚠️  수정할 회사가 없습니다.")

if __name__ == "__main__":
    fix_company_urls()