import os
import time
import pandas as pd
import requests
import re
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime
import pytz
import logging
from typing import Dict, List, Set, Tuple, Optional
from dotenv import load_dotenv
from google_sheet_utils import GoogleSheetManager
from analyze_titles import JobPostingSelectorAnalyzer
from utils import stabilize_selector, SeleniumRequirementChecker
import concurrent.futures

load_dotenv()

class JobMonitoringDAG:
    def __init__(self, base_dir: str, worksheet_name: str = '[등록]채용홈페이지 모음', webhook_url_env: str = 'SLACK_WEBHOOK_URL', results_filename: str = 'job_postings_latest.csv'):
        self.base_dir = base_dir
        self.data_dir = os.path.join(base_dir, 'data')
        self.html_dir = os.path.join(base_dir, 'html')
        # HTML 디렉토리 생성 (더 안전한 방식)
        try:
            os.makedirs(self.html_dir, exist_ok=True)
        except (FileExistsError, OSError):
            # 이미 존재하거나 권한 문제가 있어도 계속 진행
            pass
        self.worksheet_name = worksheet_name
        self.webhook_url_env = webhook_url_env  # 환경변수 이름 저장
        self.results_path = os.path.join(self.data_dir, results_filename)
        self.webhook_url = os.getenv(webhook_url_env)
        self.company_urls = {}

        self._setup_logging()

    def _setup_logging(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        # 이 로거나 루트 로거에 핸들러가 없을 때만 핸들러를 추가하여 중복 방지
        if not self.logger.handlers and not logging.getLogger().handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def run(self):
        self.sheet_manager = GoogleSheetManager(self.base_dir)
        self.selenium_checker = SeleniumRequirementChecker()
        self.selector_analyzer = JobPostingSelectorAnalyzer()

        self.logger.info(f"🚀 Job Monitoring DAG 시작 - {self.worksheet_name}")
        df_config = self.sheet_manager.get_all_records_as_df(self.worksheet_name)
        if df_config.empty:
            self.logger.error(f"Google Sheets에서 설정 정보를 가져오지 못했습니다: {self.worksheet_name}")
            return

        original_df_config = df_config.copy()

        self.logger.info("--- 1. 전처리 시작 ---")
        df_processed = self.preprocess_companies(df_config)
        self.logger.info("--- 1. 전처리 종료 ---")

        self.logger.info("--- 2. 선택자 안정화 시작 ---")
        df_processed = self.stabilize_selectors(df_processed)
        self.logger.info("--- 2. 선택자 안정화 종료 ---")

        updated_count = 0
        for idx in df_processed.index:
            if idx in df_config.index:
                if pd.isna(original_df_config.loc[idx, 'selenium_required']) or original_df_config.loc[idx, 'selenium_required'] == '':
                    if df_processed.loc[idx, 'selenium_required'] in [0, 1, -1]:
                        updated_count += 1
                df_config.loc[idx] = df_processed.loc[idx]

        if updated_count > 0:
            self.logger.info(f"📝 {updated_count}개 회사의 selenium_required 값이 업데이트되었습니다.")

        has_changes = not df_config.equals(original_df_config)

        if has_changes:
            if len(df_config) < len(original_df_config):
                self.logger.warning(f"⚠️ 데이터 손실 방지: 원본({len(original_df_config)}개) 대비 현재({len(df_config)}개)로 행이 줄어들었습니다. 시트 업데이트를 건너뜁니다.")
            else:
                self.logger.info("Google Sheets에 변경 사항 업데이트 중...")
                self.sheet_manager.update_sheet_from_df(df_config, self.worksheet_name)
                self.logger.info("✅ Google Sheets 업데이트 완료")
        else:
            self.logger.info("설정 변경 사항이 없어 Google Sheets 업데이트를 건너뜁니다.")

        current_jobs, failed_companies = self.crawl_jobs(df_processed)
        self.compare_and_notify(current_jobs, failed_companies)
        self.logger.info(f"✅ Job Monitoring DAG 종료 - {self.worksheet_name}")

    def _process_company_preprocess(self, args):
        index, row, existing_selectors = args
        company_name = row['회사_한글_이름']
        url = row['job_posting_url']
        self.logger.info(f"- {company_name} 처리 중...")

        driver = self.create_minimal_driver() if row['selenium_required'] else None
        html_content = self.get_html_content(url, row['selenium_required'], driver)
        if driver:
            driver.quit()

        if html_content:
            self.logger.info(f"  - HTML 가져오기 성공")
            soup = BeautifulSoup(html_content, 'html.parser')
            found_selector = self._try_existing_selectors(soup, existing_selectors, company_name)

            if found_selector:
                return index, found_selector, None
            else:
                best_selector, _ = self.selector_analyzer.find_best_selector(soup)
                if best_selector:
                    return index, best_selector, None
                else:
                    self.logger.warning("  - 선택자 분석 실패")
                    return index, None, None
        else:
            self.logger.error(f"  - HTML 가져오기 실패: {company_name} (selenium_required를 -1로 설정)")
            return index, None, -1

    def preprocess_companies(self, df: pd.DataFrame) -> pd.DataFrame:
        self.logger.info(f"전체 회사 데이터: {len(df)}개")

        valid_companies_mask = (
            df['회사_한글_이름'].notna() & (df['회사_한글_이름'].str.strip() != '') &
            df['job_posting_url'].notna() & (df['job_posting_url'].str.strip() != '')
        )

        invalid_count = len(df) - valid_companies_mask.sum()
        if invalid_count > 0:
            self.logger.info(f"URL이 없어 전처리에서 제외되는 회사: {invalid_count}개 (시트에서는 유지됨)")

        self.logger.info(f"전처리 대상 회사 (URL 포함): {valid_companies_mask.sum()}개")

        if valid_companies_mask.any():
            self._fill_missing_selenium_required(df, valid_companies_mask)

        companies_to_process = df[
            valid_companies_mask &
            (df['selector'].isna() | (df['selector'] == '')) &
            (df['original_selector'].isna() | (df['original_selector'] == '')) &
            (df['selenium_required'] != -1)
        ]

        if companies_to_process.empty:
            self.logger.info("새로 전처리할 회사가 없습니다.")
            return df

        self.logger.info(f"{len(companies_to_process)}개 회사에 대한 전처리를 시작합니다.")

        existing_selectors = self._get_existing_selectors(df)
        self.logger.info(f"기존 회사들에서 사용 중인 선택자 {len(existing_selectors)}개를 우선 적용합니다.")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            args_list = [(index, row, existing_selectors) for index, row in companies_to_process.iterrows()]
            results = executor.map(self._process_company_preprocess, args_list)

            for index, new_selector, selenium_status in results:
                if new_selector:
                    df.loc[index, 'selector'] = new_selector
                    self.logger.info(f"  - 선택자 적용 성공: {new_selector}")
                if selenium_status is not None:
                    df.loc[index, 'selenium_required'] = selenium_status

        return df

    def stabilize_selectors(self, df: pd.DataFrame) -> pd.DataFrame:
        changed = False
        for index, row in df.iterrows():
            selector = row['selector']
            original_selector = row.get('original_selector', '')

            if (pd.isna(selector) or selector == '') and pd.notna(original_selector) and original_selector != '':
                stabilized = stabilize_selector(original_selector, conservative=False)
                df.loc[index, 'selector'] = stabilized
                self.logger.info(f"- {row['회사_한글_이름']} original_selector를 안정화하여 적용: {original_selector} -> {stabilized}")
                changed = True
            elif pd.notna(selector) and selector != '':
                stabilized = stabilize_selector(selector, conservative=True)
                if selector != stabilized:
                    df.loc[index, 'selector'] = stabilized
                    self.logger.info(f"- {row['회사_한글_이름']} 선택자 안정화: {selector} -> {stabilized}")
                    changed = True
        if not changed:
            self.logger.info("안정화할 선택자가 없습니다.")
        return df


    def _get_existing_selectors(self, df: pd.DataFrame) -> List[str]:
        """기존에 성공적으로 사용된 선택자들을 수집합니다."""
        existing_selectors = []

        valid_selectors = df[df['selector'].notna() & (df['selector'] != '')]['selector'].unique()
        existing_selectors.extend(valid_selectors)

        expanded_selectors = []
        for selector in valid_selectors:
            expanded_selectors.append(selector)
            stabilized = stabilize_selector(selector, conservative=False)
            if stabilized != selector and stabilized:
                expanded_selectors.append(stabilized)

        known_good_selectors = [
            "a div.sc-9b56f69e-0.jlntFl",
            "div.JobPostingsJobPosting__Layout-sc-6ae888f2-0.ffnSOB div.JobPostingsJobPosting__Bottom-sc-6ae888f2-5.iXrIoX",
            "#jobList > div.jobList_info > div > a > span.title",
            "div.RecruitList_left__5MzDR div.RecruitList_title-wrapper__Gvh1r p",
            "div.swiper-slide button p",
            "button div p",
            "li.job-item a",
            "td.job-title a",
            ".job-list li a",
            ".career-item .title",
        ]
        expanded_selectors.extend(known_good_selectors)

        selector_counts = df[df['selector'].notna() & (df['selector'] != '')]['selector'].value_counts()
        sorted_selectors = selector_counts.index.tolist()

        final_selectors = sorted_selectors + [s for s in expanded_selectors if s not in sorted_selectors]

        self.logger.info(f"수집된 선택자 {len(final_selectors)}개 (기존: {len(sorted_selectors)}개, 확장: {len(expanded_selectors)}개)")
        return final_selectors

    def _is_specific_enough_selector(self, selector: str) -> bool:
        """선택자가 충분히 구체적인지 판단합니다."""
        selector = selector.strip()
        if not selector:
            return False

        parts = selector.split()

        if len(parts) == 1:
            part = parts[0].lower()
            if '.' in part or '#' in part:
                return True
            if '[' in part and ']' in part:
                if part == 'a[href]' or part.endswith('[href]') :
                    return False
                return True
            if ':' in part:
                return True
            return False

        if len(parts) >= 2:
            return True

        return False

    def _try_existing_selectors(self, soup: BeautifulSoup, existing_selectors: List[str], _: str) -> Optional[str]:
        """기존 선택자들을 순서대로 시도해서 유효한 것을 찾습니다."""
        for i, selector in enumerate(existing_selectors):
            if not self._is_specific_enough_selector(selector):
                continue

            try:
                elements = soup.select(selector)
                if not elements:
                    continue

                titles = [elem.get_text(strip=True) for elem in elements]
                valid_titles = [title for title in titles if title and len(title) > 3]

                if len(valid_titles) >= 1:
                    job_related_titles = [title for title in valid_titles
                                        if self.selector_analyzer._is_potential_job_posting(title)]

                    if len(job_related_titles) >= 1:
                        quality_score = len(job_related_titles) / len(valid_titles)

                        if len(valid_titles) > 50:
                            if quality_score < 0.8:
                                continue
                        elif len(valid_titles) > 20:
                            if quality_score < 0.6:
                                continue
                        elif len(valid_titles) > 5:
                            if quality_score < 0.4:
                                continue

                        category = "기존" if i < 10 else "확장" if i < 50 else "패턴"
                        self.logger.info(f"  - {category} 선택자 '{selector}' 검증 성공 (채용공고: {len(job_related_titles)}개/{len(valid_titles)}개, 품질: {quality_score:.1%})")
                        if len(valid_titles) <= 5:
                            for title in valid_titles[:3]:
                                self.logger.info(f"    예시: {title[:50]}...")
                        return selector

            except Exception:
                continue

        return None

    def _fill_missing_selenium_required(self, df: pd.DataFrame, mask: pd.Series):
        """selenium_required 값이 없는 회사들을 자동으로 채웁니다. (병렬 처리)"""
        missing_selenium_mask = mask & (
            df['selenium_required'].isna() |
            (df['selenium_required'] == '') |
            (~df['selenium_required'].isin([0, 1, -1]))
        )
        missing_selenium = df[missing_selenium_mask]

        if missing_selenium.empty:
            self.logger.info("모든 회사의 selenium_required 값이 설정되어 있습니다.")
            return

        self.logger.info(f"{len(missing_selenium)}개 회사의 selenium_required 값을 병렬로 자동 설정 중...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_index = {
                executor.submit(self._determine_selenium_requirement, row['job_posting_url'], row['회사_한글_이름']): index
                for index, row in missing_selenium.iterrows()
            }

            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                company_name = missing_selenium.loc[index, '회사_한글_이름']
                try:
                    selenium_required = future.result()
                    df.loc[index, 'selenium_required'] = int(selenium_required)

                    selenium_text = "Selenium 필요" if selenium_required else "requests 사용"
                    self.logger.info(f"  - {company_name}: {selenium_text}")
                except Exception as e:
                    self.logger.error(f"  - {company_name} 처리 중 오류 발생: {e}")
                    df.loc[index, 'selenium_required'] = 1  # 오류 발생 시 기본값

        self.logger.info(f"{len(missing_selenium)}개 회사의 selenium_required 값 설정 완료.")
    
    def _determine_selenium_requirement(self, url: str, _: str) -> int:
        """URL을 기반으로 Selenium 필요 여부를 동적으로 판단합니다."""

        try:
            selenium_req = self.selenium_checker.check_selenium_requirement(url)
            result = int(selenium_req)
            self.logger.info(f"    🔍 Selenium 체크 결과: {url} -> {result}")
            return result
        except Exception as e:
            self.logger.info(f"    ⚠️ Selenium 체크 실패 ({url}): {e} -> 기본값 1 사용")
            return 1

    def _crawl_company(self, args):
        row, df_crawl = args
        company_name, url, use_selenium, selector = row['회사_한글_이름'], row['job_posting_url'], row['selenium_required'], row['selector']
        self.company_urls[company_name] = url
        self.logger.info(f"- {company_name} 크롤링 중...")

        driver = self.create_minimal_driver() if use_selenium else None
        html_content = self.get_html_content_for_crawling(url, use_selenium, driver, selector)
        if driver:
            driver.quit()

        if not html_content:
            return None, {'company': company_name, 'reason': 'HTML 가져오기 실패', 'url': url}

        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            postings = soup.select(selector)
            if not postings:
                return None, {'company': company_name, 'reason': f'선택자 \'{selector}\'로 공고를 찾지 못함', 'url': url}

            job_titles = {post.get_text(strip=True) for post in postings if post.get_text(strip=True).strip()}
            if job_titles:
                self.logger.info(f"  - 성공: {len(job_titles)}개 공고 추출")
                return company_name, job_titles
            else:
                return None, {'company': company_name, 'reason': '유효한 공고를 찾지 못함', 'url': url}
        except Exception as e:
            return None, {'company': company_name, 'reason': f'HTML 파싱 실패: {e}', 'url': url}

    def crawl_jobs(self, df_config: pd.DataFrame) -> Tuple[Dict[str, Set[str]], List[Dict]]:
        self.logger.info("--- 3. 채용 공고 크롤링 시작 ---")
        df_crawl = df_config[
            (df_config['회사_한글_이름'].notna() & (df_config['회사_한글_이름'].str.strip() != '')) &
            (df_config['job_posting_url'].notna() & (df_config['job_posting_url'].str.strip() != '')) &
            (df_config['selector'].notna() & (df_config['selector'] != '')) &
            (df_config['selenium_required'] != -1)
        ].copy()

        if df_crawl.empty:
            self.logger.warning("크롤링할 회사가 없습니다.")
            return {}, []

        current_jobs = {}
        failed_companies = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            args_list = [(row, df_crawl) for _, row in df_crawl.iterrows()]
            results = executor.map(self._crawl_company, args_list)

            for result in results:
                company_name, job_titles = result
                if company_name and job_titles:
                    current_jobs[company_name] = job_titles
                elif job_titles:
                    failed_companies.append(job_titles)

        self.logger.info("--- 3. 채용 공고 크롤링 종료 ---")
        return current_jobs, failed_companies

    def compare_and_notify(self, current_jobs: Dict, failed_companies: List):
        self.logger.info("--- 4. 비교 및 알림 시작 ---")
        existing_jobs = self.load_existing_jobs()
        new_jobs = self.find_new_jobs(current_jobs, existing_jobs)
        warnings = self.check_suspicious_results(current_jobs, existing_jobs, new_jobs)
        self.send_slack_notification(new_jobs, warnings, failed_companies)
        if current_jobs:
            self.save_jobs(current_jobs)
        self.logger.info("--- 4. 비교 및 알림 종료 ---")

    def get_html_content(self, url, use_selenium, driver=None, selector=None):
        """선택자 분석용 HTML 가져오기 메서드 (HTML 파일 저장용)"""
        max_retries = 2
        for attempt in range(max_retries):
            try:
                if not use_selenium:
                    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
                    response.raise_for_status()
                    return response.text
                else:
                    if driver is None: raise Exception("Selenium Driver가 없습니다.")
                    driver.get(url)

                    if selector:
                        from selenium.webdriver.common.by import By
                        from selenium.webdriver.support.ui import WebDriverWait
                        from selenium.webdriver.support import expected_conditions as EC
                        try:
                            WebDriverWait(driver, 20).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                            )
                            time.sleep(3)
                        except Exception:
                            self.logger.warning(f"''{selector}'' 요소를 기다리는 데 실패했습니다.")
                    else:
                        time.sleep(5)

                    return driver.page_source
            except Exception as e:
                if "timeout" in str(e).lower() and attempt < max_retries - 1:
                    self.logger.warning(f"페이지 로드 타임아웃 ({attempt + 1}/{max_retries}): {url} - 재시도 중...")
                    time.sleep(5)
                    continue
                else:
                    self.logger.error(f"HTML 가져오기 실패: {url}, 오류: {e}")
                    return None

    def get_html_content_for_crawling(self, url, use_selenium, driver=None, selector=None):
        """실제 크롤링용 HTML 가져오기 메서드 (selenium_required 값에 따라 분기)"""
        try:
            if not use_selenium:
                response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
                response.raise_for_status()
                return response.text
            else:
                if driver is None:
                    raise Exception("Selenium Driver가 없습니다.")

                max_retries = 2
                for attempt in range(max_retries):
                    try:
                        driver.get(url)

                        if selector:
                            from selenium.webdriver.common.by import By
                            from selenium.webdriver.support.ui import WebDriverWait
                            from selenium.webdriver.support import expected_conditions as EC
                            try:
                                WebDriverWait(driver, 20).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                                )
                                time.sleep(3)
                            except Exception:
                                self.logger.warning(f"선택자 '{selector}' 요소를 기다리는 데 실패했습니다.")
                        else:
                            time.sleep(5)

                        return driver.page_source

                    except Exception as e:
                        if "timeout" in str(e).lower() and attempt < max_retries - 1:
                            self.logger.warning(f"페이지 로드 타임아웃 ({attempt + 1}/{max_retries}): {url} - 재시도 중...")
                            time.sleep(5)
                            continue
                        else:
                            raise e

        except Exception as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패: {url}, 오류: {e}")
            return None

    def create_minimal_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(service=Service(executable_path="/usr/bin/chromedriver"), options=chrome_options)
        driver.set_page_load_timeout(20)
        return driver

    def load_existing_jobs(self) -> Dict[str, Set[str]]:
        if not os.path.exists(self.results_path):
            return {}
        try:
            df = pd.read_csv(self.results_path, encoding='utf-8-sig')
            return {comp: set(df_comp['job_posting_title']) for comp, df_comp in df.groupby('회사_한글_이름')}
        except Exception as e:
            self.logger.error(f"기존 공고 로드 오류: {e}")
            return {}

    def find_new_jobs(self, current_jobs: Dict, existing_jobs: Dict) -> Dict[str, List[str]]:
        new_jobs = {comp: list(curr - existing_jobs.get(comp, set())) for comp, curr in current_jobs.items()}
        return {c: j for c, j in new_jobs.items() if j}

    def check_suspicious_results(self, current_jobs: Dict, existing_jobs: Dict, new_jobs: Dict) -> List[str]:
        warnings = []
        for company, new_list in new_jobs.items():
            if len(existing_jobs.get(company, set())) > 0 and len(new_list) == len(current_jobs.get(company, set())):
                warnings.append(f"{company}: 모든 공고가 신규입니다. 전체 채용 페이지를 확인해주세요.")
        return warnings

    def save_jobs(self, current_jobs: Dict):
        kst = pytz.timezone('Asia/Seoul')
        current_time_kst = datetime.now(kst)
        all_postings = [{'회사_한글_이름': comp, 'job_posting_title': title, 'crawl_datetime': current_time_kst.strftime('%Y-%m-%d %H:%M:%S')} for comp, titles in current_jobs.items() for title in titles]
        pd.DataFrame(all_postings).to_csv(self.results_path, index=False, encoding='utf-8-sig')
        self.logger.info(f"결과를 '{self.results_path}'에 저장했습니다.")

    def send_slack_notification(self, new_jobs: Dict, warnings: List, failed_companies: List):
        if not self.webhook_url:
            self.logger.error(f"{self.webhook_url_env}이 .env에 설정되지 않았습니다.")
            return

        if not new_jobs and not warnings and not failed_companies:
            self.logger.info("알림 보낼 내용이 없습니다.")
            return

        kst = pytz.timezone('Asia/Seoul')
        current_time = datetime.now(kst).strftime('%H:%M')
        messages_to_send = []

        if new_jobs:
            total_new_jobs = sum(len(jobs) for jobs in new_jobs.values())
            header_msg = f"🎉 *새로운 채용공고 {total_new_jobs}개 발견!* ({current_time})\n"

            current_message = header_msg
            for company, jobs in new_jobs.items():
                company_url = self.company_urls.get(company, "")
                linked_company = f"<{company_url}|{company}>" if company_url else company
                company_section = f"\n📢 *{linked_company}* - {len(jobs)}개\n"

                for job in jobs:
                    company_section += f"• {job}\n"

                if len(current_message + company_section) > 3500:
                    messages_to_send.append(current_message.strip())
                    current_message = company_section
                else:
                    current_message += company_section

            if current_message.strip():
                messages_to_send.append(current_message.strip())

        if warnings:
            warning_msg = "⚠️ *의심스러운 결과* (직접 확인 필요)\n"
            for warning in warnings:
                warning_msg += f"• {warning}\n"
            messages_to_send.append(warning_msg.strip())

        if failed_companies:
            fail_msg = "❌ *크롤링 실패*\n"
            for fail in failed_companies:
                fail_line = f"• {fail['company']}: {fail['reason']}\n"
                if len(fail_msg + fail_line) > 3500:
                    messages_to_send.append(fail_msg.strip())
                    fail_msg = f"❌ *크롤링 실패 (계속)*\n{fail_line}"
                else:
                    fail_msg += fail_line

            if fail_msg.strip() != "❌ *크롤링 실패*":
                messages_to_send.append(fail_msg.strip())

        for i, message in enumerate(messages_to_send):
            payload = {"text": message, "username": "채용공고 알리미", "icon_emoji": ":robot_face:"}
            try:
                self.logger.info(f"📤 슬랙 메시지 전송 시도 ({i+1}/{len(messages_to_send)}) - 메시지 길이: {len(message)}자")
                response = requests.post(self.webhook_url, json=payload, timeout=15)

                if response.status_code == 200:
                    self.logger.info(f"✅ 슬랙 알림 전송 완료 ({i+1}/{len(messages_to_send)})")
                else:
                    self.logger.error(f"❌ 슬랙 응답 오류 ({i+1}/{len(messages_to_send)}): {response.status_code} - {response.text}")

                import time
                time.sleep(1)

            except Exception as e:
                self.logger.error(f"❌ 슬랙 알림 전송 오류 ({i+1}/{len(messages_to_send)}): {e}")

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dag = JobMonitoringDAG(base_dir)
    dag.run()

if __name__ == "__main__":
    main()
