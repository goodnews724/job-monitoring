import pandas as pd
import re

def update_selectors():
    """선택자 안정화 및 업데이트 (해시 보존 버전)"""
    csv_path = "../data/채용공고_목록.csv"
    
    def stabilize(selector):
        if pd.isna(selector):
            return selector
        
        original = selector
        
        # 1. 동적 ID만 제거 (# 뒤에 긴 UUID 형태만)
        selector = re.sub(r'#[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\s*>\s*', '', selector)
        
        # 2. nth-child 제거 (모든 항목 선택을 위해)
        selector = re.sub(r':nth-child\(\d+\)', '', selector)
        
        # 3. 공백 정리
        selector = re.sub(r'\s+', ' ', selector).strip()
        selector = re.sub(r'\s*>\s*', ' > ', selector)
        
        return selector
    
    # CSV 처리
    df = pd.read_csv(csv_path)
    
    print("🔧 선택자 안정화 처리 중 (해시 보존)...")
    print("=" * 60)
    
    changed_companies = []
    
    for index, row in df.iterrows():
        company_name = row['회사명']
        original_selector = row['selector']
        
        if pd.isna(original_selector):
            continue
            
        stabilized_selector = stabilize(original_selector)
        
        if original_selector != stabilized_selector:
            changed_companies.append(company_name)
            print(f"🔄 {company_name}")
            print(f"   이전: {original_selector}")
            print(f"   이후: {stabilized_selector}")
            print()
            
            df.at[index, 'selector'] = stabilized_selector
    
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    
    print("=" * 60)
    if changed_companies:
        print(f"✅ 선택자 안정화 완료! ({len(changed_companies)}개 회사)")
        print(f"📋 변경된 회사들: {', '.join(changed_companies)}")
    else:
        print("✅ 모든 선택자가 이미 안정적입니다!")

# 실행
update_selectors()