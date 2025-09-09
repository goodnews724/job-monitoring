import subprocess
import sys
import os
from datetime import datetime

def setup_companies_simple():
    """
    새로운 회사 추가를 위한 간단한 설정 실행
    """
    scripts = [
        ("update_selenium_flags.py", "Selenium 설정 확인"),
        ("save_html.py", "HTML 수집"), 
        ("analyze_titles.py", "셀렉터 분석")
    ]
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    print("🏢 새로운 회사 추가 설정 시작")
    print(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    for i, (script, desc) in enumerate(scripts, 1):
        print(f"\n[{i}/{len(scripts)}] {desc} - {script}")
        
        try:
            subprocess.run([sys.executable, script], cwd=base_dir, check=True)
            print(f"✅ 완료")
        except Exception as e:
            print(f"❌ 실패: {e}")
    
    print(f"\n🏁 설정 완료 - {datetime.now().strftime('%H:%M:%S')}")
    print("💡 이제 data/채용공고_목록.csv에서 셀렉터를 확인하고 설정하세요!")

if __name__ == "__main__":
    setup_companies_simple()