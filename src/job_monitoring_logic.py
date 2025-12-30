import os
import time
import gc
import pandas as pd
import requests
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from datetime import datetime
import pytz
import logging
from typing import Dict, List, Set, Tuple, Optional
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from google_sheet_utils import GoogleSheetManager
from analyze_titles import JobPostingSelectorAnalyzer
from utils import stabilize_selector, SeleniumRequirementChecker

load_dotenv()

class JobMonitoringDAG:
    def __init__(self, base_dir: str, worksheet_name: str = '[등록]채용홈페이지 모음', webhook_url_env: str = 'SLACK_WEBHOOK_URL', results_filename: str = 'job_postings_latest.csv', limit: Optional[int] = None):
        self.base_dir = base_dir
        self.data_dir = os.path.join(base_dir, 'data')
        self.worksheet_name = worksheet_name
        self.webhook_url_env = webhook_url_env  # 환경변수 이름 저장
        self.results_path = os.path.join(self.data_dir, results_filename)
        self.webhook_url = os.getenv(webhook_url_env)
        self.limit = limit
        self.company_urls = {}
        self.foreign_keywords = []  # 외국인 채용공고 키워드
        self.url_groups_for_notification = {}  # URL 그룹 정보 (슬랙 알림용)
        self.url_crawling_cache = {}  # URL별 크롤링 결과 캐시 {url: job_titles}

        # requests 세션 설정 (쿠키 및 연결 유지)
        self.session = requests.Session()
        self._setup_session()
        self._setup_logging()

    def _setup_session(self):
        """HTTP 세션 설정 (더 현실적인 브라우저 모방)"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }
        self.session.headers.update(headers)

        # HTTP 어댑터 설정 (연결 풀링, 재시도 등)
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

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

        if self.limit:
            self.logger.info(f"테스트 목적으로 {self.limit}개 기업만 처리합니다.")
            df_config = df_config.head(self.limit)

        # 키워드 필터링이 필요한 시트 목록
        keyword_sheets = ['5000대_기업', '[등록]채용홈페이지 모음']
        if self.worksheet_name in keyword_sheets:
            # 외국인 채용공고 키워드 로드
            self.foreign_keywords = self._load_foreign_keywords()

        if self.worksheet_name == '5000대_기업':
            # 1. 먼저 original_selector를 selector로 안정화
            self.logger.info("original_selector를 selector로 안정화 중...")
            df_config = self.stabilize_selectors(df_config)

            # 2. 안정화된 데이터로 처리 대상 필터링
            df_to_process = df_config[df_config['job_posting_url'].notna() & (df_config['job_posting_url'].str.strip() != '')].copy()

            chunk_size = 100
            num_chunks = (len(df_to_process) - 1) // chunk_size + 1
            self.logger.info(f"'{self.worksheet_name}' 시트의 {len(df_to_process)}개 기업을 {num_chunks}개 청크로 분할하여 처리합니다.")

            is_first_chunk = True
            list_of_df_chunks = [df_to_process.iloc[i:i+chunk_size] for i in range(0, len(df_to_process), chunk_size)]

            for i, df_chunk in enumerate(list_of_df_chunks):
                start_num = i * chunk_size + 1
                end_num = start_num + len(df_chunk) - 1
                chunk_info = f"{start_num}-{end_num}번째 기업"
                self.logger.info(f"--- 청크 처리 시작: {chunk_info} ({len(df_chunk)}개 기업) ---")

                # 1. 각 청크별로 통합 처리 (전처리 + 크롤링)
                df_chunk_processed, current_jobs_chunk, failed_companies_chunk = self.process_companies_with_cache(df_chunk.copy())

                # 2. DataFrame에 선택자 업데이트
                for idx in df_chunk_processed.index:
                    if 'selector' in df_chunk_processed.columns and idx in df_config.index:
                        new_selector = df_chunk_processed.loc[idx, 'selector']
                        if pd.notna(new_selector) and str(new_selector).strip():
                            df_config.loc[idx, 'selector'] = new_selector
                
                # 3. 청크별 결과 비교
                new_jobs_chunk, warnings_chunk, failed_companies_for_notify = self.compare_and_notify(
                    current_jobs_chunk,
                    failed_companies_chunk,
                    save=False,
                    send_notifications=False
                )

                # 4. 청크별 슬랙 알림 전송
                if new_jobs_chunk or warnings_chunk or failed_companies_for_notify:
                    self.logger.info(f"📤 청크 {i+1}/{num_chunks}에 대한 슬랙 알림 전송 중...")
                    self.send_slack_notification(
                        new_jobs_chunk,
                        warnings_chunk,
                        failed_companies_for_notify,
                        chunk_info=chunk_info
                    )
                else:
                    self.logger.info(f"✅ 청크 {i+1}/{num_chunks}에 새로운 내용이 없어 알림을 건너뜁니다.")

                # 5. 청크별 결과 파일에 증분 저장
                if current_jobs_chunk:
                    self.save_jobs_incrementally(current_jobs_chunk, append=not is_first_chunk)
                    if is_first_chunk:
                        is_first_chunk = False

                # 6. 구글 시트 선택자 업데이트 (테스트 모드에서는 건너뜀)
                if self.limit:
                    self.logger.info(f"⚠️ 테스트 모드 - 청크 {i+1}/{num_chunks} 선택자 업데이트 건너뜀")
                else:
                    self.logger.info(f"청크 {i+1}/{num_chunks} 선택자 업데이트 중...")
                    try:
                        self.sheet_manager.update_selector_column_only(df_config, self.worksheet_name)
                        self.logger.info(f"✅ 청크 {i+1}/{num_chunks} 선택자 업데이트 완료")
                    except Exception as e:
                        self.logger.error(f"❌ 청크 {i+1} 선택자 업데이트 실패: {e}")

                self.logger.info(f"--- 청크 처리 종료: {chunk_info} ---")

                # 청크 처리 후 메모리 정리
                gc.collect()
                self.logger.info("🧹 메모리 정리 완료 (gc.collect)")

                if i < num_chunks - 1:
                    self.logger.info(f"다음 청크 처리를 위해 30초간 대기합니다.")
                    time.sleep(30)

            self.logger.info("모든 청크 처리 완료.")
            if self.limit:
                self.logger.info("⚠️ 테스트 모드 - 시트 전체 업데이트를 건너뜁니다 (데이터 손실 방지)")
            else:
                self.logger.info("최종 시트 업데이트 중...")
                try:
                    self.sheet_manager.update_sheet_from_df(df_config, self.worksheet_name)
                    self.logger.info("✅ 최종 시트 업데이트 완료")
                except Exception as e:
                    self.logger.error(f"❌ 최종 시트 업데이트 실패: {e}")

        else:
            original_df_config = df_config.copy()

            self.logger.info("--- 통합 처리 시작 (전처리 + 크롤링) ---")
            df_processed, current_jobs, failed_companies = self.process_companies_integrated(df_config)

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

            self.logger.info(f"🔍 간단한 실행 모드 - 슬랙 알림 체크:")
            self.logger.info(f"  - current_jobs: {len(current_jobs)}개 회사")
            self.logger.info(f"  - failed_companies: {len(failed_companies)}개")

            new_jobs, warnings, failed_companies_result = self.compare_and_notify(current_jobs, failed_companies)

            self.logger.info(f"🔍 compare_and_notify 결과:")
            self.logger.info(f"  - new_jobs: {len(new_jobs)}개 회사")
            self.logger.info(f"  - warnings: {len(warnings)}개")
            self.logger.info(f"  - failed_companies_result: {len(failed_companies_result)}개")

            if new_jobs or warnings or failed_companies_result:
                self.logger.info("📤 간단한 모드 - 슬랙 알림 전송 중...")
                self.send_slack_notification(new_jobs, warnings, failed_companies_result, chunk_info="간단한 실행")
            else:
                self.logger.warning("⚠️ 간단한 모드 - 슬랙 알림 전송 조건 불만족")

        self.logger.info(f"✅ Job Monitoring DAG 종료 - {self.worksheet_name}")

    def _analyze_global_url_groups(self, df: pd.DataFrame) -> Dict[str, List[str]]:
        """전체 데이터에서 URL별 회사 그룹을 미리 분석합니다."""
        url_groups = {}

        for idx, row in df.iterrows():
            url = row['job_posting_url'].strip()
            company_name = row['회사_한글_이름']

            if url not in url_groups:
                url_groups[url] = []
            url_groups[url].append(company_name)

        # 중복 URL만 필터링
        shared_url_groups = {url: companies for url, companies in url_groups.items() if len(companies) > 1}

        if shared_url_groups:
            self.logger.info(f"🔍 전체 URL 분석 완료: {len(shared_url_groups)}개 공유 URL 발견")
            for url, companies in shared_url_groups.items():
                self.logger.info(f"  - {url[:50]}... → {companies}")

        return shared_url_groups

    def _prepare_global_url_groups_for_notification(self, current_jobs: Dict) -> Dict[str, List[str]]:
        """전체 처리 결과를 바탕으로 URL 그룹을 준비합니다."""
        if not hasattr(self, 'global_url_groups'):
            return {}

        notification_groups = {}
        for url, all_companies in self.global_url_groups.items():
            # 실제 새로운 공고가 있는 회사들만 필터링
            companies_with_jobs = [c for c in all_companies if c in current_jobs]
            if len(companies_with_jobs) > 1:
                notification_groups[url] = companies_with_jobs

        if notification_groups:
            self.logger.info(f"🎯 전체 결과 URL 그룹화: {len(notification_groups)}개 URL")
            for url, companies in notification_groups.items():
                self.logger.info(f"  - {url[:50]}... → {companies}")

        return notification_groups

    def process_companies_with_cache(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict, List]:
        """캐시를 활용한 통합 처리 (Playwright 브라우저 재사용 최적화)"""
        self.logger.info(f"캐시 활용 통합 처리 대상: {len(df)}개 회사")

        # 기본 전처리
        valid_companies_mask = (
            df['회사_한글_이름'].notna() & (df['회사_한글_이름'].str.strip() != '') &
            df['job_posting_url'].notna() & (df['job_posting_url'].str.strip() != '')
        )

        if valid_companies_mask.any():
            self._fill_missing_selenium_required(df, valid_companies_mask)

        companies_to_process = df[
            valid_companies_mask &
            (~df['selenium_required'].isin([-1, -2]))
        ]

        if companies_to_process.empty:
            self.logger.info("처리할 회사가 없습니다.")
            return df, {}, []

        current_jobs = {}
        failed_companies = []
        cache_hits = 0
        cache_misses = 0

        # URL별로 그룹화
        url_company_map = {}
        for idx, row in companies_to_process.iterrows():
            url = row['job_posting_url'].strip()
            company_name = row['회사_한글_이름']

            if url not in url_company_map:
                url_company_map[url] = []
            url_company_map[url].append((idx, company_name))

        # Playwright 브라우저 한 번만 생성 (재사용)
        playwright, browser, context = None, None, None
        try:
            playwright, browser, context = self.create_playwright_browser()
            if playwright and browser and context:
                self.logger.info("Playwright 브라우저 생성 완료 - 전체 크롤링에 재사용합니다")

            # URL별 처리 (캐시 활용)
            for url, company_list in url_company_map.items():
                if url in self.url_crawling_cache:
                    # 캐시 히트
                    cache_hits += len(company_list)
                    job_titles = self.url_crawling_cache[url]

                    for idx, company_name in company_list:
                        current_jobs[company_name] = job_titles
                        self.company_urls[company_name] = url

                    self.logger.info(f"  캐시 사용: {url[:50]}... -> {len(company_list)}개 회사 ({len(job_titles)}개 공고)")
                else:
                    # 캐시 미스 - 크롤링 수행
                    cache_misses += len(company_list)
                    representative_idx, representative_company = company_list[0]
                    representative_row = companies_to_process.loc[representative_idx]

                    self.logger.info(f"  크롤링: {url[:50]}... -> {len(company_list)}개 회사")

                    # 실제 크롤링 (컨텍스트 재사용)
                    result = self._crawl_single_url_with_browser(url, representative_row, context)

                    if result is not None:
                        idx, found_selector, job_titles, error = result

                        if error is None and job_titles is not None:
                            # 캐시에 저장
                            self.url_crawling_cache[url] = job_titles

                            # 찾은 선택자를 DataFrame에 저장
                            if found_selector:
                                for company_idx, company_name in company_list:
                                    if company_idx in df.index:
                                        old_selector = df.loc[company_idx, 'selector']
                                        if pd.isna(old_selector) or str(old_selector).strip() == '':
                                            df.loc[company_idx, 'selector'] = found_selector
                                            self.logger.info(f"새 선택자 저장: {company_name} = '{found_selector}'")

                            # 모든 관련 회사에 결과 적용
                            for idx, company_name in company_list:
                                current_jobs[company_name] = job_titles
                                self.company_urls[company_name] = url
                        else:
                            # 크롤링 실패 처리
                            if error:
                                failed_companies.append(error)
                    else:
                        # 크롤링 실패
                        for idx, company_name in company_list:
                            failed_companies.append({
                                'company': company_name,
                                'reason': 'HTML 가져오기 실패',
                                'url': url
                            })

        finally:
            # 모든 크롤링 완료 후 브라우저 종료
            if context:
                try:
                    context.close()
                except Exception as e:
                    self.logger.warning(f"컨텍스트 종료 중 오류: {e}")
            if browser:
                try:
                    browser.close()
                    self.logger.info("Playwright 브라우저 종료 완료")
                except Exception as e:
                    self.logger.warning(f"브라우저 종료 중 오류: {e}")
            if playwright:
                try:
                    playwright.stop()
                except Exception as e:
                    self.logger.warning(f"Playwright 중지 중 오류: {e}")

        self.logger.info(f"성능 개선 효과: 캐시 히트 {cache_hits}개, 새 크롤링 {len(url_company_map)}개 URL")
        if cache_hits > 0:
            total_requests = cache_hits + len(url_company_map)
            saved_percentage = (cache_hits / total_requests) * 100
            self.logger.info(f"   절약된 크롤링: {cache_hits}회 ({saved_percentage:.1f}%)")

        return df, current_jobs, failed_companies

    def _crawl_single_url_with_browser(self, url: str, representative_row: pd.Series, context=None) -> Optional[tuple]:
        """단일 URL 크롤링 (선택자 찾기 포함, 컨텍스트 재사용 버전)"""
        company_name = representative_row['회사_한글_이름']
        use_selenium = representative_row['selenium_required']
        selector = representative_row.get('selector', '')
        index = representative_row.name

        self.logger.info(f"  - {company_name} 기존 선택자 확인: '{selector}' (타입: {type(selector)})")

        # ⭐ 스레드 기반 강제 타임아웃 (JavaScript 무한 루프 방지)
        # toss.im은 3분, 나머지는 2분
        hard_timeout = 180 if 'toss.im' in url else 120

        html_content = None
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self.get_html_content_for_crawling_with_browser,
                    url, use_selenium, context, selector
                )
                html_content = future.result(timeout=hard_timeout)
        except FuturesTimeoutError:
            self.logger.error(f"  - {company_name} 강제 타임아웃 ({hard_timeout}초) - JavaScript 무한 루프 의심")
            return index, None, None, {'company': company_name, 'reason': f'강제 타임아웃 ({hard_timeout}초)', 'url': url}
        except Exception as e:
            self.logger.error(f"  - {company_name} 크롤링 중 오류: {e}")
            return index, None, None, {'company': company_name, 'reason': f'크롤링 오류: {e}', 'url': url}

        if not html_content:
            return None

        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            found_selector = None

            if not selector or selector.strip() == '':
                self.logger.info(f"  - {company_name} 선택자 찾기 중...")

                found_selector = self._try_existing_selectors(soup, [], company_name)

                if found_selector:
                    selector = found_selector
                    self.logger.info(f"  - 기존 선택자 적용 성공: {selector}")
                else:
                    best_selector, _ = self.selector_analyzer.find_best_selector(soup)
                    if best_selector:
                        selector = best_selector
                        found_selector = best_selector
                        self.logger.info(f"  - 새 선택자 찾기 성공: {selector}")
                    else:
                        self.logger.warning(f"  - {company_name} 선택자 찾기 실패")
                        return index, None, [], {'company': company_name, 'reason': '선택자를 찾을 수 없음', 'url': url}
            else:
                self.logger.info(f"  - 기존 선택자 사용: {selector}")

            postings = soup.select(selector)
            if not postings:
                return index, selector, None, {'company': company_name, 'reason': f'선택자 \'{selector}\'로 공고를 찾지 못함', 'url': url}

            all_texts = [post.get_text(strip=True) for post in postings if post.get_text(strip=True).strip()]
            job_titles = {text for text in all_texts if self.selector_analyzer._is_potential_job_posting(text)}

            if job_titles:
                self.logger.info(f"  - 성공: {len(job_titles)}개 공고 수집")
                return index, found_selector, job_titles, None
            else:
                return index, selector, None, {'company': company_name, 'reason': '유효한 공고를 찾지 못함', 'url': url}

        except Exception as e:
            self.logger.error(f"  - {company_name} 처리 중 오류 발생: {e}")
            return index, None, None, {'company': company_name, 'reason': f'처리 중 오류: {e}', 'url': url}

    def _crawl_single_url(self, url: str, representative_row: pd.Series) -> Optional[tuple]:
        """단일 URL 크롤링 (선택자 찾기 포함)"""
        company_name = representative_row['회사_한글_이름']
        use_selenium = representative_row['selenium_required']
        # stabilize_selectors에서 이미 original_selector -> selector 변환됨
        selector = representative_row.get('selector', '')
        index = representative_row.name  # DataFrame의 인덱스

        # 디버깅: 선택자 값 확인
        self.logger.info(f"  - {company_name} 기존 선택자 확인: '{selector}' (타입: {type(selector)})")

        html_content = self.get_html_content_for_crawling(url, use_selenium)
        if not html_content:
            return None

        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            found_selector = None

            # 선택자가 없거나 빈 경우 새로 찾기
            if not selector or selector.strip() == '':
                self.logger.info(f"  - {company_name} 선택자 찾기 중...")

                # 기존 선택자들 활용 시도
                found_selector = self._try_existing_selectors(soup, [], company_name)

                if found_selector:
                    selector = found_selector
                    self.logger.info(f"  - 기존 선택자 적용 성공: {selector}")
                else:
                    # 새 선택자 찾기
                    best_selector, _ = self.selector_analyzer.find_best_selector(soup)
                    if best_selector:
                        selector = best_selector
                        found_selector = best_selector
                        self.logger.info(f"  - 새 선택자 찾기 성공: {selector}")
                    else:
                        self.logger.warning(f"  - {company_name} 선택자 찾기 실패")
                        return index, None, [], {'company': company_name, 'reason': '선택자를 찾을 수 없음', 'url': url}
            else:
                self.logger.info(f"  - 기존 선택자 사용: {selector}")

            postings = soup.select(selector)
            if not postings:
                return index, found_selector, [], {'company': company_name, 'reason': f'선택자 \'{selector}\'로 공고를 찾지 못함', 'url': url}

            job_titles = [elem.get_text(strip=True) for elem in postings if elem.get_text(strip=True)]
            job_titles = [title for title in job_titles if len(title) > 2 and len(title) < 200]
            job_titles = list(set(job_titles))  # 중복 제거

            if job_titles:
                self.logger.info(f"  - 성공: {len(job_titles)}개 공고 수집")
                return index, found_selector, job_titles, None
            else:
                return index, found_selector, [], {'company': company_name, 'reason': '유효한 공고를 찾지 못함', 'url': url}

        except Exception as e:
            self.logger.error(f"  - {company_name} 크롤링 오류: {e}")
            return index, None, [], {'company': company_name, 'reason': f'처리 중 오류: {e}', 'url': url}

    def _load_foreign_keywords(self):
        """외국인_공고_키워드 시트에서 키워드들을 로드합니다."""
        try:
            df_keywords = self.sheet_manager.get_all_records_as_df('외국인_공고_키워드')
            if df_keywords.empty:
                self.logger.info("외국인 키워드 시트가 비어있거나 찾을 수 없습니다.")
                return []

            keywords = []
            # B열부터 모든 열의 값들을 수집
            for col in df_keywords.columns[1:]:  # A열(인덱스) 제외
                col_keywords = df_keywords[col].dropna().tolist()
                keywords.extend([str(k).strip() for k in col_keywords if str(k).strip()])

            # 중복 제거 및 빈 값 제거
            keywords = list(set([k for k in keywords if k and k != 'nan']))
            self.logger.info(f"외국인 채용 키워드 {len(keywords)}개 로드 완료: {keywords[:5]}..." if len(keywords) > 5 else f"외국인 채용 키워드 로드: {keywords}")
            return keywords

        except Exception as e:
            self.logger.error(f"외국인 키워드 로드 실패: {e}")
            return []

    def _is_foreign_job_posting(self, job_title: str) -> bool:
        """채용공고 제목에 외국인 키워드가 포함되는지 확인합니다."""
        if not self.foreign_keywords:
            return False

        job_title_lower = job_title.lower()
        for keyword in self.foreign_keywords:
            if keyword.lower() in job_title_lower:
                return True
        return False

    def _clean_job_title(self, job_title: str) -> str:
        """공고 제목에서 불필요한 패턴들을 제거합니다."""
        if not job_title:
            return job_title

        # D-1, D-2 같은 마감일 패턴 제거 (더 광범위한 패턴)
        job_title = re.sub(r'D-\d+', '', job_title, flags=re.IGNORECASE)
        job_title = re.sub(r'D-DAY', '', job_title, flags=re.IGNORECASE)
        job_title = re.sub(r'\bD\d+', '', job_title, flags=re.IGNORECASE)  # D2, D12 같은 패턴
        job_title = re.sub(r'마감\s*D-\d+', '', job_title, flags=re.IGNORECASE)

        # 날짜시간 패턴 제거 (예: 2024.12.31 23:59)
        job_title = re.sub(r'\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2}', '', job_title)
        job_title = re.sub(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}', '', job_title)

        # 여러 공백을 하나로 정리하고 앞뒤 공백 제거
        job_title = re.sub(r'\s+', ' ', job_title).strip()

        return job_title

    def _highlight_foreign_keywords(self, job_title: str) -> Tuple[str, bool]:
        """채용공고 제목에서 외국인 키워드를 볼드처리하고, 외국인 공고인지 여부를 반환합니다."""
        if not self.foreign_keywords:
            return job_title, False

        is_foreign = False

        # 1단계: 이미 *로 둘러싸인 부분 찾기 (이 부분은 보호)
        markdown_ranges = []
        for match in re.finditer(r'\*[^*]+\*', job_title):
            markdown_ranges.append((match.start(), match.end()))

        # 2단계: 키워드 찾기 (보호된 영역 제외)
        matches = []
        for keyword in self.foreign_keywords:
            try:
                for match in re.finditer(re.escape(keyword), job_title, re.IGNORECASE):
                    start, end = match.start(), match.end()

                    # 이미 마크다운으로 처리된 영역과 겹치는지 확인
                    overlap = False
                    for md_start, md_end in markdown_ranges:
                        if not (end <= md_start or start >= md_end):
                            overlap = True
                            break

                    if not overlap:
                        matches.append((start, end))
                        is_foreign = True
            except re.error as e:
                self.logger.warning(f"정규식 오류: 키워드 '{keyword}' 처리 중 오류 발생 - {e}")
                continue

        if not is_foreign:
            return job_title, False

        # 3단계: 매칭된 위치들을 병합하여 중첩 제거
        if not matches:
            return job_title, is_foreign

        matches.sort()
        merged = [matches[0]]
        for current_start, current_end in matches[1:]:
            last_start, last_end = merged[-1]
            if current_start <= last_end:
                # 중첩되거나 연속된 경우, 병합
                merged[-1] = (last_start, max(last_end, current_end))
            else:
                merged.append((current_start, current_end))

        # 4단계: 볼드 처리된 새로운 문자열 생성 (공백 추가로 마크다운 충돌 방지)
        highlighted_title = ""
        last_index = 0
        for start, end in merged:
            highlighted_title += job_title[last_index:start]
            # 앞뒤 문자가 문자인 경우 공백 추가
            need_space_before = start > 0 and job_title[start-1].isalnum()
            need_space_after = end < len(job_title) and job_title[end].isalnum()

            space_before = " " if need_space_before else ""
            space_after = " " if need_space_after else ""

            highlighted_title += f"{space_before}*{job_title[start:end]}*{space_after}"
            last_index = end
        highlighted_title += job_title[last_index:]

        # 외국인 공고인 경우 문장 앞에 크리스탈볼 이모지 한 번만 추가
        if is_foreign:
            highlighted_title = f"🔮 {highlighted_title}"

        return highlighted_title, is_foreign

    def _process_company_complete(self, args):
        """선택자 찾기와 공고 수집을 한번에 처리"""
        index, row, existing_selectors = args
        company_name = row['회사_한글_이름']
        url = row['job_posting_url']
        selector = row.get('selector', '')
        use_selenium = row['selenium_required']

        self.logger.info(f"- {company_name} 처리 중...")
        self.company_urls[company_name] = url

        html_content = self.get_html_content_for_crawling(url, use_selenium)

        if not html_content:
            self.logger.error(f"  - HTML 가져오기 실패: {company_name} (selenium_required를 -1로 설정)")
            return index, None, None, {'company': company_name, 'reason': 'HTML 가져오기 실패', 'url': url, 'selenium_status': -1}

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # 선택자가 없거나 빈 경우 새로 찾기
            if not selector or selector.strip() == '':
                self.logger.info(f"  - {company_name} 선택자 찾기 중...")
                found_selector = self._try_existing_selectors(soup, existing_selectors, company_name)

                if found_selector:
                    selector = found_selector
                    self.logger.info(f"  - 기존 선택자 적용 성공: {selector}")
                else:
                    best_selector, _ = self.selector_analyzer.find_best_selector(soup)
                    if best_selector:
                        selector = best_selector
                        self.logger.info(f"  - 새 선택자 찾기 성공: {selector}")
                    else:
                        self.logger.warning(f"  - {company_name} 선택자 찾기 실패 (selenium_required를 -2로 설정)")
                        return index, None, None, {'company': company_name, 'reason': '선택자를 찾을 수 없음', 'url': url, 'selenium_status': -2}
            else:
                self.logger.info(f"  - 기존 선택자 사용: {selector}")

            # 같은 HTML로 공고 수집
            postings = soup.select(selector)
            if not postings:
                return index, selector, None, {'company': company_name, 'reason': f'선택자 \'{selector}\'로 공고를 찾지 못함', 'url': url}

            # 모든 텍스트 추출 후 필터링
            all_texts = [post.get_text(strip=True) for post in postings if post.get_text(strip=True).strip()]
            # 채용공고가 맞는 것들만 필터링
            job_titles = {text for text in all_texts if self.selector_analyzer._is_potential_job_posting(text)}

            if job_titles:
                self.logger.info(f"  - 성공: 선택자 적용 + {len(job_titles)}개 공고 수집")
                return index, selector, job_titles, None
            else:
                return index, selector, None, {'company': company_name, 'reason': '유효한 공고를 찾지 못함', 'url': url}

        except Exception as e:
            self.logger.error(f"  - {company_name} 처리 중 오류 발생: {e}")
            return index, None, None, {'company': company_name, 'reason': f'처리 중 오류: {e}', 'url': url}

    def process_companies_integrated(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict, List]:
        """전처리와 크롤링을 한번에 통합 처리 (Playwright 브라우저 재사용 최적화)"""
        self.logger.info(f"통합 처리 대상: {len(df)}개 회사")

        # 메모리 사용량 체크
        import psutil
        memory_percent = psutil.virtual_memory().percent
        if memory_percent > 80:
            self.logger.warning(f"⚠️ 메모리 사용률 높음: {memory_percent:.1f}% - 처리 속도를 늦춥니다")
            time.sleep(5)  # 메모리 부족 시 5초 대기

        # 1. selenium_required 값 채우기
        valid_companies_mask = (
            df['회사_한글_이름'].notna() & (df['회사_한글_이름'].str.strip() != '') &
            df['job_posting_url'].notna() & (df['job_posting_url'].str.strip() != '')
        )

        if valid_companies_mask.any():
            self._fill_missing_selenium_required(df, valid_companies_mask)

        # 2. 처리 가능한 회사들 필터링 (HTML 실패(-1), 선택자 실패(-2) 제외)
        companies_to_process = df[
            valid_companies_mask &
            (~df['selenium_required'].isin([-1, -2]))
        ]

        if companies_to_process.empty:
            self.logger.info("처리할 회사가 없습니다.")
            return df, {}, []

        # 3. 기존 선택자 수집
        existing_selectors = self._get_existing_selectors(df)
        self.logger.info(f"기존 선택자 {len(existing_selectors)}개 (20자 이상만) 활용")

        # 4. 중복 URL 그룹화 및 최적화
        url_groups = self._group_companies_by_url(companies_to_process)

        if len(url_groups) < len(companies_to_process):
            duplicate_savings = len(companies_to_process) - len(url_groups)
            self.logger.info(f"중복 URL 최적화: {len(companies_to_process)}개 회사 → {len(url_groups)}개 URL로 그룹화 (크롤링 {duplicate_savings}회 절약)")

        # 5. URL별 통합 처리 (선택자 찾기 + 크롤링) - Playwright 브라우저 재사용
        current_jobs = {}
        failed_companies = []
        url_results_cache = {}  # URL별 크롤링 결과 캐시

        # ⭐ Playwright 브라우저 한 번만 생성 (재사용 구조)
        playwright, browser, context = None, None, None
        try:
            playwright, browser, context = self.create_playwright_browser()
            if playwright and browser and context:
                self.logger.info("✅ Playwright 브라우저 생성 완료 - 전체 크롤링에 재사용합니다")

            # URL별 순차 처리
            results = []
            processed_count = 0
            total_urls = len(url_groups)

            for url, company_indices in url_groups.items():
                processed_count += 1
                # 각 URL 그룹에서 가장 완전한 정보를 가진 회사를 대표로 선택
                representative_idx = self._select_representative_company(companies_to_process, company_indices)
                representative_row = companies_to_process.loc[representative_idx]
                is_shared = len(company_indices) > 1  # 2개 이상 회사가 같은 URL 사용시 공유로 간주
                url_args = (representative_idx, representative_row, existing_selectors, url, is_shared, context)  # context 전달

                # 진행 상황 로그
                self.logger.info(f"🔄 진행 상황: {processed_count}/{total_urls} ({processed_count/total_urls*100:.1f}%)")

                # URL별 크롤링 실행 (브라우저 재사용)
                result = self._process_url_with_companies(url_args)
                results.append(result)

                # 10개마다 메모리 체크 및 쿨다운
                if processed_count % 10 == 0:
                    import psutil
                    memory_percent = psutil.virtual_memory().percent
                    self.logger.info(f"📊 메모리 사용률: {memory_percent:.1f}%")
                    if memory_percent > 85:
                        self.logger.warning("⚠️ 메모리 부족 - 5초 대기")
                        time.sleep(5)  # 10초 -> 5초로 단축
                    else:
                        time.sleep(0.5)  # 1초 -> 0.5초로 단축

        finally:
            # 모든 크롤링 완료 후 브라우저 종료
            if context:
                try:
                    context.close()
                except:
                    pass
            if browser:
                try:
                    browser.close()
                    self.logger.info("✅ Playwright 브라우저 종료 완료")
                except:
                    pass
            if playwright:
                try:
                    playwright.stop()
                except:
                    pass

        for url, result_selector, job_titles, error_info in results:
                url_results_cache[url] = {
                    'selector': result_selector,
                    'job_titles': job_titles,
                    'error_info': error_info
                }

        # 6. 결과를 모든 관련 회사에 적용
        for url, company_indices in url_groups.items():
            cached_result = url_results_cache[url]

            if cached_result['error_info']:
                # 실패한 경우 모든 관련 회사에 동일한 오류 적용
                for idx in company_indices:
                    company_name = companies_to_process.loc[idx, '회사_한글_이름']
                    error_info = cached_result['error_info'].copy()
                    error_info['company'] = company_name

                    if 'selenium_status' in error_info:
                        df.loc[idx, 'selenium_required'] = error_info['selenium_status']

                    failed_companies.append(error_info)

                if len(company_indices) > 1:
                    self.logger.info(f"  - URL {url[:50]}... 실패 → {len(company_indices)}개 회사에 동일 오류 적용")
            else:
                # 성공한 경우 모든 관련 회사에 동일한 결과 적용
                for idx in company_indices:
                    company_name = companies_to_process.loc[idx, '회사_한글_이름']

                    # 선택자 업데이트
                    if cached_result['selector']:
                        df.loc[idx, 'selector'] = cached_result['selector']

                    # 채용공고 결과 적용 (URL 그룹 정보도 함께 저장)
                    current_jobs[company_name] = cached_result['job_titles']
                    self.company_urls[company_name] = url

                if len(company_indices) > 1:
                    self.logger.info(f"  - URL {url[:50]}... 성공 → {len(company_indices)}개 회사에 동일 결과 적용 ({len(cached_result['job_titles'])}개 공고)")

        # 7. URL 그룹 정보 저장 (슬랙 알림용)
        self.url_groups_for_notification = self._prepare_url_groups_for_notification(url_groups, companies_to_process, current_jobs)

        # 8. 선택자 안정화
        df = self.stabilize_selectors(df)

        self.logger.info(f"통합 처리 완료: 성공 {len(current_jobs)}개, 실패 {len(failed_companies)}개")
        return df, current_jobs, failed_companies

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
            (~df['selenium_required'].isin([-1, -2]))
        ]

        if companies_to_process.empty:
            self.logger.info("새로 전처리할 회사가 없습니다.")
            return df

        self.logger.info(f"{len(companies_to_process)}개 회사에 대한 전처리를 시작합니다.")

        existing_selectors = self._get_existing_selectors(df)
        self.logger.info(f"기존 회사들에서 사용 중인 선택자 {len(existing_selectors)}개 (20자 이상만)를 우선 적용합니다.")

        # 순차 처리
        results = []
        for index, row in companies_to_process.iterrows():
            args = (index, row, existing_selectors)
            result = self._process_company_complete(args)
            results.append(result)

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

    def _group_companies_by_url(self, df: pd.DataFrame) -> Dict[str, List[int]]:
        """URL별로 회사들을 그룹화합니다."""
        url_groups = {}
        for idx, row in df.iterrows():
            url = row['job_posting_url'].strip()
            if url not in url_groups:
                url_groups[url] = []
            url_groups[url].append(idx)
        return url_groups

    def _select_representative_company(self, df: pd.DataFrame, company_indices: List[int]) -> int:
        """URL 그룹에서 가장 적합한 대표 회사를 선택합니다."""
        if len(company_indices) == 1:
            return company_indices[0]

        # 선택자가 있는 회사 우선
        for idx in company_indices:
            row = df.loc[idx]
            if pd.notna(row.get('selector', '')) and row.get('selector', '').strip():
                return idx

        # original_selector가 있는 회사 우선
        for idx in company_indices:
            row = df.loc[idx]
            if pd.notna(row.get('original_selector', '')) and row.get('original_selector', '').strip():
                return idx

        # selenium_required가 0 또는 1인 회사 우선 (실패 상태 아닌)
        for idx in company_indices:
            row = df.loc[idx]
            if row.get('selenium_required', 0) in [0, 1]:
                return idx

        # 그 외의 경우 첫 번째 회사 선택
        return company_indices[0]

    def _process_url_with_companies(self, args):
        """URL별로 크롤링을 수행합니다 (Playwright 컨텍스트 재사용)."""
        index, row, existing_selectors, url, is_shared, context = args  # context 사용
        company_name = row['회사_한글_이름']
        selector = row.get('selector', '')
        use_selenium = row['selenium_required']

        url_type = "공유 URL" if is_shared else "개별 URL"
        self.logger.info(f"- {company_name} URL 처리 중... ({url_type})")
        self.company_urls[company_name] = url

        # 컨텍스트 재사용하여 HTML 가져오기
        html_content = self.get_html_content_for_crawling_with_browser(url, use_selenium, context)

        if not html_content:
            self.logger.error(f"  - HTML 가져오기 실패: {company_name} (selenium_required를 -1로 설정)")
            return url, None, [], {'company': company_name, 'reason': 'HTML 가져오기 실패', 'url': url, 'selenium_status': -1}

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # 선택자가 없거나 빈 경우 새로 찾기
            if not selector or selector.strip() == '':
                self.logger.info(f"  - {company_name} 선택자 찾기 중...")
                found_selector = self._try_existing_selectors(soup, existing_selectors, company_name)

                if found_selector:
                    selector = found_selector
                    self.logger.info(f"  - 기존 선택자 적용 성공: {selector}")
                else:
                    best_selector, _ = self.selector_analyzer.find_best_selector(soup)
                    if best_selector:
                        selector = best_selector
                        self.logger.info(f"  - 새 선택자 찾기 성공: {selector}")
                    else:
                        self.logger.warning(f"  - {company_name} 선택자 찾기 실패 (selenium_required를 -2로 설정)")
                        return url, None, [], {'company': company_name, 'reason': '선택자를 찾을 수 없음', 'url': url, 'selenium_status': -2}
            else:
                self.logger.info(f"  - 기존 선택자 사용: {selector}")

            # 채용공고 수집
            postings = soup.select(selector)
            if not postings:
                self.logger.warning(f"  - {company_name} 선택자로 요소를 찾을 수 없음: {selector}")
                return url, selector, [], None

            job_titles = [elem.get_text(strip=True) for elem in postings if elem.get_text(strip=True)]
            job_titles = [title for title in job_titles if len(title) > 2 and len(title) < 200]
            job_titles = list(set(job_titles))  # 중복 제거

            url_type = "URL 공유" if is_shared else "개별 URL"
            self.logger.info(f"  - {company_name} 성공: {len(job_titles)}개 채용공고 수집 ({url_type})")
            return url, selector, job_titles, None

        except Exception as e:
            self.logger.error(f"  - {company_name} 처리 중 오류: {e}")
            return url, None, [], {'company': company_name, 'reason': f'처리 오류: {str(e)}', 'url': url, 'selenium_status': None}

    def _prepare_url_groups_for_notification(self, url_groups: Dict[str, List[int]], companies_df: pd.DataFrame, current_jobs: Dict) -> Dict[str, List[str]]:
        """슬랙 알림용 URL 그룹 정보를 준비합니다."""
        notification_groups = {}

        for url, company_indices in url_groups.items():
            if len(company_indices) > 1:  # 중복 URL만 처리
                company_names = []
                for idx in company_indices:
                    company_name = companies_df.loc[idx, '회사_한글_이름']
                    # 실제로 채용공고를 가져온 회사만 포함
                    if company_name in current_jobs:
                        company_names.append(company_name)

                if len(company_names) > 1:  # 성공한 회사가 2개 이상일 때만 그룹화
                    notification_groups[url] = company_names

        return notification_groups

    def _get_existing_selectors(self, df: pd.DataFrame) -> List[str]:
        """기존에 성공적으로 사용된 선택자들을 수집합니다 (20자 이상만)."""
        existing_selectors = []

        # 20자 이상의 선택자만 수집
        valid_selectors = df[df['selector'].notna() & (df['selector'] != '')]['selector'].unique()
        valid_selectors = [s for s in valid_selectors if len(s) >= 20]
        existing_selectors.extend(valid_selectors)

        expanded_selectors = []
        for selector in valid_selectors:
            expanded_selectors.append(selector)
            stabilized = stabilize_selector(selector, conservative=False)
            if stabilized != selector and stabilized and len(stabilized) >= 20:
                expanded_selectors.append(stabilized)

        # known_good_selectors도 20자 이상만 포함
        known_good_selectors = [
            "a div.sc-9b56f69e-0.jlntFl",
            "div.JobPostingsJobPosting__Layout-sc-6ae888f2-0.ffnSOB div.JobPostingsJobPosting__Bottom-sc-6ae888f2-5.iXrIoX",
            "#jobList > div.jobList_info > div > a > span.title",
            "div.RecruitList_left__5MzDR div.RecruitList_title-wrapper__Gvh1r p",
            "div.swiper-slide button p",
        ]
        # 20자 이상인 것만 추가
        known_good_selectors = [s for s in known_good_selectors if len(s) >= 20]
        expanded_selectors.extend(known_good_selectors)

        selector_counts = df[df['selector'].notna() & (df['selector'] != '')]['selector'].value_counts()
        sorted_selectors = [s for s in selector_counts.index.tolist() if len(s) >= 20]

        final_selectors = sorted_selectors + [s for s in expanded_selectors if s not in sorted_selectors]

        self.logger.info(f"수집된 선택자 {len(final_selectors)}개 (20자 이상만, 기존: {len(sorted_selectors)}개, 확장: {len(expanded_selectors)}개)")
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
        # 20자 이상의 선택자만 재활용 시도
        valid_selectors = [s for s in existing_selectors if len(s) >= 20 and self._is_specific_enough_selector(s)]

        for i, selector in enumerate(valid_selectors):
            # 이미 필터링되었으므로 길이 체크 불필요

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

        # 순차 처리
        for index, row in missing_selenium.iterrows():
            company_name = row['회사_한글_이름']
            try:
                selenium_required = self._determine_selenium_requirement(row['job_posting_url'], row['회사_한글_이름'])
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
        row, _ = args
        company_name, url, use_selenium, selector = row['회사_한글_이름'], row['job_posting_url'], row['selenium_required'], row['selector']
        self.company_urls[company_name] = url
        self.logger.info(f"- {company_name} 크롤링 중...")

        html_content = self.get_html_content_for_crawling(url, use_selenium, selector)

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
            (~df_config['selenium_required'].isin([-1, -2]))
        ].copy()

        if df_crawl.empty:
            self.logger.warning("크롤링할 회사가 없습니다.")
            return {}, []

        current_jobs = {}
        failed_companies = []

        # 순차 처리
        results = []
        for _, row in df_crawl.iterrows():
            args = (row, df_crawl)
            result = self._crawl_company(args)
            results.append(result)

        for result in results:
                company_name, job_titles = result
                if company_name and job_titles:
                    current_jobs[company_name] = job_titles
                elif job_titles:
                    failed_companies.append(job_titles)

        self.logger.info("--- 3. 채용 공고 크롤링 종료 ---")
        return current_jobs, failed_companies

    def compare_and_notify(self, current_jobs: Dict, failed_companies: List, chunk_info: str = None, save: bool = True, send_notifications: bool = True) -> Tuple[Dict, List, List]:
        self.logger.info("--- 4. 비교 및 알림 시작 ---")
        existing_jobs = self.load_existing_jobs()
        new_jobs = self.find_new_jobs(current_jobs, existing_jobs)
        warnings = self.check_suspicious_results(current_jobs, existing_jobs, new_jobs)

        # 청크별 즉시 알림 비활성화 - 모든 청크 처리 후 통합 알림
        # if send_notifications and (new_jobs or warnings or failed_companies):
        #     self.send_slack_notification(new_jobs, warnings, failed_companies, chunk_info=chunk_info)

        if save and current_jobs:
            self.save_jobs(current_jobs)
        self.logger.info("--- 4. 비교 및 알림 종료 ---")
        return new_jobs, warnings, failed_companies

    def get_html_content(self, url, use_selenium, selector=None):
        """선택자 분석용 HTML 가져오기 메서드 (Playwright 사용)"""
        max_retries = 2
        for attempt in range(max_retries):
            try:
                if not use_selenium:
                    # 세션에 이미 헤더가 설정되어 있음
                    response = self.session.get(url, timeout=20)
                    response.raise_for_status()
                    return response.text
                else:
                    playwright, browser, context = self.create_playwright_browser()
                    if not playwright or not browser or not context:
                        raise Exception("Playwright 브라우저를 시작할 수 없습니다.")

                    try:
                        page = context.new_page()
                        page.goto(url, timeout=20000)

                        if selector:
                            try:
                                page.wait_for_selector(selector, timeout=20000)
                                time.sleep(3)
                            except Exception:
                                self.logger.warning(f"'{selector}' 요소를 기다리는 데 실패했습니다.")
                        else:
                            time.sleep(5)

                        html_content = page.content()
                        return html_content
                    finally:
                        context.close()
                        browser.close()
                        playwright.stop()

            except Exception as e:
                if "timeout" in str(e).lower() and attempt < max_retries - 1:
                    self.logger.warning(f"페이지 로드 타임아웃 ({attempt + 1}/{max_retries}): {url} - 재시도 중...")
                    time.sleep(5)
                    continue
                else:
                    self.logger.error(f"HTML 가져오기 실패: {url}, 오류: {e}")
                    return None

    def get_html_content_for_crawling_with_browser(self, url, use_selenium, context=None, selector=None):
        """실제 크롤링용 HTML 가져오기 (Playwright 컨텍스트 재사용)"""
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("크롤링 타임아웃")

        try:
            # URL별 타임아웃 설정 (signal은 백업용, Playwright 자체 타임아웃이 우선)
            if 'toss.im' in url:
                timeout_seconds = 180  # toss.im: 3분
                page_timeout = 60000  # 60초
                wait_time = 3
            else:
                timeout_seconds = 60   # 나머지: 1분
                page_timeout = 20000   # 20초
                wait_time = 1

            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout_seconds)

            if not use_selenium:
                # 더 현실적인 브라우저 헤더 사용
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Cache-Control': 'max-age=0',
                    'Referer': url
                }
                response = requests.get(url, headers=headers, timeout=20, verify=False)
                response.raise_for_status()
                self.logger.debug(f"HTTP 요청 성공: {url} (응답 코드: {response.status_code})")
                return response.text
            else:
                # ⭐ 컨텍스트가 전달되었으면 재사용, 없으면 새로 생성
                should_close_context = False
                playwright, browser = None, None
                if not context:
                    playwright, browser, context = self.create_playwright_browser()
                    should_close_context = True
                    if not context:
                        raise Exception("Playwright 브라우저를 시작할 수 없습니다.")

                try:
                    max_retries = 2
                    page = None
                    for attempt in range(max_retries):
                        try:
                            page = context.new_page()  # 컨텍스트에서 페이지 생성 (타임아웃 자동 적용)
                            page.set_extra_http_headers({"Accept-Encoding": "gzip"})
                            page.goto(url, timeout=page_timeout)  # URL별 타임아웃

                            if selector:
                                try:
                                    page.wait_for_selector(selector, timeout=page_timeout // 2)
                                    time.sleep(wait_time)
                                except Exception:
                                    self.logger.warning(f"선택자 '{selector}' 요소를 기다리는 데 실패했습니다.")
                            else:
                                time.sleep(wait_time)

                            html_content = page.content()
                            return html_content

                        except Exception as e:
                            error_msg = str(e).lower()
                            if ("timeout" in error_msg or "target" in error_msg) and attempt < max_retries - 1:
                                self.logger.warning(f"페이지 처리 오류 ({attempt + 1}/{max_retries}): {url} - {type(e).__name__} - 재시도 중...")
                                if page:
                                    try:
                                        page.close()
                                    except:
                                        pass
                                time.sleep(wait_time)  # URL별 대기 시간
                                continue
                            else:
                                raise e
                        finally:
                            if page:
                                try:
                                    page.close()  # 페이지만 닫기 (컨텍스트는 유지)
                                except:
                                    pass

                    raise Exception("모든 재시도 실패")

                finally:
                    # ⭐ 직접 생성한 컨텍스트/브라우저만 닫기
                    if should_close_context:
                        try:
                            if context:
                                context.close()
                            if browser:
                                browser.close()
                            if playwright:
                                playwright.stop()
                        except:
                            pass

        except requests.exceptions.Timeout as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (타임아웃): {url} - {str(e)}")
            return None
        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (연결 오류): {url} - {str(e)}")
            return None
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (HTTP {e.response.status_code}): {url} - {str(e)}")
            return None
        except requests.exceptions.SSLError as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (SSL 오류): {url} - {str(e)}")
            return None
        except TimeoutError as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (타임아웃): {url} - {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (기타 오류): {url} - {type(e).__name__}: {str(e)}")
            return None
        finally:
            try:
                signal.alarm(0)
            except:
                pass

    def get_html_content_for_crawling(self, url, use_selenium, selector=None):
        """실제 크롤링용 HTML 가져오기 메서드 (하위 호환성 유지)"""
        return self.get_html_content_for_crawling_with_browser(url, use_selenium, None, selector)

    def get_html_content_for_crawling_old(self, url, use_selenium, selector=None):
        """[DEPRECATED] 실제 크롤링용 HTML 가져오기 메서드 (Playwright 매번 생성 - 사용 안 함)"""
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("크롤링 타임아웃")

        try:
            # 개별 URL 크롤링에 5분 타임아웃 설정
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(300)  # 5분
            if not use_selenium:
                # 더 현실적인 브라우저 헤더 사용
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Cache-Control': 'max-age=0',
                    'Referer': url  # 리퍼러 추가로 자연스러운 브라우징 시뮬레이션
                }
                response = requests.get(url, headers=headers, timeout=20, verify=False)
                response.raise_for_status()
                self.logger.debug(f"HTTP 요청 성공: {url} (응답 코드: {response.status_code})")
                return response.text
            else:
                playwright, browser, context = self.create_playwright_browser()
                if not playwright or not browser or not context:
                    raise Exception("Playwright 브라우저를 시작할 수 없습니다.")

                try:
                    max_retries = 2
                    page = None
                    for attempt in range(max_retries):
                        try:
                            page = context.new_page()
                            # 메모리 사용량 줄이기 위한 설정
                            page.set_extra_http_headers({"Accept-Encoding": "gzip"})

                            page.goto(url, timeout=15000)  # 타임아웃 단축

                            if selector:
                                try:
                                    page.wait_for_selector(selector, timeout=10000)  # 타임아웃 단축
                                    time.sleep(2)  # 대기 시간 단축
                                except Exception:
                                    self.logger.warning(f"선택자 '{selector}' 요소를 기다리는 데 실패했습니다.")
                            else:
                                time.sleep(3)  # 대기 시간 단축

                            html_content = page.content()
                            return html_content

                        except Exception as e:
                            error_msg = str(e).lower()
                            if ("timeout" in error_msg or "target" in error_msg) and attempt < max_retries - 1:
                                self.logger.warning(f"페이지 처리 오류 ({attempt + 1}/{max_retries}): {url} - {type(e).__name__} - 재시도 중...")
                                if page:
                                    try:
                                        page.close()
                                    except:
                                        pass
                                time.sleep(3)
                                continue
                            else:
                                raise e
                        finally:
                            if page:
                                try:
                                    page.close()
                                except:
                                    pass

                    # 여기까지 오면 모든 재시도 실패
                    raise Exception("모든 재시도 실패")

                finally:
                    # 브라우저 정리
                    try:
                        if context:
                            context.close()
                        if browser:
                            browser.close()
                        if playwright:
                            playwright.stop()
                    except:
                        pass

        except requests.exceptions.Timeout as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (타임아웃): {url} - {str(e)}")
            return None
        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (연결 오류): {url} - {str(e)}")
            return None
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (HTTP {e.response.status_code}): {url} - {str(e)}")
            return None
        except requests.exceptions.SSLError as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (SSL 오류): {url} - {str(e)}")
            return None
        except TimeoutError as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (타임아웃): {url} - {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패 (기타 오류): {url} - {type(e).__name__}: {str(e)}")
            return None
        finally:
            # 타임아웃 알람 해제
            try:
                signal.alarm(0)
            except:
                pass

    def create_playwright_browser(self):
        """Playwright 브라우저 인스턴스 생성 (타임아웃 강제 설정)"""
        playwright = None
        browser = None
        context = None
        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                    "--ignore-certificate-errors",
                    "--ignore-ssl-errors",
                    "--ignore-certificate-errors-spki-list",
                    "--memory-pressure-off",  # 메모리 압박 모드 비활성화
                    "--max_old_space_size=2048"  # 메모리 제한 설정
                ]
            )
            # ⭐ 브라우저 컨텍스트 생성 및 타임아웃 강제 설정
            context = browser.new_context()
            context.set_default_timeout(60000)  # 60초 - 요소 대기, 클릭 등
            context.set_default_navigation_timeout(90000)  # 90초 - 페이지 이동
            self.logger.info("Playwright 브라우저 실행 성공 (타임아웃: 60초/90초)")
            return playwright, browser, context
        except Exception as e:
            self.logger.error(f"Playwright 브라우저 실행 실패: {e}")
            # 실패 시 정리
            try:
                if context:
                    context.close()
                if browser:
                    browser.close()
                if playwright:
                    playwright.stop()
            except:
                pass
            return None, None, None

    def load_existing_jobs(self) -> Dict[str, Set[str]]:
        if not os.path.exists(self.results_path):
            return {}
        try:
            df = pd.read_csv(self.results_path, encoding='utf-8-sig')
            if df.empty or 'job_posting_title' not in df.columns or '회사_한글_이름' not in df.columns:
                self.logger.warning("기존 공고 파일이 비어있거나 필수 컬럼이 없습니다.")
                return {}
            return {comp: set(df_comp['job_posting_title']) for comp, df_comp in df.groupby('회사_한글_이름')}
        except pd.errors.EmptyDataError:
            self.logger.warning("기존 공고 파일이 비어있습니다.")
            return {}
        except Exception as e:
            self.logger.error(f"기존 공고 로드 오류: {e}")
            return {}

    def find_new_jobs(self, current_jobs: Dict, existing_jobs: Dict) -> Dict[str, List[str]]:
        new_jobs = {}
        try:
            for comp, curr in current_jobs.items():
                try:
                    # current_jobs의 값이 list인지 set인지 상관없이 set으로 변환
                    if curr is None:
                        curr = []
                    curr_set = set(curr) if not isinstance(curr, set) else curr
                    existing_set = existing_jobs.get(comp, set())
                    new_jobs_for_company = list(curr_set - existing_set)
                    if new_jobs_for_company:
                        new_jobs[comp] = new_jobs_for_company
                except Exception as e:
                    self.logger.error(f"회사 '{comp}'의 새로운 공고 비교 중 오류: {e}")
                    continue
            return new_jobs
        except Exception as e:
            self.logger.error(f"새로운 공고 찾기 중 전체 오류: {e}")
            return {}

    def check_suspicious_results(self, current_jobs: Dict, existing_jobs: Dict, new_jobs: Dict) -> List[str]:
        warnings = []
        for company, new_list in new_jobs.items():
            existing_count = len(existing_jobs.get(company, set()))
            current_jobs_data = current_jobs.get(company, [])
            current_count = len(current_jobs_data) if isinstance(current_jobs_data, (list, set)) else 0

            if existing_count > 0 and len(new_list) == current_count:
                warnings.append(f"{company}: 기존 공고가 모두 사라지고 새로운 공고만 보입니다. 홈페이지를 직접 확인해주세요.")
        return warnings

    def save_jobs(self, current_jobs: Dict):
        kst = pytz.timezone('Asia/Seoul')
        current_time_kst = datetime.now(kst)
        all_postings = [{'회사_한글_이름': comp, 'job_posting_title': title, 'crawl_datetime': current_time_kst.strftime('%Y-%m-%d %H:%M:%S')} for comp, titles in current_jobs.items() for title in titles]

        try:
            pd.DataFrame(all_postings).to_csv(self.results_path, index=False, encoding='utf-8-sig')
            self.logger.info(f"결과를 '{self.results_path}'에 저장했습니다.")
        except PermissionError as e:
            self.logger.error(f"파일 저장 권한 오류: {e}")
            # 대안 경로 시도
            import tempfile
            temp_path = os.path.join(tempfile.gettempdir(), 'job_postings_latest.csv')
            try:
                pd.DataFrame(all_postings).to_csv(temp_path, index=False, encoding='utf-8-sig')
                self.logger.info(f"임시 경로에 결과를 저장했습니다: '{temp_path}'")
            except Exception as e2:
                self.logger.error(f"임시 파일 저장도 실패: {e2}")
        except Exception as e:
            self.logger.error(f"파일 저장 중 오류 발생: {e}")

    def save_jobs_incrementally(self, current_jobs: Dict, append: bool):
        """결과를 CSV 파일에 증분 저장합니다."""
        kst = pytz.timezone('Asia/Seoul')
        current_time_kst = datetime.now(kst)
        all_postings = [{'회사_한글_이름': comp, 'job_posting_title': title, 'crawl_datetime': current_time_kst.strftime('%Y-%m-%d %H:%M:%S')} for comp, titles in current_jobs.items() for title in titles]

        if not all_postings:
            return

        df_to_save = pd.DataFrame(all_postings)
        mode = 'a' if append else 'w'
        header = not append

        try:
            df_to_save.to_csv(self.results_path, mode=mode, header=header, index=False, encoding='utf-8-sig')
            self.logger.info(f"결과를 '{self.results_path}'에 {'추가' if append else '저장'}했습니다. ({len(df_to_save)}개 항목)")
        except Exception as e:
            self.logger.error(f"파일 증분 저장 중 오류 발생: {e}")

    def save_jobs_incrementally(self, current_jobs: Dict, append: bool):
        """결과를 CSV 파일에 증분 저장합니다."""
        kst = pytz.timezone('Asia/Seoul')
        current_time_kst = datetime.now(kst)
        all_postings = [{'회사_한글_이름': comp, 'job_posting_title': title, 'crawl_datetime': current_time_kst.strftime('%Y-%m-%d %H:%M:%S')} for comp, titles in current_jobs.items() for title in titles]

        if not all_postings:
            return

        df_to_save = pd.DataFrame(all_postings)
        mode = 'a' if append else 'w'
        header = not append

        try:
            df_to_save.to_csv(self.results_path, mode=mode, header=header, index=False, encoding='utf-8-sig')
            self.logger.info(f"결과를 '{self.results_path}'에 {'추가' if append else '저장'}했습니다. ({len(df_to_save)}개 항목)")
        except Exception as e:
            self.logger.error(f"파일 증분 저장 중 오류 발생: {e}")

    def send_slack_notification(self, new_jobs: Dict, warnings: List, failed_companies: List, chunk_info: str = None):
        self.logger.info(f"🚀 send_slack_notification 호출됨:")
        self.logger.info(f"  - new_jobs: {len(new_jobs)}개")
        self.logger.info(f"  - warnings: {len(warnings)}개")
        self.logger.info(f"  - failed_companies: {len(failed_companies)}개")
        self.logger.info(f"  - chunk_info: {chunk_info}")

        if not self.webhook_url:
            self.logger.error(f"❌ 웹훅 URL 없음: {self.webhook_url_env}이 .env에 설정되지 않았습니다.")
            return
        else:
            self.logger.info(f"✅ 웹훅 URL 확인됨: {self.webhook_url[:50]}...")

        if not new_jobs and not warnings and not failed_companies:
            self.logger.warning("❌ 알림 보낼 내용이 없습니다.")
            return

        kst = pytz.timezone('Asia/Seoul')
        current_time = datetime.now(kst).strftime('%H:%M')
        current_datetime = datetime.now(kst)
        weekdays = ['월', '화', '수', '목', '금', '토', '일']
        formatted_datetime = f"{current_datetime.month}월 {current_datetime.day}일 ({weekdays[current_datetime.weekday()]}) {current_datetime.strftime('%H:%M')}"

        def sanitize_slack_text(text: str) -> str:
            """슬랙 메시지용 텍스트를 안전하게 처리합니다."""
            if not text:
                return ""
            # JSON 특수 문자 이스케이프
            text = text.replace('\\', '\\\\').replace('"', '\\"')
            # 닫히지 않은 마크다운 수정
            if text.count('*') % 2 == 1:
                text += '*'
            if text.count('_') % 2 == 1:
                text += '_'
            # 텍스트 길이 제한 (안전 마진 포함)
            if len(text) > 2900:
                text = text[:2900] + "..."
            return text

        def send_payload(payload):
            try:
                # 텍스트 필드 안전하게 처리
                if 'text' in payload:
                    payload['text'] = sanitize_slack_text(payload['text'])

                self.logger.info(f"📤 슬랙 메시지 전송 시도")
                response = requests.post(self.webhook_url, json=payload, timeout=15)
                if response.status_code == 200:
                    self.logger.info("✅ 슬랙 알림 전송 완료")
                else:
                    self.logger.error(f"❌ 슬랙 응답 오류: {response.status_code} - {response.text}")
            except Exception as e:
                self.logger.error(f"❌ 슬랙 알림 전송 오류: {e}")

        def create_unified_message():
            """통합 메시지를 생성합니다."""
            # [DEBUG] 함수 진입 확인
            self.logger.info(f"[DEBUG SLACK] create_unified_message 진입 - new_jobs type: {type(new_jobs)}, len: {len(new_jobs) if new_jobs else 0}")
            self.logger.info(f"[DEBUG SLACK] new_jobs keys: {list(new_jobs.keys())[:5] if new_jobs else 'None'}")

            content_sections = []

            # 요약 헤더 생성
            summary_parts = []
            total_new_jobs = sum(len(jobs) for jobs in new_jobs.values()) if new_jobs else 0
            foreign_job_count = sum(1 for jobs in new_jobs.values() for job in jobs if self._is_foreign_job_posting(job)) if new_jobs else 0

            if total_new_jobs > 0:
                foreign_info = f" (외국인 채용: {foreign_job_count}개 🔮)" if foreign_job_count > 0 else ""
                summary_parts.append(f"새로운 공고: {total_new_jobs}개{foreign_info}")
            if warnings:
                summary_parts.append(f"홈페이지 확인: {len(warnings)}개")
            if failed_companies:
                summary_parts.append(f"실패: {len(failed_companies)}개")

            chunk_str = f"({chunk_info}) " if chunk_info else ""
            summary = " | ".join(summary_parts)
            header = f":robot_face: *채용공고 모니터링 결과* {chunk_str}({current_time})\n*{summary}*"

            # 1. 새로운 공고 섹션
            if new_jobs:
                processed_companies = set()
                # 전체 URL 그룹 사용 (5000대_기업) 또는 청크별 그룹 사용 (기타)
                url_groups = getattr(self, 'global_url_groups', {}) or getattr(self, 'url_groups_for_notification', {})

                # URL 그룹 처리 (같은 URL을 사용하는 여러 회사들)
                self.logger.info(f"[DEBUG] url_groups 개수: {len(url_groups)}")
                for url, grouped_companies in url_groups.items():
                    if len(grouped_companies) > 1:
                        # 그룹에 속한 회사들 중 새로운 공고가 있는 회사들만 확인
                        companies_with_jobs = [c for c in grouped_companies if c in new_jobs]
                        if companies_with_jobs:
                            # 대표 회사의 공고를 사용 (모든 회사가 같은 URL이므로 공고도 동일)
                            rep_company = companies_with_jobs[0]
                            jobs = new_jobs[rep_company]
                            company_names = " / ".join(companies_with_jobs)
                            linked_company = f"<{url}|{company_names}>"
                            company_with_time = f"{linked_company} - {formatted_datetime}"
                            job_lines = [f"  • {self._highlight_foreign_keywords(self._clean_job_title(job))[0]}" for job in jobs]
                            job_text = "\n".join(job_lines)
                            group_info = f"🔗 *{len(companies_with_jobs)}개 회사 공유 URL*"
                            content_sections.append(f"📢 {company_with_time} - {len(jobs)}개\n{group_info}\n{job_text}")
                            processed_companies.update(companies_with_jobs)
                            # 디버깅용 로그
                            self.logger.info(f"[DEBUG GROUP] companies='{company_names[:50]}', url='{url[:50]}', linked='{linked_company[:80]}'")

                # 개별 회사 처리 (URL 그룹에 속하지 않는 회사들)
                self.logger.info(f"[DEBUG SLACK] company_urls 개수: {len(self.company_urls)}")
                for company, jobs in new_jobs.items():
                    if company not in processed_companies:
                        company_url = self.company_urls.get(company, "")
                        self.logger.info(f"[DEBUG SLACK] 회사: '{company}' -> URL: '{company_url[:50] if company_url else 'EMPTY'}'")
                        linked_company = f"<{company_url}|{company}>" if company_url else f"*{company}*"
                        company_with_time = f"{linked_company} - {formatted_datetime}"
                        job_lines = [f"  • {self._highlight_foreign_keywords(self._clean_job_title(job))[0]}" for job in jobs]
                        job_text = "\n".join(job_lines)
                        section_content = f"📢 {company_with_time} - {len(jobs)}개\n{job_text}"
                        content_sections.append(section_content)
                        # 디버깅용 로그
                        self.logger.info(f"[DEBUG] company='{company}', url='{company_url[:50] if company_url else 'N/A'}', linked='{linked_company[:80]}'")

            # 2. 확인이 필요한 공고 섹션
            if warnings:
                warning_header = "⚠️ 확인이 필요한 회사들 (추가 공고가 있을 수 있으니 홈페이지를 직접 확인해주세요):"
                warning_section = warning_header

                for i, warning in enumerate(warnings):
                    # "회사명: 메시지" 형태에서 회사명만 추출
                    company_name = warning.split(':')[0] if ':' in warning else warning
                    new_line = f"\n{company_name}"

                    # 길이 체크: 2000자 초과하면 현재 섹션 저장하고 새 섹션 시작
                    if len(warning_section + new_line) > 2000:
                        content_sections.append(warning_section)
                        warning_section = "⚠️ (계속)" + new_line
                    else:
                        warning_section += new_line

                # 마지막 섹션 추가
                if warning_section != warning_header:
                    content_sections.append(warning_section)

            # 3. 실패한 공고 섹션
            if failed_companies:
                failed_header = ":x: 크롤링에 실패한 회사들 (구글 시트에서 수정하거나 홈페이지를 확인해주세요):"
                failed_section = failed_header

                for failed in failed_companies:
                    company_name = failed.get('company', '알 수 없음')
                    reason = failed.get('reason', '알 수 없음')
                    new_line = f"\n{company_name}: {reason}"

                    # 길이 체크: 2000자 초과하면 현재 섹션 저장하고 새 섹션 시작
                    if len(failed_section + new_line) > 2000:
                        content_sections.append(failed_section)
                        failed_section = ":x: (계속)" + new_line
                    else:
                        failed_section += new_line

                # 마지막 섹션 추가
                if failed_section != failed_header:
                    content_sections.append(failed_section)

            return header, content_sections

        def paginate_and_send_unified(header: str, content_sections: List[str]):
            """통합 메시지를 페이징하여 전송합니다."""
            CHAR_LIMIT = 2800

            # [DEBUG] 전송 전 내용 확인
            self.logger.info(f"[DEBUG SLACK] content_sections 개수: {len(content_sections)}")
            if content_sections:
                self.logger.info(f"[DEBUG SLACK] 첫 번째 섹션 미리보기: {content_sections[0][:200] if content_sections[0] else 'EMPTY'}")

            # 전체 컨텐츠를 하나의 문자열로 결합
            full_content = "\n".join(content_sections)

            # 헤더 길이를 고려하여 실제 컨텐츠 제한 계산
            header_overhead = len(header) + 100  # 여유분 포함
            content_limit = CHAR_LIMIT - header_overhead

            self.logger.info(f"[DEBUG SLACK] full_content 길이: {len(full_content)}, content_limit: {content_limit}")

            if len(full_content) <= content_limit:
                # 한 번에 전송 가능 - 단순 텍스트 형식
                full_message = f"{header}\n\n{full_content}"
                self.logger.info(f"[DEBUG SLACK] 전송할 메시지 미리보기: {full_message[:300]}...")
                payload = {"text": full_message, "username": "채용공고 알리미", "icon_emoji": ":robot_face:"}
                send_payload(payload)
            else:
                # 페이징 필요
                pages = []
                current_page = ""

                for section in content_sections:
                    separator = "\n" if current_page else ""
                    if len(current_page) + len(separator) + len(section) > content_limit:
                        if current_page:
                            pages.append(current_page)
                        current_page = section
                    else:
                        current_page += separator + section

                if current_page:
                    pages.append(current_page)

                # 각 페이지 전송 - 단순 텍스트 형식
                for i, page_content in enumerate(pages):
                    if i == 0:
                        # 첫 번째 페이지
                        if len(pages) > 1:
                            full_message = f"{header}\n\n{page_content}\n\n*({i+1}/{len(pages)})*"
                        else:
                            full_message = f"{header}\n\n{page_content}"
                    elif i == len(pages) - 1:
                        # 마지막 페이지
                        full_message = f"{page_content}\n\n:white_check_mark: *전체 결과 끝* *({i+1}/{len(pages)})*"
                    else:
                        # 중간 페이지
                        full_message = f"{page_content}\n\n*({i+1}/{len(pages)})*"

                    payload = {"text": full_message, "username": "채용공고 알리미", "icon_emoji": ":robot_face:"}
                    send_payload(payload)

                    # 페이지 간 최소 간격 (연속성 확보)
                    if i < len(pages) - 1:
                        time.sleep(0.5)

        # 통합 메시지 생성 및 전송
        header, content_sections = create_unified_message()
        paginate_and_send_unified(header, content_sections)

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dag = JobMonitoringDAG(base_dir)
    dag.run()

if __name__ == "__main__":
    main()