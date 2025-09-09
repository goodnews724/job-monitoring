import os
import pandas as pd
import glob
import sys

def remove_company(company_name: str, project_root: str = None):
    """
    특정 회사를 CSV 파일에서 삭제하고 해당 HTML 파일도 삭제
    
    Args:
        company_name: 삭제할 회사명
        project_root: 프로젝트 루트 경로 (None이면 자동 감지)
    """
    if project_root is None:
        # 현재 파일의 프로젝트 루트 찾기
        current_file = os.path.abspath(__file__)
        src_dir = os.path.dirname(current_file)
        project_root = os.path.dirname(src_dir)
    
    # 파일 경로 설정 - 각 파일별로 컬럼명이 다름
    csv_configs = [
        {
            'file': os.path.join(project_root, 'data', '채용공고_목록.csv'),
            'column': '회사명'
        },
        {
            'file': os.path.join(project_root, 'data', 'job_postings_latest.csv'),
            'column': 'company_name'
        }
    ]
    html_dir = os.path.join(project_root, 'html')
    
    print(f"🗑️  회사 '{company_name}' 삭제 작업을 시작합니다...")
    
    # 1. CSV 파일들에서 회사 삭제
    for config in csv_configs:
        csv_file = config['file']
        column_name = config['column']
        
        if os.path.exists(csv_file):
            try:
                df = pd.read_csv(csv_file)
                initial_count = len(df)
                
                # 해당 컬럼이 있는지 확인
                if column_name in df.columns:
                    # 해당 회사명 행들 삭제
                    df_filtered = df[df[column_name] != company_name]
                    removed_count = initial_count - len(df_filtered)
                    
                    if removed_count > 0:
                        # 필터링된 데이터 저장
                        df_filtered.to_csv(csv_file, index=False, encoding='utf-8-sig')
                        print(f"✅ {os.path.basename(csv_file)}: {removed_count}개 행 삭제 완료")
                    else:
                        print(f"ℹ️  {os.path.basename(csv_file)}: '{company_name}' 회사를 찾을 수 없습니다")
                else:
                    print(f"⚠️  {os.path.basename(csv_file)}: '{column_name}' 컬럼이 없습니다")
                    
            except Exception as e:
                print(f"❌ {os.path.basename(csv_file)} 처리 중 오류: {e}")
        else:
            print(f"⚠️  파일이 존재하지 않습니다: {os.path.basename(csv_file)}")
    
    # 2. HTML 파일 삭제
    if os.path.exists(html_dir):
        # 가능한 HTML 파일 패턴들 검색
        html_patterns = [
            os.path.join(html_dir, f"{company_name}.html"),
            os.path.join(html_dir, f"*{company_name}*.html"),
        ]
        
        deleted_html_files = []
        for pattern in html_patterns:
            matching_files = glob.glob(pattern)
            for html_file in matching_files:
                try:
                    os.remove(html_file)
                    deleted_html_files.append(os.path.basename(html_file))
                except Exception as e:
                    print(f"❌ HTML 파일 삭제 중 오류: {html_file} - {e}")
        
        if deleted_html_files:
            print(f"🗑️  HTML 파일 삭제 완료: {', '.join(deleted_html_files)}")
        else:
            print(f"ℹ️  '{company_name}' 관련 HTML 파일을 찾을 수 없습니다")
    else:
        print(f"⚠️  HTML 디렉토리가 존재하지 않습니다: {html_dir}")

def list_companies(project_root: str = None):
    """현재 등록된 회사 목록 출력"""
    if project_root is None:
        current_file = os.path.abspath(__file__)
        src_dir = os.path.dirname(current_file)
        project_root = os.path.dirname(src_dir)
    
    csv_file = os.path.join(project_root, 'data', '채용공고_목록.csv')
    
    if os.path.exists(csv_file):
        try:
            df = pd.read_csv(csv_file)
            if '회사명' in df.columns:
                companies = df['회사명'].unique()
                print("📋 현재 등록된 회사 목록:")
                for i, company in enumerate(companies, 1):
                    print(f"  {i}. {company}")
                return companies
            else:
                print("⚠️  '회사명' 컬럼이 없습니다")
        except Exception as e:
            print(f"❌ CSV 파일 읽기 오류: {e}")
    else:
        print(f"⚠️  파일이 존재하지 않습니다: {csv_file}")
    return []

def interactive_mode():
    """대화형 모드"""
    print("🏢 회사 삭제 도구")
    print("=" * 50)
    
    # 현재 회사 목록 표시
    companies = list_companies()
    
    if not companies:
        print("삭제할 회사가 없습니다.")
        return
    
    print("\n삭제할 회사명을 입력하세요:")
    company_to_delete = input("회사명: ").strip()
    
    if not company_to_delete:
        print("회사명이 입력되지 않았습니다.")
        return
    
    # 확인
    confirm = input(f"\n정말로 '{company_to_delete}' 회사를 삭제하시겠습니까? (y/N): ").strip().lower()
    
    if confirm in ['y', 'yes']:
        remove_company(company_to_delete)
        print(f"\n🎉 '{company_to_delete}' 삭제 작업이 완료되었습니다!")
    else:
        print("취소되었습니다.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # 명령행에서 회사명을 바로 받아서 처리
        company_name = sys.argv[1]
        remove_company(company_name)
        print(f"\n🎉 '{company_name}' 삭제 작업이 완료되었습니다!")
    else:
        # 인수가 없으면 대화형 모드
        interactive_mode()