#!/usr/bin/env python3
"""개선된 로직으로 삼성SDS 셀렉터 테스트"""

import sys
import os
sys.path.append('src')

import requests
from bs4 import BeautifulSoup
from analyze_titles import JobPostingSelectorAnalyzer

def test_samsung_selector():
    print("🔍 개선된 로직으로 삼성SDS 셀렉터 분석...")
    
    url = "https://www.samsungsds.com/kr/careers/overview/about_care_over.html"
    
    try:
        # HTML 가져오기
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        print(f"✅ HTML 가져오기 성공 ({len(response.content)} bytes)")
        
        # 개선된 분석기로 테스트
        analyzer = JobPostingSelectorAnalyzer()
        
        print("\n=== 개선된 키워드로 potential job posting 체크 ===")
        test_texts = ["사업 개발", "R&D", "개발자", "엔지니어", "디자이너"]
        for text in test_texts:
            result = analyzer._is_potential_job_posting(text)
            print(f"'{text}': {result}")
        
        # 실제 셀렉터 분석
        print(f"\n=== 자동 셀렉터 분석 ===")
        best_selector, titles = analyzer.find_best_selector(soup)
        
        if best_selector:
            print(f"🎯 찾은 최적 셀렉터: {best_selector}")
            print(f"📋 채용공고 목록 ({len(titles)}개):")
            for i, title in enumerate(titles[:10], 1):
                print(f"  {i}. {title}")
        else:
            print("❌ 적절한 셀렉터를 찾지 못했습니다.")
        
        # 수동으로 올바른 셀렉터 테스트
        print(f"\n=== 올바른 셀렉터 수동 테스트 ===")
        correct_selectors = [
            "ul.abt_care_list2 li .tit",
            "ul.abt_care_list2 li strong.tit",
            ".abt_care_list2 li .tit"
        ]
        
        for selector in correct_selectors:
            try:
                elements = soup.select(selector)
                titles = [elem.get_text(strip=True) for elem in elements]
                print(f"{selector:30s}: {len(titles)}개")
                for i, title in enumerate(titles, 1):
                    print(f"  {i}. {title}")
            except Exception as e:
                print(f"{selector:30s}: 오류 - {e}")
        
        # 모든 potential elements 확인
        print(f"\n=== 모든 potential elements 확인 ===")
        count = 0
        for element in soup.find_all(['p', 'div', 'span', 'a', 'strong', 'h2', 'h3', 'h4', 'li', 'dt', 'td']):
            text = element.get_text(strip=True)
            if analyzer._is_potential_job_posting(text):
                count += 1
                if count <= 10:
                    parent_info = f"{element.name}"
                    if element.get('class'):
                        parent_info += f".{'.'.join(element.get('class'))}"
                    print(f"  {count}. [{parent_info}] {text}")
        
        print(f"총 potential elements: {count}개")
        
    except Exception as e:
        print(f"❌ 오류: {e}")

if __name__ == "__main__":
    test_samsung_selector()