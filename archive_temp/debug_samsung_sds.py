#!/usr/bin/env python3
"""삼성SDS 상세 디버그"""

import requests
from bs4 import BeautifulSoup

def debug_samsung_sds():
    url = "https://www.samsungsds.com/kr/about/recruit.html"
    print(f"삼성SDS URL: {url}")
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        print(f"✅ HTML 가져오기 성공 ({len(response.content)} bytes)")
        
        # 다양한 셀렉터 시도
        selectors_to_try = [
            "div div.checkBox",
            "div.checkBox", 
            ".checkBox",
            "input[type='checkbox']",
            "div[class*='check']",
            "div[class*='job']",
            "div[class*='recruit']",
            "li",
            "ul li",
            "a[href*='job']",
            "a[href*='recruit']"
        ]
        
        for selector in selectors_to_try:
            elements = soup.select(selector)
            print(f"{selector:20s} : {len(elements):3d}개 요소")
            
            if elements and len(elements) <= 10:
                for i, elem in enumerate(elements[:3]):
                    text = elem.get_text(strip=True)[:100]
                    print(f"  {i+1}. {text}")
        
        # HTML 구조 분석
        print(f"\n=== HTML 구조 분석 ===")
        
        # 채용 관련 키워드가 포함된 요소들 찾기
        job_keywords = ['채용', '모집', '지원', 'recruit', 'career', 'job']
        for keyword in job_keywords:
            elements = soup.find_all(text=lambda text: text and keyword in text.lower())
            if elements:
                print(f"'{keyword}' 포함 텍스트: {len(elements)}개")
                for elem in elements[:3]:
                    parent_tag = elem.parent.name if elem.parent else 'None'
                    print(f"  - ({parent_tag}) {elem.strip()[:80]}")
        
    except Exception as e:
        print(f"❌ 오류: {e}")

if __name__ == "__main__":
    debug_samsung_sds()