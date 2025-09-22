#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import json

def analyze_samsung_html():
    """삼성전자 HTML 구조 분석"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.set_page_load_timeout(15)

    try:
        print("=== 삼성전자 채용 페이지 분석 ===")
        driver.get('https://samsung.recruiter.co.kr/app/jobnotice/list')
        time.sleep(3)

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # 현재 선택자로 찾은 링크들
        current_selector = "a[href]"
        current_links = soup.select(current_selector)

        print(f"\n현재 선택자 '{current_selector}'로 찾은 링크 수: {len(current_links)}")
        print("첫 20개 링크들:")
        for i, link in enumerate(current_links[:20]):
            text = link.get_text(strip=True)
            if text:
                print(f"{i+1}. {text[:100]}")

        # 구조 분석: 실제 채용공고가 있는 영역 찾기
        print("\n=== HTML 구조 분석 ===")

        # ID나 클래스에 job, recruit, notice 등이 포함된 요소들 찾기
        job_containers = []
        for element in soup.find_all(['div', 'section', 'ul', 'table']):
            element_id = element.get('id', '').lower()
            element_classes = ' '.join(element.get('class', [])).lower()

            if any(keyword in element_id + element_classes for keyword in ['job', 'recruit', 'notice', 'posting', 'list']):
                links_in_container = element.find_all('a', href=True)
                if len(links_in_container) > 3:  # 여러 링크가 있는 컨테이너만
                    job_containers.append({
                        'element': element.name,
                        'id': element_id,
                        'classes': element_classes,
                        'link_count': len(links_in_container),
                        'sample_texts': [link.get_text(strip=True)[:50] for link in links_in_container[:3]]
                    })

        print("채용공고 관련 컨테이너들:")
        for container in job_containers:
            print(f"- {container['element']} (id: {container['id']}, classes: {container['classes']})")
            print(f"  링크 수: {container['link_count']}")
            print(f"  샘플: {container['sample_texts']}")

        # 메인 컨텐츠 영역 찾기
        main_content = soup.find(['main', 'div'], {'class': ['content', 'main', 'container']})
        if main_content:
            print(f"\n메인 컨텐츠 영역 찾음: {main_content.name}")
            content_links = main_content.find_all('a', href=True)
            print(f"메인 컨텐츠 내 링크 수: {len(content_links)}")

    finally:
        driver.quit()

if __name__ == "__main__":
    analyze_samsung_html()