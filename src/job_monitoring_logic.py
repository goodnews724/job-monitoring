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
import logging
from typing import Dict, List, Set, Tuple, Optional
from dotenv import load_dotenv
from google_sheet_utils import GoogleSheetManager
from analyze_titles import JobPostingSelectorAnalyzer
from utils import stabilize_selector, SeleniumRequirementChecker

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
        self.sheet_manager = GoogleSheetManager(base_dir)
        self.selenium_checker = SeleniumRequirementChecker()
        self.selector_analyzer = JobPostingSelectorAnalyzer()

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
        self.logger.info(f"🚀 Job Monitoring DAG 시작 - {self.worksheet_name}")
        df_config = self.sheet_manager.get_all_records_as_df(self.worksheet_name)
        if df_config.empty:
            self.logger.error(f"Google Sheets에서 설정 정보를 가져오지 못했습니다: {self.worksheet_name}")
            return

        original_df_config = df_config.copy()

        df_config = self.preprocess_companies(df_config)
        df_config = self.stabilize_selectors(df_config)

        if not df_config.equals(original_df_config):
            self.logger.info("Google Sheets에 변경 사항 업데이트 중...")
            self.sheet_manager.update_sheet_from_df(df_config, self.worksheet_name)
        else:
            self.logger.info("설정 변경 사항이 없어 Google Sheets 업데이트를 건너뜁니다.")

        current_jobs, failed_companies = self.crawl_jobs(df_config)
        self.compare_and_notify(current_jobs, failed_companies)
        self.logger.info(f"✅ Job Monitoring DAG 종료 - {self.worksheet_name}")

    def preprocess_companies(self, df: pd.DataFrame) -> pd.DataFrame:
        self.logger.info("--- 1. 전처리 시작 ---")

        # 빈 회사 이름과 빈 job_posting_url을 가진 행들 필터링
        df = df[
            df['회사_한글_이름'].notna() & (df['회사_한글_이름'].str.strip() != '') &
            df['job_posting_url'].notna() & (df['job_posting_url'].str.strip() != '')
        ]
        self.logger.info(f"유효한 회사 데이터 (URL 포함): {len(df)}개")

        # 1. 먼저 모든 회사의 selenium_required 값을 자동 채우기
        self._fill_missing_selenium_required(df)

        # 2. selector가 없고 original_selector도 없으며, selenium_required가 -1이 아닌 회사들만 처리
        companies_to_process = df[
            (df['selector'].isna() | (df['selector'] == '')) &
            (df['original_selector'].isna() | (df['original_selector'] == '')) &
            (df['selenium_required'] != -1)  # HTML 저장 실패로 스킵된 회사는 제외
        ]

        if companies_to_process.empty:
            self.logger.info("새로 전처리할 회사가 없습니다.")
            return df

        self.logger.info(f"{len(companies_to_process)}개 회사에 대한 전처리를 시작합니다.")

        # 3. 다른 회사들에서 성공적으로 사용된 선택자들 수집
        existing_selectors = self._get_existing_selectors(df)
        self.logger.info(f"기존 회사들에서 사용 중인 선택자 {len(existing_selectors)}개를 우선 적용합니다.")

        driver = self.create_minimal_driver()

        for index, row in companies_to_process.iterrows():
            company_name = row['회사_한글_이름']
            url = row['job_posting_url']
            self.logger.info(f"- {company_name} 처리 중...")

            # HTML 가져오기 (메모리에서만 처리)
            html_content = self.get_html_content(url, df.loc[index, 'selenium_required'], driver)
            if html_content:
                self.logger.info(f"  - HTML 가져오기 성공")

                # 선택자 분석 - 기존 선택자 우선 시도
                soup = BeautifulSoup(html_content, 'html.parser')
                found_selector = self._try_existing_selectors(soup, existing_selectors, company_name)

                if found_selector:
                    df.loc[index, 'selector'] = found_selector
                    self.logger.info(f"  - 기존 선택자 적용 성공: {found_selector}")
                else:
                    # 기존 선택자로 안 되면 새로 분석
                    best_selector, _ = self.selector_analyzer.find_best_selector(soup)
                    if best_selector:
                        df.loc[index, 'selector'] = best_selector
                        existing_selectors.append(best_selector)  # 새 선택자를 목록에 추가
                        self.logger.info(f"  - 새로운 선택자 분석 성공: {best_selector}")
                    else:
                        self.logger.warning("  - 선택자 분석 실패")
            else:
                # HTML 가져오기 실패 시 selenium_required를 -1로 설정하여 향후 시도하지 않음
                df.loc[index, 'selenium_required'] = -1
                self.logger.error(f"  - HTML 가져오기 실패: {company_name} (selenium_required를 -1로 설정)")

        if driver:
            driver.quit()
        self.logger.info("--- 1. 전처리 종료 ---")
        return df

    def stabilize_selectors(self, df: pd.DataFrame) -> pd.DataFrame:
        self.logger.info("--- 2. 선택자 안정화 시작 ---")
        changed = False
        for index, row in df.iterrows():
            selector = row['selector']
            original_selector = row.get('original_selector', '')

            # selector가 비어있고 original_selector가 있으면 original_selector를 안정화해서 사용
            if (pd.isna(selector) or selector == '') and pd.notna(original_selector) and original_selector != '':
                stabilized = stabilize_selector(original_selector, conservative=False)
                df.loc[index, 'selector'] = stabilized
                self.logger.info(f"- {row['회사_한글_이름']} original_selector를 안정화하여 적용: {original_selector} -> {stabilized}")
                changed = True
            # selector가 있으면 기존 로직대로 안정화
            elif pd.notna(selector) and selector != '':
                stabilized = stabilize_selector(selector, conservative=True)
                if selector != stabilized:
                    df.loc[index, 'selector'] = stabilized
                    self.logger.info(f"- {row['회사_한글_이름']} 선택자 안정화: {selector} -> {stabilized}")
                    changed = True
        if not changed:
            self.logger.info("안정화할 선택자가 없습니다.")
        self.logger.info("--- 2. 선택자 안정화 종료 ---")
        return df


    def _get_existing_selectors(self, df: pd.DataFrame) -> List[str]:
        """기존에 성공적으로 사용된 선택자들을 수집합니다."""
        existing_selectors = []

        # 1. 현재 DataFrame에서 유효한 선택자들 수집
        valid_selectors = df[df['selector'].notna() & (df['selector'] != '')]['selector'].unique()
        existing_selectors.extend(valid_selectors)

        # 2. 각 선택자의 원본과 안정화된 버전 둘 다 추가
        expanded_selectors = []
        for selector in valid_selectors:
            expanded_selectors.append(selector)  # 원본
            stabilized = stabilize_selector(selector, conservative=False)  # 안정화된 버전
            if stabilized != selector and stabilized:
                expanded_selectors.append(stabilized)

        # 3. 알려진 성공 선택자들 추가 (정답 기반) - 구체적인 것들만
        known_good_selectors = [
            "a div.sc-9b56f69e-0.jlntFl",  # greetinghr 계열
            "div.JobPostingsJobPosting__Layout-sc-6ae888f2-0.ffnSOB div.JobPostingsJobPosting__Bottom-sc-6ae888f2-5.iXrIoX",  # ninehire 계열
            "#jobList > div.jobList_info > div > a > span.title",  # 트리노드 스타일
            "div.RecruitList_left__5MzDR div.RecruitList_title-wrapper__Gvh1r p",  # recruiter.co.kr 계열
            "div.swiper-slide button p",  # 슬라이더 내부 버튼
            "button div p",  # 버튼 내부 텍스트
            "li.job-item a",  # 구체적인 리스트 링크
            "td.job-title a",  # 구체적인 테이블 셀
            ".job-list li a",  # 채용 목록 링크
            ".career-item .title",  # 채용 아이템 제목
        ]
        expanded_selectors.extend(known_good_selectors)

        # 4. 선택자 사용 빈도순으로 정렬 (많이 사용된 선택자부터 시도)
        selector_counts = df[df['selector'].notna() & (df['selector'] != '')]['selector'].value_counts()
        sorted_selectors = selector_counts.index.tolist()

        # 5. 최종 리스트: 빈도순 선택자 + 확장된 선택자들
        final_selectors = sorted_selectors + [s for s in expanded_selectors if s not in sorted_selectors]

        self.logger.info(f"수집된 선택자 {len(final_selectors)}개 (기존: {len(sorted_selectors)}개, 확장: {len(expanded_selectors)}개)")
        return final_selectors

    def _is_specific_enough_selector(self, selector: str) -> bool:
        """선택자가 충분히 구체적인지 판단합니다."""
        selector = selector.strip()
        if not selector:
            return False

        # 공백으로 분리된 선택자 부분들
        parts = selector.split()

        # 1. 단일 태그명만 있는 경우는 비구체적
        if len(parts) == 1:
            part = parts[0].lower()
            # 클래스나 ID가 있으면 구체적
            if '.' in part or '#' in part:
                return True
            # 속성 선택자가 있는지 체크
            if '[' in part and ']' in part:
                # 하지만 단순히 a[href] 같은 너무 일반적인 것은 제외
                # 속성값이 구체적인지 체크 (예: a[class="job-link"])
                if part == 'a[href]' or part.endswith('[href]'):
                    return False
                return True
            # 가상 선택자가 있으면 구체적
            if ':' in part:
                return True
            # 단순 태그명만 있으면 비구체적
            return False

        # 2. 여러 레벨의 선택자는 구체적 (최소 2레벨 이상)
        if len(parts) >= 2:
            return True

        return False

    def _try_existing_selectors(self, soup: BeautifulSoup, existing_selectors: List[str], _: str) -> Optional[str]:
        """기존 선택자들을 순서대로 시도해서 유효한 것을 찾습니다."""
        for i, selector in enumerate(existing_selectors):
            # 너무 일반적인 선택자는 건너뛰기
            if not self._is_specific_enough_selector(selector):
                continue

            try:
                elements = soup.select(selector)
                if not elements:
                    continue

                # 선택자로 찾은 요소들의 텍스트 추출
                titles = [elem.get_text(strip=True) for elem in elements]
                valid_titles = [title for title in titles if title and len(title) > 3]

                # 기본 검증: 최소 1개 이상의 유효한 텍스트
                if len(valid_titles) >= 1:
                    # 채용공고 관련성 검사
                    job_related_titles = [title for title in valid_titles
                                        if self.selector_analyzer._is_potential_job_posting(title)]

                    # 더 엄격한 검증: 적어도 1개 이상의 채용공고가 있어야 함
                    if len(job_related_titles) >= 1:
                        # 품질 점수 계산: 채용공고 비율이 높을수록 좋음
                        quality_score = len(job_related_titles) / len(valid_titles)

                        # 너무 많은 결과를 가져오는 선택자는 일반적일 가능성이 높음
                        if len(valid_titles) > 50:
                            # 50개 이상이면 품질이 80% 이상이어야 함
                            if quality_score < 0.8:
                                continue
                        elif len(valid_titles) > 20:
                            # 20개 이상이면 품질이 60% 이상이어야 함
                            if quality_score < 0.6:
                                continue
                        elif len(valid_titles) > 5:
                            # 5개 이상이면 품질이 40% 이상이어야 함
                            if quality_score < 0.4:
                                continue
                        # 5개 이하면 적어도 1개 이상의 채용공고만 있으면 됨

                        # 로그에서 어떤 카테고리의 선택자인지 표시
                        category = "기존" if i < 10 else "확장" if i < 50 else "패턴"
                        self.logger.info(f"  - {category} 선택자 '{selector}' 검증 성공 (채용공고: {len(job_related_titles)}개/{len(valid_titles)}개, 품질: {quality_score:.1%})")
                        if len(valid_titles) <= 5:  # 적은 수일 때만 샘플 출력
                            for title in valid_titles[:3]:
                                self.logger.info(f"    예시: {title[:50]}...")
                        return selector

            except Exception:
                # 선택자 문법 오류 등은 무시하고 다음 선택자 시도
                continue

        return None

    def _fill_missing_selenium_required(self, df: pd.DataFrame) -> None:
        """selenium_required 값이 없는 회사들을 자동으로 채웁니다."""
        # NaN, 빈 문자열, 또는 0/1/-1이 아닌 값들을 모두 체크
        missing_selenium = df[
            df['selenium_required'].isna() |
            (df['selenium_required'] == '') |
            (~df['selenium_required'].isin([0, 1, -1]))
        ]
        
        if missing_selenium.empty:
            self.logger.info("모든 회사의 selenium_required 값이 설정되어 있습니다.")
            return
            
        self.logger.info(f"{len(missing_selenium)}개 회사의 selenium_required 값을 자동 설정 중...")
        
        # 자동 판단 규칙
        for index, row in missing_selenium.iterrows():
            company_name = row['회사_한글_이름']
            url = row['job_posting_url']
            
            selenium_required = self._determine_selenium_requirement(url, company_name)
            df.loc[index, 'selenium_required'] = selenium_required
            
            selenium_text = "Selenium 필요" if selenium_required else "requests 사용"
            self.logger.info(f"  - {company_name}: {selenium_text}")
    
    def _determine_selenium_requirement(self, url: str, _: str) -> int:
        """URL을 기반으로 Selenium 필요 여부를 동적으로 판단합니다."""
        
        # 모든 사이트에 대해 실제로 체크해서 판단
        try:
            selenium_req = self.selenium_checker.check_selenium_requirement(url)
            return int(selenium_req)
        except Exception:
            # 체크 실패 시 안전하게 Selenium 사용
            return 1

    def crawl_jobs(self, df_config: pd.DataFrame) -> Tuple[Dict[str, Set[str]], List[Dict]]:
        self.logger.info("--- 3. 채용 공고 크롤링 시작 ---")
        df_crawl = df_config[
            (df_config['selector'].notna() & (df_config['selector'] != '')) &
            (df_config['selenium_required'] != -1)  # HTML 저장 실패로 스킵된 회사는 제외
        ].copy()
        if df_crawl.empty:
            self.logger.warning("크롤링할 회사가 없습니다.")
            return {}, []
        driver = self.create_minimal_driver() if df_crawl['selenium_required'].any() else None
        current_jobs = {}
        failed_companies = []

        for _, row in df_crawl.iterrows():
            company_name, url, use_selenium, selector = row['회사_한글_이름'], row['job_posting_url'], row['selenium_required'], row['selector']
            self.company_urls[company_name] = url
            self.logger.info(f"- {company_name} 크롤링 중...")
            html_content = self.get_html_content_for_crawling(url, use_selenium, driver, selector)
            if not html_content:
                failed_companies.append({'company': company_name, 'reason': 'HTML 가져오기 실패', 'url': url})
                continue
            try:
                soup = BeautifulSoup(html_content, 'html.parser')
                postings = soup.select(selector)
                if not postings:
                    failed_companies.append({'company': company_name, 'reason': f'선택자 \'{selector}\'로 공고를 찾지 못함', 'url': url})
                    continue
                job_titles = {post.get_text(strip=True) for post in postings 
                             if post.get_text(strip=True).strip()}  # 빈 텍스트만 제외
                if job_titles:
                    current_jobs[company_name] = job_titles
                    self.logger.info(f"  - 성공: {len(job_titles)}개 공고 추출")
                else:
                    failed_companies.append({'company': company_name, 'reason': '유효한 공고를 찾지 못함', 'url': url})
            except Exception as e:
                failed_companies.append({'company': company_name, 'reason': f'HTML 파싱 실패: {e}', 'url': url})

        if driver:
            driver.quit()
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
        try:
            if not use_selenium:
                response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
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
                        # 1. 선택자가 나타날 때까지 최대 7초 대기
                        WebDriverWait(driver, 7).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        # 2. 데이터 로드를 위해 1.5초 추가 대기
                        time.sleep(1.5)
                    except Exception:
                        # 대기 실패 시, 경고만 남기고 HTML을 바로 가져옴
                        self.logger.warning(f"''{selector}'' 요소를 기다리는 데 실패했습니다.")
                else:
                    # 선택자가 없으면 2초 기본 대기
                    time.sleep(2)

                return driver.page_source
        except Exception as e:
            self.logger.error(f"HTML 가져오기 실패: {url}, 오류: {e}")
            return None

    def get_html_content_for_crawling(self, url, use_selenium, driver=None, selector=None):
        """실제 크롤링용 HTML 가져오기 메서드 (selenium_required 값에 따라 분기)"""
        try:
            if not use_selenium:
                # requests 사용
                response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                response.raise_for_status()
                return response.text
            else:
                # selenium 사용
                if driver is None:
                    raise Exception("Selenium Driver가 없습니다.")

                # 타임아웃 오류 처리를 위한 재시도 로직
                max_retries = 2
                for attempt in range(max_retries):
                    try:
                        driver.get(url)

                        if selector:
                            from selenium.webdriver.common.by import By
                            from selenium.webdriver.support.ui import WebDriverWait
                            from selenium.webdriver.support import expected_conditions as EC
                            try:
                                # 선택자가 나타날 때까지 최대 15초 대기 (10초 → 15초)
                                WebDriverWait(driver, 15).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                                )
                                # 데이터 로드를 위해 3초 추가 대기 (2초 → 3초)
                                time.sleep(3)
                            except Exception:
                                # 대기 실패 시, 경고만 남기고 HTML을 바로 가져옴
                                self.logger.warning(f"선택자 '{selector}' 요소를 기다리는 데 실패했습니다.")
                        else:
                            # 선택자가 없으면 5초 기본 대기 (3초 → 5초)
                            time.sleep(5)

                        return driver.page_source

                    except Exception as e:
                        if "timeout" in str(e).lower() and attempt < max_retries - 1:
                            self.logger.warning(f"페이지 로드 타임아웃 ({attempt + 1}/{max_retries}): {url} - 재시도 중...")
                            time.sleep(2)  # 재시도 전 대기
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
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        driver.set_page_load_timeout(15)
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
        all_postings = [{'회사_한글_이름': comp, 'job_posting_title': title, 'crawl_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S')} for comp, titles in current_jobs.items() for title in titles]
        pd.DataFrame(all_postings).to_csv(self.results_path, index=False, encoding='utf-8-sig')
        self.logger.info(f"결과를 '{self.results_path}'에 저장했습니다.")

    def send_slack_notification(self, new_jobs: Dict, warnings: List, failed_companies: List):
        if not self.webhook_url:
            self.logger.error(f"{self.webhook_url_env}이 .env에 설정되지 않았습니다.")
            return

        if not new_jobs and not warnings and not failed_companies:
            self.logger.info("알림 보낼 내용이 없습니다.")
            return

        current_time = datetime.now().strftime('%H:%M')
        messages_to_send = []

        # 1. 새로운 채용공고 메시지들 생성
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

                # 메시지가 3500자를 초과하면 분할
                if len(current_message + company_section) > 3500:
                    messages_to_send.append(current_message.strip())
                    current_message = company_section
                else:
                    current_message += company_section

            if current_message.strip():
                messages_to_send.append(current_message.strip())

        # 2. 경고 메시지
        if warnings:
            warning_msg = "⚠️ *의심스러운 결과* (직접 확인 필요)\n"
            for warning in warnings:
                warning_msg += f"• {warning}\n"
            messages_to_send.append(warning_msg.strip())

        # 3. 실패 메시지
        if failed_companies:
            fail_msg = "❌ *크롤링 실패*\n"
            for fail in failed_companies:
                fail_line = f"• {fail['company']}: {fail['reason']}\n"
                # 실패 메시지가 너무 길어지면 분할
                if len(fail_msg + fail_line) > 3500:
                    messages_to_send.append(fail_msg.strip())
                    fail_msg = f"❌ *크롤링 실패 (계속)*\n{fail_line}"
                else:
                    fail_msg += fail_line

            if fail_msg.strip() != "❌ *크롤링 실패*":
                messages_to_send.append(fail_msg.strip())

        # 메시지들 전송
        for i, message in enumerate(messages_to_send):
            payload = {"text": message, "username": "채용공고 알리미", "icon_emoji": ":robot_face:"}
            try:
                self.logger.info(f"📤 슬랙 메시지 전송 시도 ({i+1}/{len(messages_to_send)}) - 메시지 길이: {len(message)}자")
                response = requests.post(self.webhook_url, json=payload, timeout=15)

                if response.status_code == 200:
                    self.logger.info(f"✅ 슬랙 알림 전송 완료 ({i+1}/{len(messages_to_send)})")
                else:
                    self.logger.error(f"❌ 슬랙 응답 오류 ({i+1}/{len(messages_to_send)}): {response.status_code} - {response.text}")

                # 슬랙 레이트 리밋 방지를 위한 짧은 대기
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