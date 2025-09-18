#!/usr/bin/env python3
"""토스 채용공고 수집 문제 디버그"""

import sys
sys.path.append('src')

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time

def debug_toss_crawling():
    print("🔍 토스 채용공고 수집 디버그")
    
    url = "https://toss.im/career/jobs"
    selector = "a.css-g65o95 div.css-16fusbk"
    
    print(f"URL: {url}")
    print(f"셀렉터: {selector}")
    
    # Chrome 옵션 설정
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        
        print(f"\n=== Selenium으로 페이지 로딩 ===")
        driver.get(url)
        time.sleep(3)  # 페이지 로딩 대기
        
        # 현재 URL 확인
        current_url = driver.current_url
        print(f"현재 URL: {current_url}")
        
        # HTML 가져오기
        html_content = driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')
        
        print(f"HTML 크기: {len(html_content)} bytes")
        
        # 지정된 셀렉터로 채용공고 찾기
        job_postings = soup.select(selector)
        print(f"\n=== 지정된 셀렉터 결과 ===")
        print(f"'{selector}': {len(job_postings)}개 발견")
        
        for i, posting in enumerate(job_postings[:10], 1):
            text = posting.get_text(strip=True)
            print(f"  {i:2d}. {text}")
        
        # 다른 가능한 셀렉터들 시도
        print(f"\n=== 다른 셀렉터들 시도 ===")
        alternative_selectors = [
            "a.css-g65o95",
            "div.css-16fusbk", 
            "[class*='css-g65o95']",
            "[class*='css-16fusbk']",
            "a[href*='/career/jobs/']",
            ".job-item", ".position", ".career-item",
            "h3", "h4", ".title"
        ]
        
        for alt_selector in alternative_selectors:
            try:
                elements = soup.select(alt_selector)
                if elements:
                    print(f"{alt_selector:30s}: {len(elements):3d}개")
                    # 채용공고 같은 텍스트들 확인
                    job_like = []
                    for elem in elements[:5]:
                        text = elem.get_text(strip=True)
                        if len(text) > 5 and len(text) < 100:
                            job_like.append(text)
                    
                    if job_like:
                        for i, text in enumerate(job_like, 1):
                            print(f"    {i}. {text}")
            except Exception as e:
                print(f"{alt_selector:30s}: 오류 - {e}")
        
        # 전체 텍스트에서 채용공고 수 추정
        print(f"\n=== 전체 채용공고 수 추정 ===")
        all_text = soup.get_text()
        
        # "개발자", "엔지니어", "디자이너" 등이 포함된 라인 수
        lines = all_text.split('\n')
        job_keywords = ['개발자', '엔지니어', '디자이너', '매니저', 'PM', '마케팅', '영업', 'QA']
        
        job_lines = []
        for line in lines:
            line = line.strip()
            if len(line) > 5 and len(line) < 50:  # 적절한 길이
                if any(keyword in line for keyword in job_keywords):
                    job_lines.append(line)
        
        print(f"채용공고로 보이는 라인들: {len(job_lines)}개")
        for i, line in enumerate(job_lines[:15], 1):
            print(f"  {i:2d}. {line}")
        
        if len(job_lines) > len(job_postings):
            print(f"\n⚠️  실제 채용공고({len(job_lines)}개) > 수집된 공고({len(job_postings)}개)")
            print("셀렉터가 모든 채용공고를 포착하지 못하고 있습니다!")
        
    except Exception as e:
        print(f"❌ 오류: {e}")
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    debug_toss_crawling()