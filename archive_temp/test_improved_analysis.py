#!/usr/bin/env python3
"""개선된 셀렉터 분석 테스트 스크립트"""

import sys
import os
sys.path.append('src')

from bs4 import BeautifulSoup
from src.analyze_titles import JobPostingSelectorAnalyzer

def test_improved_filtering():
    """개선된 필터링 로직을 테스트합니다."""
    
    analyzer = JobPostingSelectorAnalyzer()
    
    # 문제가 있었던 텍스트들
    problematic_texts = [
        "경력 2 ~ 5년",
        "브랜드디자인팀", 
        "퍼포먼스마케팅팀",
        "아이리스브라이트",
        "인턴 · 정규직 · 계약직",
        "채용 프로세스",
        "Contact",
        "관계사 선택관계사 선택전자삼성전자",
        "기타 사항국가등록장애인",
        "셀리맥스 채용 홈페이지입니다.",
        "우리는 지금채용 중입니다!",
        "스토리타코이야기"
    ]
    
    # 올바른 채용공고 텍스트들
    valid_texts = [
        "백엔드 개발자",
        "프론트엔드 개발자", 
        "UI/UX 디자이너",
        "데이터 사이언티스트",
        "마케팅 매니저",
        "프로덕트 기획자",
        "DevOps 엔지니어",
        "QA 엔지니어"
    ]
    
    print("=== 문제가 있었던 텍스트들 ===")
    for text in problematic_texts:
        result = analyzer._is_potential_job_posting(text)
        print(f"{'❌' if not result else '⚠️ '} {text}: {result}")
    
    print("\n=== 올바른 채용공고 텍스트들 ===") 
    for text in valid_texts:
        result = analyzer._is_potential_job_posting(text)
        print(f"{'✅' if result else '❌'} {text}: {result}")
        
        # 디버그 정보
        if not result:
            has_job_keyword = any(keyword in text for keyword in analyzer.job_keywords)
            import re
            job_title_pattern = r'(백엔드|프론트엔드|풀스택|모바일|웹|UI/UX|그래픽|브랜드|마케팅|데이터|AI|ML|DevOps|QA|기획|운영|영업|HR|재무|법무|개발자|디자이너|엔지니어|매니저|기획자|사이언티스트)'
            has_job_pattern = bool(re.search(job_title_pattern, text))
            
            # 제외 패턴 체크
            excluded_by = None
            for pattern in analyzer.exclude_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    excluded_by = pattern
                    break
            
            print(f"  -> 키워드: {has_job_keyword}, 패턴: {has_job_pattern}, 제외됨: {excluded_by}")

if __name__ == "__main__":
    test_improved_filtering()