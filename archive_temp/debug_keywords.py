#!/usr/bin/env python3
"""키워드 매칭 디버그"""

import sys
sys.path.append('src')
from src.analyze_titles import JobPostingSelectorAnalyzer

analyzer = JobPostingSelectorAnalyzer()

text = "백엔드 개발자"
print(f"테스트 텍스트: {text}")
print(f"job_keywords: {analyzer.job_keywords}")

has_job_keyword = any(keyword in text for keyword in analyzer.job_keywords)
print(f"키워드 매칭: {has_job_keyword}")

for keyword in analyzer.job_keywords:
    if keyword in text:
        print(f"  - 매칭된 키워드: '{keyword}'")

import re
job_title_pattern = r'(백엔드|프론트엔드|풀스택|모바일|웹|UI/UX|그래픽|브랜드|마케팅|데이터|AI|ML|DevOps|QA|기획|운영|영업|HR|재무|법무|개발자|디자이너|엔지니어|매니저|기획자|사이언티스트)'
has_job_pattern = bool(re.search(job_title_pattern, text))
print(f"패턴 매칭: {has_job_pattern}")

result = analyzer._is_potential_job_posting(text)
print(f"최종 결과: {result}")