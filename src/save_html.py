import os
import time
import pandas as pd
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

def create_minimal_driver():
    """최소한의 설정으로 가장 빠른 드라이버"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--disable-css")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.set_page_load_timeout(10)  # 10초로 제한
    return driver

def save_html_from_csv(csv_path, html_dir):
    if not os.path.exists(html_dir):
        os.makedirs(html_dir)

    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"오류: {csv_path} 파일을 찾을 수 없습니다.")
        return

    selenium_needed = df['selenium_required'].any()
    driver = None
    
    if selenium_needed:
        driver = create_minimal_driver()

    try:
        for index, row in df.iterrows():
            company_name = row['회사명']
            url = row['채용공고 URL']
            use_selenium = row['selenium_required']
            
            file_path = os.path.join(html_dir, f"{company_name}.html")
            if os.path.exists(file_path):
                continue

            try:
                if not use_selenium:
                    print(f"[{index+1}] '{company_name}' - requests")
                    response = requests.get(url, timeout=8)
                    html_content = response.text
                else:
                    print(f"[{index+1}] '{company_name}' - selenium")
                    driver.get(url)
                    time.sleep(2)  # 간단한 2초 대기
                    html_content = driver.page_source

                if html_content:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    print(f"  ✓ 저장됨")

            except Exception as e:
                print(f"  ✗ 오류: {e}")

    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_file = os.path.join(base_dir, 'data', '채용공고_목록.csv')
    html_folder = os.path.join(base_dir, 'html')
    save_html_from_csv(csv_file, html_folder)