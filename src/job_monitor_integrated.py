import os
import time
import pandas as pd
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime
import logging
from typing import Dict, List, Set
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

class JobMonitor:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.data_dir = os.path.join(base_dir, 'data')
        self.config_path = os.path.join(self.data_dir, '채용공고_목록.csv')
        self.results_path = os.path.join(self.data_dir, 'job_postings_latest.csv')
        
        # .env에서 웹훅 URL 로드
        self.webhook_url = os.getenv('SLACK_WEBHOOK_URL')
        
        # 로깅 설정
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def create_minimal_driver(self):
        """최소한의 설정으로 빠른 드라이버"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-images")
        chrome_options.add_argument("--disable-css")
        
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        driver.set_page_load_timeout(10)
        return driver

    def get_html_content(self, url, use_selenium, driver=None):
        """URL에서 HTML 내용을 가져오기"""
        try:
            if not use_selenium:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                return response.text
            else:
                if driver is None:
                    raise Exception("Selenium이 필요하지만 드라이버가 없습니다.")
                driver.get(url)
                time.sleep(2)
                return driver.page_source
        except Exception as e:
            self.logger.error(f"HTML 가져오기 실패: {e}")
            return None

    def extract_current_jobs(self) -> Dict[str, Set[str]]:
        """현재 채용공고를 추출하여 회사별로 정리"""
        if not os.path.exists(self.config_path):
            self.logger.error(f"설정 파일 '{self.config_path}'을 찾을 수 없습니다.")
            return {}

        try:
            df_config = pd.read_csv(self.config_path)
        except Exception as e:
            self.logger.error(f"설정 파일 처리 중 오류: {e}")
            return {}

        # 선택자가 설정된 회사만 처리
        df_config = df_config[df_config['selector'].notna() & (df_config['selector'].str.strip() != '')]
        
        if df_config.empty:
            self.logger.warning("선택자가 설정된 회사가 없습니다.")
            return {}

        selenium_needed = df_config['selenium_required'].any()
        driver = None
        
        if selenium_needed:
            self.logger.info("Selenium 드라이버 초기화 중...")
            driver = self.create_minimal_driver()

        current_jobs = {}
        
        self.logger.info("채용 공고 추출 시작...")
        start_time = time.time()
        
        try:
            for index, row in df_config.iterrows():
                company_name = row['회사명']
                url = row['채용공고 URL']
                use_selenium = row['selenium_required']
                selector = row['selector']
                
                self.logger.info(f"[{index+1}/{len(df_config)}] {company_name} 처리 중...")
                
                html_content = self.get_html_content(url, use_selenium, driver)
                if not html_content:
                    continue
                    
                try:
                    soup = BeautifulSoup(html_content, 'html.parser')
                    postings = soup.select(selector)
                    
                    if not postings:
                        self.logger.warning(f"    '{selector}' 선택자로 공고를 찾지 못함")
                        continue

                    job_titles = set()
                    for post in postings:
                        title = post.get_text(strip=True)
                        if len(title) > 5:
                            job_titles.add(title)
                    
                    if job_titles:
                        current_jobs[company_name] = job_titles
                        self.logger.info(f"    성공: {len(job_titles)}개 공고 추출됨")
                    
                except Exception as e:
                    self.logger.error(f"    HTML 파싱 실패: {e}")
                    continue
                    
        finally:
            if driver:
                driver.quit()
        
        elapsed_time = time.time() - start_time
        total_jobs = sum(len(jobs) for jobs in current_jobs.values())
        self.logger.info(f"총 {total_jobs}개 공고 수집 완료 (실행시간: {elapsed_time:.1f}초)")
        
        return current_jobs

    def load_existing_jobs(self) -> Dict[str, Set[str]]:
        """기존에 저장된 채용공고 로드"""
        if not os.path.exists(self.results_path):
            return {}
        
        try:
            df = pd.read_csv(self.results_path)
            existing_jobs = {}
            
            for company in df['company_name'].unique():
                company_jobs = set(
                    df[df['company_name'] == company]['job_posting_title'].tolist()
                )
                existing_jobs[company] = company_jobs
            
            return existing_jobs
        except Exception as e:
            self.logger.error(f"기존 공고 로드 오류: {e}")
            return {}

    def find_new_jobs(self, current_jobs: Dict[str, Set[str]], existing_jobs: Dict[str, Set[str]]) -> Dict[str, List[str]]:
        """새로운 채용공고 찾기"""
        new_jobs = {}
        
        for company, current_titles in current_jobs.items():
            existing_titles = existing_jobs.get(company, set())
            new_titles = current_titles - existing_titles
            
            if new_titles:
                new_jobs[company] = list(new_titles)
                self.logger.info(f"{company}: {len(new_titles)}개 새로운 공고 발견")
        
        return new_jobs

    def save_jobs(self, current_jobs: Dict[str, Set[str]]):
        """현재 채용공고를 CSV 파일로 저장"""
        if not current_jobs:
            self.logger.warning("저장할 공고가 없습니다.")
            return
        
        all_postings = []
        crawl_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        for company_name, job_titles in current_jobs.items():
            for title in job_titles:
                all_postings.append({
                    "company_name": company_name,
                    "job_posting_title": title,
                    "crawl_datetime": crawl_datetime
                })
        
        try:
            df = pd.DataFrame(all_postings)
            df.to_csv(self.results_path, index=False, encoding='utf-8-sig')
            self.logger.info(f"결과를 '{self.results_path}'에 저장 완료")
        except Exception as e:
            self.logger.error(f"파일 저장 오류: {e}")

    def send_slack_notification(self, new_jobs: Dict[str, List[str]]):
        """슬랙으로 알림 전송"""
        if not new_jobs:
            self.logger.info("전송할 새로운 공고가 없습니다.")
            return

        if not self.webhook_url:
            self.logger.error("❌ 슬랙 웹훅 URL이 .env 파일에 설정되지 않았습니다.")
            self.logger.error("   .env 파일에 SLACK_WEBHOOK_URL=your_webhook_url 을 추가하세요.")
            return

        # 메시지 포맷팅
        current_time = datetime.now().strftime('%H:%M')
        message_parts = [f"🚀 *새로운 채용공고 알림* ({current_time})\n"]
        
        total_new_jobs = sum(len(jobs) for jobs in new_jobs.values())
        message_parts.append(f"📊 총 {total_new_jobs}개의 새로운 공고가 발견되었습니다!\n")
        
        for company_name, jobs in new_jobs.items():
            message_parts.append(f"\n📢 *{company_name}*")
            for job_title in jobs:
                # 슬랙 특수문자 이스케이프
                escaped_title = job_title.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")
                message_parts.append(f"• {escaped_title}")
        
        message = "\n".join(message_parts)
        
        payload = {
            "text": message,
            "username": "채용공고 봇",
            "icon_emoji": ":briefcase:"
        }
        
        try:
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            if response.status_code == 200:
                self.logger.info("✅ 슬랙 알림 전송 완료")
            else:
                self.logger.error(f"❌ 슬랙 알림 전송 실패: {response.status_code}")
        except Exception as e:
            self.logger.error(f"❌ 슬랙 알림 전송 오류: {e}")

    def run_monitoring(self):
        """전체 모니터링 프로세스 실행"""
        self.logger.info("=" * 60)
        self.logger.info("채용공고 모니터링 시작")
        self.logger.info("=" * 60)
        
        # 1단계: 기존 공고 로드
        existing_jobs = self.load_existing_jobs()
        if existing_jobs:
            total_existing = sum(len(jobs) for jobs in existing_jobs.values())
            self.logger.info(f"기존 공고: {total_existing}개")
        else:
            self.logger.info("기존 공고 없음 (첫 실행)")
        
        # 2단계: 현재 공고 추출
        current_jobs = self.extract_current_jobs()
        if not current_jobs:
            self.logger.error("채용공고 추출 실패")
            return False
        
        # 3단계: 새로운 공고 찾기
        new_jobs = self.find_new_jobs(current_jobs, existing_jobs)
        
        # 4단계: 새로운 공고가 있으면 알림 전송
        if new_jobs:
            total_new = sum(len(jobs) for jobs in new_jobs.values())
            self.logger.info(f"🎉 총 {total_new}개의 새로운 공고 발견!")
            self.send_slack_notification(new_jobs)
        else:
            self.logger.info("새로운 공고가 없습니다.")
        
        # 5단계: 현재 공고로 업데이트
        self.save_jobs(current_jobs)
        
        self.logger.info("=" * 60)
        self.logger.info("채용공고 모니터링 완료")
        self.logger.info("=" * 60)
        
        return True

def main():
    """메인 실행 함수"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monitor = JobMonitor(base_dir)
    monitor.run_monitoring()

if __name__ == "__main__":
    main()