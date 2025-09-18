#!/usr/bin/env python3
"""선택자 분석 실패한 회사들 디버그"""

import sys
import os
sys.path.append('src')

import requests
from bs4 import BeautifulSoup
from analyze_titles import JobPostingSelectorAnalyzer

def analyze_failed_company(company_name, url):
    print(f"\n{'='*60}")
    print(f"🔍 {company_name} 분석")
    print(f"URL: {url}")
    print(f"{'='*60}")
    
    try:
        # HTML 가져오기
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        print(f"✅ HTML 가져오기 성공 ({len(response.content)} bytes)")
        
        # 분석기 초기화
        analyzer = JobPostingSelectorAnalyzer()
        
        # 1. potential elements 확인
        print(f"\n=== 1. Potential Elements 검사 ===")
        potential_count = 0
        potential_elements = []
        
        for element in soup.find_all(['p', 'div', 'span', 'a', 'strong', 'h2', 'h3', 'h4', 'li', 'dt', 'td']):
            # blacklist 체크
            is_blacklisted = any(
                parent.name in analyzer.blacklist or 
                any(b in (parent.get('class', []) + ([parent.get('id')] if parent.get('id') else [])) 
                    for b in analyzer.blacklist) 
                for parent in element.find_parents()
            )
            
            if is_blacklisted:
                continue
                
            text = element.get_text(strip=True)
            if analyzer._is_potential_job_posting(text):
                potential_count += 1
                potential_elements.append((element, text))
                if potential_count <= 15:
                    parent_info = f"{element.name}"
                    if element.get('class'):
                        parent_info += f".{'.'.join(element.get('class'))}"
                    print(f"  {potential_count:2d}. [{parent_info:30s}] {text[:80]}")
        
        print(f"\n총 potential elements: {potential_count}개")
        
        if potential_count < 3:
            print(f"❌ Potential elements가 {potential_count}개로 부족함 (최소 3개 필요)")
            
            # 키워드별 세부 분석
            print(f"\n=== 키워드별 세부 분석 ===")
            job_keywords = analyzer.job_keywords
            for keyword in job_keywords[:10]:  # 처음 10개만
                elements = soup.find_all(string=lambda text: text and keyword in text)
                if elements:
                    print(f"'{keyword}': {len(elements)}개 발견")
                    for elem in elements[:2]:
                        text = elem.strip()
                        if len(text) > 5:
                            parent = elem.parent
                            if parent:
                                tag_info = f"{parent.name}"
                                if parent.get('class'):
                                    tag_info += f".{'.'.join(parent.get('class'))}"
                                is_potential = analyzer._is_potential_job_posting(text)
                                print(f"  - [{tag_info:20s}] {text[:60]} → {is_potential}")
            
            return None, []
        
        # 2. 셀렉터 분석 시도
        print(f"\n=== 2. 셀렉터 분석 시도 ===")
        best_selector, titles = analyzer.find_best_selector(soup)
        
        if best_selector:
            print(f"🎯 찾은 최적 셀렉터: {best_selector}")
            print(f"📋 채용공고 목록 ({len(titles)}개):")
            for i, title in enumerate(titles[:10], 1):
                print(f"  {i:2d}. {title}")
        else:
            print("❌ 적절한 셀렉터를 찾지 못했습니다.")
        
        # 3. 수동 패턴 검사
        print(f"\n=== 3. 수동 패턴 검사 ===")
        common_job_selectors = [
            'ul li', 'ol li', '.list li', '.job-list li', '.career-list li',
            '.job-item', '.position', '.recruit', '.career', '.opening',
            'h3', 'h4', '.title', '.job-title', '.position-title',
            'a[href*="job"]', 'a[href*="career"]', 'a[href*="position"]'
        ]
        
        for selector in common_job_selectors:
            try:
                elements = soup.select(selector)
                if elements:
                    job_like_count = 0
                    titles = []
                    for elem in elements:
                        text = elem.get_text(strip=True)
                        if text and len(text) > 2:
                            titles.append(text)
                            if analyzer._is_potential_job_posting(text):
                                job_like_count += 1
                    
                    if job_like_count >= 3 or len(titles) >= 5:
                        print(f"🔍 {selector:25s}: {len(elements):3d}개, 채용관련 {job_like_count}개")
                        for i, title in enumerate(titles[:5], 1):
                            is_potential = analyzer._is_potential_job_posting(title)
                            print(f"    {i}. {title[:60]} → {is_potential}")
                        if job_like_count >= 3:
                            print(f"    ✅ 유력한 셀렉터!")
                    elif len(titles) > 0:
                        print(f"   {selector:25s}: {len(elements):3d}개, 채용관련 {job_like_count}개")
            except Exception as e:
                pass
        
        return best_selector, titles
        
    except Exception as e:
        print(f"❌ 오류: {e}")
        return None, []

def main():
    # 실패한 회사들
    failed_companies = [
        ("마이다스아이티", "https://midas.recruiter.co.kr/career/home"),
        ("더파운더즈", "https://thevcfounders.com/career"),  # 예상 URL
        ("네오팜", "https://www.neopharm.co.kr/career"),  # 예상 URL
        ("스토리타코", "https://career.storytaco.com/"),  # 예상 URL
        ("아이리스브라이트", "https://www.irisbright.com/career"),  # 예상 URL
        ("아이엠뱅크", "https://www.i-m.co.kr/career")  # 예상 URL
    ]
    
    # 우선 마이다스아이티만 분석
    company, url = failed_companies[0]
    analyze_failed_company(company, url)

if __name__ == "__main__":
    main()