#!/usr/bin/env python3
"""개선된 SPA 감지 로직 테스트"""

import sys
sys.path.append('src')

import requests
from bs4 import BeautifulSoup
from utils import SeleniumRequirementChecker

def test_spa_detection():
    print("🔍 SPA 감지 로직 테스트")
    
    # 테스트할 사이트들
    test_sites = [
        ("마이다스아이티 (SPA)", "https://midas.recruiter.co.kr/career/home"),
        ("삼성SDS (정적)", "https://www.samsungsds.com/kr/careers/overview/about_care_over.html"),
        ("네이버 (정적)", "https://naver.com")
    ]
    
    checker = SeleniumRequirementChecker()
    
    for name, url in test_sites:
        print(f"\n{'='*50}")
        print(f"🌐 {name}")
        print(f"URL: {url}")
        print(f"{'='*50}")
        
        try:
            # HTML 가져오기
            response = requests.get(url, headers=checker.headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            print(f"HTML 크기: {len(response.content)} bytes")
            
            # SPA 감지 테스트
            is_spa = checker._is_spa_site(soup)
            print(f"SPA 감지: {is_spa}")
            
            # Selenium 필요 여부
            selenium_needed = checker.check_selenium_requirement(url)
            print(f"Selenium 필요: {selenium_needed}")
            
            # 세부 정보
            body = soup.find('body')
            if body:
                body_text = body.get_text(strip=True)
                print(f"Body 텍스트 길이: {len(body_text)} chars")
                print(f"Body 텍스트 샘플: {body_text[:100]}...")
                
            scripts = soup.find_all('script')
            print(f"Script 태그 개수: {len(scripts)}개")
            
            # SPA 지표 체크
            spa_indicators = ['react', '__next', '_next/static', 'buildId', 'webpack', 'chunk']
            html_content = str(soup).lower()
            found_indicators = [ind for ind in spa_indicators if ind in html_content]
            print(f"발견된 SPA 지표: {found_indicators}")
            
        except Exception as e:
            print(f"❌ 오류: {e}")

if __name__ == "__main__":
    test_spa_detection()