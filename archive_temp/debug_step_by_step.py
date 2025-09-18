#!/usr/bin/env python3
"""단계별 디버그"""

import sys
import re
sys.path.append('src')
from src.analyze_titles import JobPostingSelectorAnalyzer

analyzer = JobPostingSelectorAnalyzer()
text = "백엔드 개발자"

print(f"텍스트: {text}")

# 1. 길이 체크
length_ok = 10 <= len(text) <= 150
print(f"1. 길이 체크 (10 <= {len(text)} <= 150): {length_ok}")

if not length_ok:
    print("길이 체크 실패로 종료")
    exit()

# 2. 제외 패턴 체크
excluded = False
for pattern in analyzer.exclude_patterns:
    if re.search(pattern, text, re.IGNORECASE):
        print(f"2. 제외 패턴 매칭: {pattern}")
        excluded = True
        break

if not excluded:
    print("2. 제외 패턴: 매칭되지 않음 (OK)")

# 3. 직무 키워드 체크
has_job_keyword = any(keyword in text for keyword in analyzer.job_keywords)
print(f"3. 직무 키워드: {has_job_keyword}")

# 4. 직무 패턴 체크
job_title_pattern = r'(백엔드|프론트엔드|풀스택|모바일|웹|UI/UX|그래픽|브랜드|마케팅|데이터|AI|ML|DevOps|QA|기획|운영|영업|HR|재무|법무|개발자|디자이너|엔지니어|매니저|기획자|사이언티스트)'
has_job_pattern = bool(re.search(job_title_pattern, text))
print(f"4. 직무 패턴: {has_job_pattern}")

# 5. 최소 조건 체크
min_condition = has_job_keyword or has_job_pattern
print(f"5. 최소 조건 ({has_job_keyword} or {has_job_pattern}): {min_condition}")

if not min_condition:
    print("최소 조건 실패로 종료")
    exit()

# 6. 팀명/부서명 제외
team_pattern = r'^[\가-힣]+팀$|^[\가-힣]+본부$|^[\가-힣]+부문$'
is_team_name = bool(re.search(team_pattern, text))
print(f"6. 팀명/부서명 체크: {is_team_name}")

if is_team_name:
    print("팀명/부서명 제외로 종료")
    exit()

print("7. 모든 조건 통과 - True 반환")

# 실제 함수 결과 비교
actual_result = analyzer._is_potential_job_posting(text)
print(f"실제 함수 결과: {actual_result}")