import os
import time
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
        self.max_workers = int(os.getenv('MAX_WORKERS', '3'))
        self.foreign_keywords = []  # 외국인 채용공고 키워드

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

        if self.worksheet_name == '5000대_기업':
            # 외국인 채용공고 키워드 로드
            self.foreign_keywords = self._load_foreign_keywords()

            df_to_process = df_config[df_config['job_posting_url'].notna() & (df_config['job_posting_url'].str.strip() != '')].copy()

            chunk_size = 100
            num_chunks = (len(df_to_process) - 1) // chunk_size + 1
            self.logger.info(f"'{self.worksheet_name}' 시트의 {len(df_to_process)}개 기업을 {num_chunks}개 청크로 분할하여 처리합니다.")

            all_current_jobs = {}
            list_of_df_chunks = [df_to_process.iloc[i:i+chunk_size] for i in range(0, len(df_to_process), chunk_size)]

            for i, df_chunk in enumerate(list_of_df_chunks):
                start_num = i * chunk_size + 1
                end_num = start_num + len(df_chunk) - 1
                chunk_info = f"{start_num}-{end_num}번째 기업"
                self.logger.info(f"--- 청크 처리 시작: {chunk_info} ({len(df_chunk)}개 기업) ---")

                # 각 청크별로 통합 처리 (전처리 + 크롤링)
                self.logger.info(f"청크 {i+1}/{num_chunks} 통합 처리 시작")
                df_chunk_processed, current_jobs_chunk, failed_companies_chunk = self.process_companies_integrated(df_chunk)

                # 전체 DataFrame에 업데이트
                df_config.update(df_chunk_processed)
                all_current_jobs.update(current_jobs_chunk)

                # 100개 청크마다 안전한 중간 저장
                self.logger.info(f"청크 {i+1}/{num_chunks} Google Sheets 안전 업데이트 중...")
                try:
                    # 헤더를 유지하면서 데이터만 업데이트
                    self.sheet_manager.safe_update_rows(df_config, self.worksheet_name)
                    self.logger.info(f"✅ 청크 {i+1}/{num_chunks} 시트 안전 업데이트 완료 (총 {len(df_config)} 회사)")
                except Exception as e:
                    self.logger.error(f"❌ 청크 {i+1} 시트 업데이트 실패: {e}")

                self.compare_and_notify(current_jobs_chunk, failed_companies_chunk, chunk_info=chunk_info, save=False)

                self.logger.info(f"--- 청크 처리 종료: {chunk_info} ---")
                if i < num_chunks - 1:
                    self.logger.info(f"다음 청크 처리를 위해 1분간 대기합니다.")
                    time.sleep(60)

            if all_current_jobs:
                self.save_jobs(all_current_jobs)

            self.logger.info("모든 청크 처리 완료. Google Sheets에 변경 사항 업데이트 중...")
            self.sheet_manager.update_sheet_from_df(df_config, self.worksheet_name)
            self.logger.info("✅ Google Sheets 업데이트 완료")

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

            self.compare_and_notify(current_jobs, failed_companies)

        self.logger.info(f"✅ Job Monitoring DAG 종료 - {self.worksheet_name}")

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
        """전처리와 크롤링을 한번에 통합 처리"""
        self.logger.info(f"통합 처리 대상: {len(df)}개 회사")

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

        # 4. 통합 처리 (선택자 찾기 + 크롤링)
        current_jobs = {}
        failed_companies = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            args_list = [(index, row, existing_selectors) for index, row in companies_to_process.iterrows()]
            results = executor.map(self._process_company_complete, args_list)

            for index, selector, job_titles, error_info in results:
                if selector:
                    df.loc[index, 'selector'] = selector

                if job_titles:
                    company_name = companies_to_process.loc[index, '회사_한글_이름']
                    current_jobs[company_name] = job_titles
                elif error_info:
                    # 실패 유형별로 selenium_required 값 설정
                    if 'selenium_status' in error_info:
                        df.loc[index, 'selenium_required'] = error_info['selenium_status']
                        self.logger.info(f"  - {error_info['company']} selenium_required를 {error_info['selenium_status']}로 설정")
                    failed_companies.append(error_info)

        # 5. 선택자 안정화
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
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

    def compare_and_notify(self, current_jobs: Dict, failed_companies: List, chunk_info: str = None, save: bool = True):
        self.logger.info("--- 4. 비교 및 알림 시작 ---")
        existing_jobs = self.load_existing_jobs()
        new_jobs = self.find_new_jobs(current_jobs, existing_jobs)
        warnings = self.check_suspicious_results(current_jobs, existing_jobs, new_jobs)
        self.send_slack_notification(new_jobs, warnings, failed_companies, chunk_info=chunk_info)
        if save and current_jobs:
            self.save_jobs(current_jobs)
        self.logger.info("--- 4. 비교 및 알림 종료 ---")

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
                    playwright, browser = self.create_playwright_browser()
                    if not playwright or not browser:
                        raise Exception("Playwright 브라우저를 시작할 수 없습니다.")

                    try:
                        page = browser.new_page()
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

    def get_html_content_for_crawling(self, url, use_selenium, selector=None):
        """실제 크롤링용 HTML 가져오기 메서드 (Playwright 사용)"""
        try:
            if not use_selenium:
                # 더 현실적인 브라우저 헤더 사용
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
                response = requests.get(url, headers=headers, timeout=20)
                response.raise_for_status()
                return response.text
            else:
                playwright, browser = self.create_playwright_browser()
                if not playwright or not browser:
                    raise Exception("Playwright 브라우저를 시작할 수 없습니다.")

                max_retries = 2
                for attempt in range(max_retries):
                    try:
                        page = browser.new_page()
                        page.goto(url, timeout=20000)

                        if selector:
                            try:
                                page.wait_for_selector(selector, timeout=20000)
                                time.sleep(3)
                            except Exception:
                                self.logger.warning(f"선택자 '{selector}' 요소를 기다리는 데 실패했습니다.")
                        else:
                            time.sleep(5)

                        html_content = page.content()
                        browser.close()
                        playwright.stop()
                        return html_content

                    except Exception as e:
                        if "timeout" in str(e).lower() and attempt < max_retries - 1:
                            self.logger.warning(f"페이지 로드 타임아웃 ({attempt + 1}/{max_retries}): {url} - 재시도 중...")
                            time.sleep(5)
                            continue
                        else:
                            browser.close()
                            playwright.stop()
                            raise e

        except Exception as e:
            self.logger.error(f"크롤링용 HTML 가져오기 실패: {url}, 오류: {e}")
            return None

    def create_playwright_browser(self):
        """Playwright 브라우저 인스턴스 생성"""
        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor"
                ]
            )
            self.logger.info("Playwright 브라우저 실행 성공")
            return playwright, browser
        except Exception as e:
            self.logger.error(f"Playwright 브라우저 실행 실패: {e}")
            return None, None

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

    def send_slack_notification(self, new_jobs: Dict, warnings: List, failed_companies: List, chunk_info: str = None):
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
            # 외국인 채용공고 개수 계산
            foreign_job_count = 0
            for jobs in new_jobs.values():
                foreign_job_count += sum(1 for job in jobs if self._is_foreign_job_posting(job))

            chunk_str = f"({chunk_info}) " if chunk_info else ""
            foreign_info = f" (외국인 채용: {foreign_job_count}개 🌍)" if foreign_job_count > 0 else ""
            header_msg = f"🎉 *새로운 채용공고 {total_new_jobs}개 발견!*{foreign_info} {chunk_str}({current_time})\n"

            current_message = header_msg
            for company, jobs in new_jobs.items():
                company_url = self.company_urls.get(company, "")
                linked_company = f"<{company_url}|{company}>" if company_url else company
                company_section = f"\n📢 *{linked_company}* - {len(jobs)}개\n"

                for job in jobs:
                    # 외국인 채용공고인지 확인하고 굵은 글씨로 표시
                    if self._is_foreign_job_posting(job):
                        company_section += f"• *{job}* 🌍\n"  # 굵은 글씨 + 지구 이모지
                    else:
                        company_section += f"• {job}\n"

                if len(current_message + company_section) > 3500:
                    messages_to_send.append(current_message.strip())
                    current_message = company_section
                else:
                    current_message += company_section

            if current_message.strip():
                messages_to_send.append(current_message.strip())

        if warnings:
            warning_msg = "⚠️ *확인이 필요한 공고* (홈페이지를 직접 확인해주세요)\n"
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
