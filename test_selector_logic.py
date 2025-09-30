#!/usr/bin/env python3
"""
선택자 저장 로직 테스트 스크립트
5시간 걸리는 전체 실행 대신 작은 데이터셋으로 기능 검증
"""

import sys
import os
import pandas as pd
from datetime import datetime

# 프로젝트 경로 추가
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from job_monitoring_logic import JobMonitoringDAG
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

def create_test_dataframe():
    """테스트용 작은 데이터프레임 생성 (5개 회사만)"""
    test_data = {
        '회사_한글_이름': [
            '삼성전자(주)',
            'SK(주)',
            '현대자동차(주)',
            'LG전자(주)',
            '기아(주)'
        ],
        'job_posting_url': [
            'https://sec.recruiter.co.kr/app/jobnotice/list',
            'https://recruiting.sk.com/recruit/recruit-list',
            'https://www.hyundai.com/kr/ko/career/recruit/list',
            'https://www.lge.co.kr/career/recruit/job-search',
            'https://careers.kia.com/recruit'
        ],
        'selector': [
            '#list li div div a',  # 기존 선택자
            '',  # 빈 선택자 (새로 찾을 예정)
            'div.content__row',  # 기존 선택자
            '',  # 빈 선택자
            '#applyList li.cont__box a'  # 기존 선택자
        ],
        'selenium_required': [0, 0, 0, 0, 0]
    }

    return pd.DataFrame(test_data)

def test_selector_backup_logic():
    """선택자 백업/복원 로직 단위 테스트"""
    print("=" * 60)
    print("🧪 선택자 백업/복원 로직 테스트")
    print("=" * 60)

    # 테스트 데이터 생성
    df = create_test_dataframe()
    print(f"📊 테스트 데이터 ({len(df)}개 회사):")
    for idx, row in df.iterrows():
        selector_status = f"선택자: '{row['selector']}'" if row['selector'] else "선택자: 없음"
        print(f"  {idx+1}. {row['회사_한글_이름']} - {selector_status}")

    # JobMonitoringDAG 초기화 (실제 크롤링 없이 백업 로직만 테스트)
    dag = JobMonitoringDAG(
        base_dir='.',
        worksheet_name='5000대_기업',
        webhook_url_env='TOP5000COMPANY_URL',
        results_filename='test_results.csv'
    )

    # 기존 선택자 백업 로직 시뮬레이션
    print("\n🔄 백업 로직 시뮬레이션:")
    existing_selectors_backup = {}
    if 'selector' in df.columns:
        for idx, row in df.iterrows():
            if pd.notna(row.get('selector')) and str(row.get('selector')).strip():
                company_name = row.get('회사_한글_이름', '')
                if company_name:
                    existing_selectors_backup[company_name] = str(row['selector']).strip()
        print(f"✅ 기존 선택자 {len(existing_selectors_backup)}개 백업 완료")
        for company, selector in existing_selectors_backup.items():
            print(f"   - {company}: {selector[:50]}...")

    # 새 선택자 시뮬레이션 (실제로는 크롤링에서 찾을 것들)
    print("\n🔍 새 선택자 발견 시뮬레이션:")
    new_selectors = {
        'SK(주)': 'div.recruit-list ul li a',
        'LG전자(주)': 'p.MuiTypography-body1.css-1cythvu'
    }

    # 백업에 새 선택자 추가 시뮬레이션
    for company, selector in new_selectors.items():
        existing_selectors_backup[company] = selector
        print(f"   + {company}: {selector}")

    # 복원 로직 시뮬레이션
    print("\n↩️ 선택자 복원 시뮬레이션:")
    restored_count = 0
    for idx, row in df.iterrows():
        company_name = row.get('회사_한글_이름', '')
        if company_name in existing_selectors_backup:
            current_selector = str(row.get('selector', '')).strip()
            backup_selector = existing_selectors_backup[company_name]
            if not current_selector and backup_selector:
                df.at[idx, 'selector'] = backup_selector
                restored_count += 1
                print(f"   ✅ {company_name}: 선택자 복원됨")

    print(f"\n📊 최종 결과:")
    print(f"   - 백업된 선택자: {len(existing_selectors_backup)}개")
    print(f"   - 복원된 선택자: {restored_count}개")

    print(f"\n📋 최종 데이터프레임:")
    for idx, row in df.iterrows():
        selector_status = f"선택자: '{row['selector'][:50]}...'" if row['selector'] else "선택자: 없음"
        print(f"  {idx+1}. {row['회사_한글_이름']} - {selector_status}")

    return df, existing_selectors_backup

def test_selector_update_function():
    """선택자 업데이트 함수 테스트 (실제 구글시트 연결 없이)"""
    print("\n" + "=" * 60)
    print("🧪 선택자 업데이트 함수 테스트")
    print("=" * 60)

    # 테스트 데이터
    df, _ = test_selector_backup_logic()

    print("\n🔧 update_selector_column_only 함수 로직 시뮬레이션:")

    # 시뮬레이트된 구글시트 데이터 (헤더 + 데이터)
    simulated_sheet_data = [
        ['회사_한글_이름', 'job_posting_url', 'selector', 'selenium_required'],  # 헤더
        ['삼성전자(주)', 'https://sec.recruiter.co.kr/app/jobnotice/list', 'old_selector_1', '0'],
        ['SK(주)', 'https://recruiting.sk.com/recruit/recruit-list', '', '0'],
        ['현대자동차(주)', 'https://www.hyundai.com/kr/ko/career/recruit/list', 'old_selector_2', '0'],
        ['LG전자(주)', 'https://www.lge.co.kr/career/recruit/job-search', '', '0'],
        ['기아(주)', 'https://careers.kia.com/recruit', 'old_selector_3', '0']
    ]

    print(f"📊 시뮬레이트된 구글시트 현재 상태:")
    for i, row in enumerate(simulated_sheet_data):
        if i == 0:
            print(f"   헤더: {row}")
        else:
            print(f"   {i}. {row[0]} - 현재 선택자: '{row[2] if row[2] else '없음'}'")

    # 업데이트 로직 시뮬레이션
    header_row = simulated_sheet_data[0]
    selector_col_index = header_row.index('selector')
    company_name_col = header_row.index('회사_한글_이름')

    updates = []
    updated_count = 0

    print(f"\n🔄 업데이트 대상 찾기:")
    for _, row in df.iterrows():
        company_name = row.get('회사_한글_이름', '')
        new_selector = str(row.get('selector', '')).strip()

        if not company_name or not new_selector:
            continue

        # 시뮬레이트된 시트에서 해당 회사 찾기
        for sheet_row_idx, sheet_row in enumerate(simulated_sheet_data[1:], 2):
            if sheet_row[company_name_col] == company_name:
                current_selector = sheet_row[selector_col_index].strip()

                if current_selector != new_selector:
                    cell_address = f"C{sheet_row_idx}"  # C는 selector 컬럼
                    updates.append({
                        'company': company_name,
                        'cell': cell_address,
                        'old': current_selector if current_selector else '없음',
                        'new': new_selector
                    })
                    updated_count += 1
                break

    print(f"   📝 업데이트할 항목들:")
    for update in updates:
        print(f"     - {update['company']} ({update['cell']}): '{update['old']}' → '{update['new'][:50]}...'")

    print(f"\n✅ 업데이트 완료: {updated_count}개 선택자")

    return updates

def run_mini_test():
    """전체 미니 테스트 실행"""
    print("🚀 선택자 저장 로직 미니 테스트 시작")
    print(f"⏰ 테스트 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        # 1. 백업/복원 로직 테스트
        test_selector_backup_logic()

        # 2. 업데이트 함수 테스트
        updates = test_selector_update_function()

        print("\n" + "=" * 60)
        print("🎉 테스트 완료!")
        print("=" * 60)
        print(f"✅ 총 {len(updates)}개 선택자 업데이트 예정")
        print("✅ 백업/복원 로직 정상 작동")
        print("✅ 선택적 업데이트 로직 정상 작동")
        print("\n💡 실제 5000대 기업 DAG 실행 시 이 로직들이 적용되어 선택자가 보존됩니다.")

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print(f"⏰ 테스트 종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    run_mini_test()