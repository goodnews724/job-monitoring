#!/usr/bin/env python3
"""토스 필터링 문제 상세 디버그"""

import sys
sys.path.append('src')

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from analyze_titles import JobPostingSelectorAnalyzer
import time

def debug_toss_filtering():
    print("🔍 토스 필터링 문제 상세 디버그")
    
    url = "https://toss.im/career/jobs"
    selector = "a.css-g65o95 div.css-16fusbk"
    
    # Chrome 옵션 설정
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(url)
        time.sleep(3)
        
        html_content = driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 채용공고 요소들 가져오기
        postings = soup.select(selector)
        print(f"전체 포스팅: {len(postings)}개")
        
        # 필터 분석기
        analyzer = JobPostingSelectorAnalyzer()
        
        # 필터링 전후 비교
        all_texts = [post.get_text(strip=True) for post in postings]
        filtered_texts = [text for text in all_texts if analyzer._is_potential_job_posting(text)]
        
        print(f"필터링 후: {len(filtered_texts)}개")
        print(f"제거됨: {len(all_texts) - len(filtered_texts)}개")
        
        # 제거된 항목들 분석
        removed_texts = [text for text in all_texts if not analyzer._is_potential_job_posting(text)]
        
        print(f"\n=== 제거된 항목들 (처음 20개) ===")
        for i, text in enumerate(removed_texts[:20], 1):
            print(f"{i:2d}. {text[:100]}")
            
            # 왜 제거되었는지 분석
            reasons = []
            if len(text) < 3 or len(text) > 150:
                reasons.append(f"길이 문제 ({len(text)}자)")
                
            # 제외 패턴 체크
            for pattern in analyzer.exclude_patterns:
                import re
                if re.search(pattern, text, re.IGNORECASE):
                    reasons.append(f"제외 패턴: {pattern}")
                    break
            
            # 키워드 체크
            has_job_keyword = any(keyword in text for keyword in analyzer.job_keywords)
            job_title_pattern = r'(백엔드|프론트엔드|풀스택|모바일|웹|UI/UX|그래픽|브랜드|마케팅|데이터|AI|ML|DevOps|QA|기획|운영|영업|HR|재무|법무|개발자|디자이너|엔지니어|매니저|기획자|사이언티스트)'
            import re
            has_job_pattern = bool(re.search(job_title_pattern, text))
            
            if not (has_job_keyword or has_job_pattern):
                if len(text) <= 15 and re.match(r'^[가-힣a-zA-Z&\s]+$', text.strip()):
                    reasons.append("짧은 텍스트이지만 허용 패턴")
                else:
                    reasons.append("키워드/패턴 없음")
            
            if reasons:
                print(f"    → 제거 이유: {', '.join(reasons)}")
        
        print(f"\n=== 유지된 항목들 (처음 10개) ===")
        for i, text in enumerate(filtered_texts[:10], 1):
            print(f"{i:2d}. {text[:100]}")
        
    except Exception as e:
        print(f"❌ 오류: {e}")
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    debug_toss_filtering()