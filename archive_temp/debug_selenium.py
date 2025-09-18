#!/usr/bin/env python3
"""Selenium으로 삼성SDS 페이지 확인"""

import sys
sys.path.append('src')
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time

def debug_samsung_sds_selenium():
    print("Selenium으로 삼성SDS 페이지 분석...")
    
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
        url = "https://www.samsungsds.com/kr/about/recruit.html"
        
        print(f"페이지 로딩: {url}")
        driver.get(url)
        
        # 페이지 로딩 대기
        time.sleep(5)
        
        # 현재 URL 확인 (리다이렉트 될 수 있음)
        current_url = driver.current_url
        print(f"현재 URL: {current_url}")
        
        # 페이지 소스 가져오기
        html_source = driver.page_source
        soup = BeautifulSoup(html_source, 'html.parser')
        
        print(f"HTML 크기: {len(html_source)} bytes")
        
        # 채용 관련 요소들 찾기
        job_keywords = ['채용', '모집', '지원', 'recruit', 'career', 'job', '입사', '신입', '경력']
        
        print(f"\n=== 채용 관련 텍스트 검색 ===")
        found_texts = []
        for keyword in job_keywords:
            elements = soup.find_all(string=lambda text: text and keyword in text)
            if elements:
                print(f"'{keyword}': {len(elements)}개 발견")
                for elem in elements[:2]:
                    text = elem.strip()
                    if len(text) > 10:
                        parent = elem.parent
                        parent_info = f"({parent.name}" + (f".{'.'.join(parent.get('class', []))}" if parent.get('class') else "") + ")"
                        print(f"  - {parent_info} {text[:100]}")
                        found_texts.append((parent, text))
        
        # 링크들 확인
        print(f"\n=== 채용 관련 링크 ===")
        links = soup.find_all('a', href=True)
        job_links = []
        for link in links:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            if any(keyword in (href + text).lower() for keyword in ['recruit', 'career', 'job', '채용']):
                print(f"링크: {href} - {text}")
                job_links.append((href, text))
        
        # 가능한 셀렉터들 확인
        print(f"\n=== 셀렉터 테스트 ===")
        selectors = [
            "div div.checkBox",
            ".job-item", 
            ".recruit-item",
            "[class*='job']",
            "[class*='recruit']",
            "ul li",
            ".list-item"
        ]
        
        for selector in selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                print(f"{selector:20s}: {len(elements)}개")
                if elements and len(elements) <= 5:
                    for i, elem in enumerate(elements[:3]):
                        text = elem.text.strip()[:100]
                        if text:
                            print(f"  {i+1}. {text}")
            except Exception as e:
                print(f"{selector:20s}: 오류 - {e}")
                
    except Exception as e:
        print(f"❌ 오류: {e}")
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    debug_samsung_sds_selenium()