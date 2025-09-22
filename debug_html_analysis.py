#!/usr/bin/env python3
import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from src.analyze_titles import JobPostingSelectorAnalyzer

def create_debug_html_for_companies():
    """실패한 회사들의 실제 HTML을 생성하고 분석"""

    # 실패한 회사들의 URL 목록
    failed_companies = {
        '삼성전자(주)': 'https://www.samsungcareers.com/hr/',
        '현대자동차(주)': 'https://recruit.hd.com/kr/mainLayout/apply',
        'LG전자(주)': 'https://careers.lg.com/apply',
        'SK이노베이션(주)': 'https://recruit.skinnovation.com/ui/apply/applyList.do',
        '농협금융지주 주식회사': 'https://with.nonghyup.com/jbnf/jbnfLst.do'
    }

    # Chrome 옵션 설정
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-web-security')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.set_page_load_timeout(30)

    analyzer = JobPostingSelectorAnalyzer()

    # 디버그 디렉토리 생성
    debug_dir = '/opt/airflow/debug_html'
    os.makedirs(debug_dir, exist_ok=True)

    print("=== 실패한 회사들의 HTML 분석 및 개선 방안 도출 ===\\n")

    for company_name, url in failed_companies.items():
        print(f"🔍 {company_name} 분석 중...")

        try:
            # 페이지 로드
            print(f"  - URL 접속: {url}")
            driver.get(url)

            # JavaScript 실행 대기
            time.sleep(5)

            # 추가 스크롤 및 대기 (AJAX 로딩 완료 위해)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(2)

            # HTML 가져오기
            html_content = driver.page_source
            soup = BeautifulSoup(html_content, 'html.parser')

            # HTML 파일 저장
            html_file = os.path.join(debug_dir, f"{company_name}.html")
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"  - HTML 저장: {html_file}")

            # 현재 알고리즘으로 분석
            print("  - 현재 알고리즘으로 분석 시도...")
            selector, titles = analyzer.find_best_selector(soup)

            if selector and titles:
                print(f"  ✅ 성공: {selector}")
                print(f"     예시: {titles[:3]}")
            else:
                print("  ❌ 실패: 선택자를 찾지 못함")

                # 실패 원인 분석
                print("  🔎 실패 원인 분석:")

                # 1. 모든 링크 확인
                all_links = soup.find_all('a', href=True)
                print(f"    - 전체 링크 수: {len(all_links)}")

                # 2. 채용공고 관련 키워드가 포함된 링크들 찾기
                job_related_links = []
                for link in all_links:
                    text = link.get_text(strip=True)
                    if text and ('채용' in text or '인턴' in text or '경력' in text or '신입' in text or
                               'job' in text.lower() or 'career' in text.lower() or 'recruit' in text.lower()):
                        job_related_links.append(text)

                print(f"    - 채용 관련 링크 수: {len(job_related_links)}")
                if job_related_links:
                    print(f"    - 예시: {job_related_links[:5]}")

                # 3. 가능한 채용공고 컨테이너 찾기
                possible_containers = []
                for element in soup.find_all(['div', 'section', 'ul', 'table']):
                    element_id = element.get('id', '').lower()
                    element_classes = ' '.join(element.get('class', [])).lower()

                    if any(keyword in element_id + element_classes for keyword in
                          ['job', 'recruit', 'career', 'position', 'opening', 'notice', 'list']):
                        links_in_container = element.find_all('a', href=True)
                        if len(links_in_container) > 0:
                            possible_containers.append({
                                'tag': element.name,
                                'id': element_id,
                                'classes': element_classes,
                                'link_count': len(links_in_container),
                                'sample_texts': [link.get_text(strip=True)[:50] for link in links_in_container[:3]]
                            })

                print(f"    - 가능한 채용공고 컨테이너 수: {len(possible_containers)}")
                for container in possible_containers[:3]:
                    print(f"      * {container['tag']} (id: {container['id']}, classes: {container['classes']})")
                    print(f"        링크 수: {container['link_count']}, 샘플: {container['sample_texts']}")

            print()

        except Exception as e:
            print(f"  ❌ 오류 발생: {e}")
            print()

        time.sleep(2)  # 서버 부하 방지

    driver.quit()

    print("=== 분석 완료 ===")
    print(f"HTML 파일들이 {debug_dir}에 저장되었습니다.")

    # 개선 방안 제시
    print("\\n=== 개선 방안 ===")
    print("1. JavaScript 로딩 대기 시간 증가")
    print("2. 더 유연한 텍스트 필터링 조건")
    print("3. 동적 컨테이너 탐지 알고리즘 개선")
    print("4. 다양한 선택자 패턴 추가")

if __name__ == "__main__":
    create_debug_html_for_companies()