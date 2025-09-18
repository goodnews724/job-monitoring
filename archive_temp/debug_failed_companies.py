#!/usr/bin/env python3
"""실패한 회사들의 크롤링 결과 디버그"""

import sys
import os
sys.path.append('src')
import requests
from bs4 import BeautifulSoup
from src.analyze_titles import JobPostingSelectorAnalyzer

def debug_company(company_name, url, selector):
    """특정 회사의 크롤링 결과를 디버그합니다."""
    print(f"\n=== {company_name} 디버그 ===")
    print(f"URL: {url}")
    print(f"셀렉터: {selector}")
    
    try:
        # HTML 가져오기
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 셀렉터로 요소 찾기
        elements = soup.select(selector)
        print(f"찾은 요소 개수: {len(elements)}")
        
        if not elements:
            print("❌ 셀렉터로 요소를 찾지 못했습니다.")
            return
        
        # 텍스트 추출
        analyzer = JobPostingSelectorAnalyzer()
        print(f"\n📝 추출된 텍스트들:")
        
        valid_count = 0
        for i, element in enumerate(elements[:10]):  # 처음 10개만 확인
            text = element.get_text(strip=True)
            if text:
                is_valid = analyzer._is_potential_job_posting(text)
                status = "✅" if is_valid else "❌"
                print(f"{i+1:2d}. {status} [{len(text):3d}자] {text[:100]}")
                if is_valid:
                    valid_count += 1
        
        print(f"\n💡 필터링 통과: {valid_count}개 / 전체: {len(elements)}개")
        
    except Exception as e:
        print(f"❌ 오류 발생: {e}")

def main():
    # 실패한 회사들의 정보
    failed_companies = [
        {
            "name": "마이다스아이티",
            "url": "https://career.midasit.com/job", 
            "selector": "li"
        },
        {
            "name": "삼성SDS",
            "url": "https://www.samsungsds.com/kr/about/recruit.html",
            "selector": "div div.checkBox"
        }
    ]
    
    for company in failed_companies:
        debug_company(company["name"], company["url"], company["selector"])

if __name__ == "__main__":
    main()