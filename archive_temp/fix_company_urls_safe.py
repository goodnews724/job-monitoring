#!/usr/bin/env python3
"""안전한 방식으로 회사 URL을 수정하는 스크립트"""

import sys
import os
import pandas as pd
import numpy as np
sys.path.append('/opt/airflow/dags')

from job_monitoring_logic import JobMonitoringDAG

def clean_dataframe(df):
    """DataFrame의 NaN, inf 값들을 정리합니다."""
    # NaN을 빈 문자열로 변경
    df = df.fillna('')
    
    # inf, -inf를 0으로 변경
    df = df.replace([np.inf, -np.inf], 0)
    
    # 숫자 컬럼에서 매우 큰 값들을 제한
    for col in df.select_dtypes(include=[np.number]).columns:
        df[col] = df[col].clip(-1e10, 1e10)
    
    return df

def fix_company_urls_safe():
    """안전한 방식으로 문제가 있는 회사들의 URL을 수정합니다."""
    
    print("🔧 문제 회사들 URL 수정 시작 (안전 모드)")
    
    # JobMonitoringDAG 인스턴스 생성
    dag = JobMonitoringDAG('/opt/airflow')
    
    # Google Sheet에서 데이터 가져오기
    df = dag.sheet_manager.get_all_records_as_df()
    
    if df.empty:
        print("❌ Google Sheet에서 데이터를 가져올 수 없습니다.")
        return
    
    print(f"📊 현재 {len(df)}개 회사 데이터를 가져왔습니다.")
    print(f"컬럼: {list(df.columns)}")
    
    # 데이터 정리
    df = clean_dataframe(df)
    
    # 수정할 회사들의 정보
    updates = [
        {
            "company": "삼성SDS",
            "new_url": "https://www.samsungsds.com/us/careers/about_careers.html"
        }
        # 마이다스아이티는 일단 제외 (URL을 빈 문자열로 하면 문제될 수 있음)
    ]
    
    updated = False
    for update in updates:
        company = update["company"]
        new_url = update["new_url"]
        
        mask = df['company_name'] == company
        if mask.any():
            # URL 업데이트
            df.loc[mask, 'url'] = new_url
            # 셀렉터 초기화 (새로 분석하도록)
            df.loc[mask, 'selector'] = ''
            print(f"🔧 {company}: URL을 {new_url}로 변경")
            updated = True
        else:
            print(f"⚠️  {company} 회사를 찾을 수 없습니다.")
    
    if updated:
        try:
            # Google Sheet에 업데이트
            print("📝 Google Sheet 업데이트 중...")
            dag.sheet_manager.update_sheet_from_df(df)
            print("✅ URL 수정이 완료되었습니다.")
        except Exception as e:
            print(f"❌ Google Sheet 업데이트 실패: {e}")
            # 데이터 타입 정보 출력
            print("DataFrame 정보:")
            print(df.dtypes)
            print("\n문제가 될 수 있는 값들:")
            for col in df.columns:
                unique_vals = df[col].unique()
                if len(unique_vals) <= 10:
                    print(f"{col}: {unique_vals}")
                else:
                    print(f"{col}: {len(unique_vals)}개 고유값")
    else:
        print("⚠️  수정할 회사가 없습니다.")

if __name__ == "__main__":
    fix_company_urls_safe()