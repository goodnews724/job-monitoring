#!/usr/bin/env python3
import sys
import os
sys.path.append('/opt/airflow')

import logging
from src.job_monitoring_logic import JobMonitoringLogic

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_selenium_required_fix():
    """selenium_required 값 저장 문제 수정사항 테스트"""
    print("=== selenium_required 값 저장 문제 수정 테스트 ===\n")

    try:
        logic = JobMonitoringLogic(worksheet_name='5000대_기업')

        # 처리 전 상태 확인
        print("📊 처리 전 데이터 확인:")
        original_df = logic.sheet_manager.get_dataframe_from_sheet(logic.worksheet_name)
        selenium_values = original_df['selenium_required'].value_counts()
        print(f"  - selenium_required 값 분포: {dict(selenium_values)}")

        # 빈 값들 확인
        empty_mask = (original_df['selenium_required'].isna()) | (original_df['selenium_required'] == '')
        empty_count = empty_mask.sum()
        print(f"  - 빈 값/NaN 개수: {empty_count}")

        if empty_count > 0:
            sample_companies = original_df[empty_mask]['회사_한글_이름'].head(3).tolist()
            print(f"  - 빈 값을 가진 회사 예시: {sample_companies}")

        print("\n🔄 처리 시작...")
        logic.run()

        print("\n📊 처리 후 데이터 확인:")
        updated_df = logic.sheet_manager.get_dataframe_from_sheet(logic.worksheet_name)
        selenium_values_after = updated_df['selenium_required'].value_counts()
        print(f"  - selenium_required 값 분포: {dict(selenium_values_after)}")

        # 변경된 값들 확인
        empty_mask_after = (updated_df['selenium_required'].isna()) | (updated_df['selenium_required'] == '')
        empty_count_after = empty_mask_after.sum()
        print(f"  - 빈 값/NaN 개수: {empty_count_after}")

        changes = empty_count - empty_count_after
        if changes > 0:
            print(f"  ✅ {changes}개 회사의 selenium_required 값이 성공적으로 설정됨")
        else:
            print(f"  ❌ selenium_required 값 변경이 감지되지 않음")

        print("\n✅ 테스트 완료")

    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_selenium_required_fix()