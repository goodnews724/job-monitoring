import os
import pandas as pd
from bs4 import BeautifulSoup
from collections import Counter
import re
from typing import List, Tuple, Optional, Dict, Set
import logging

class JobPostingSelectorAnalyzer:
    """채용공고 선택자 분석기 (공유 캐시 기능 추가)"""
    
    def __init__(self):
        self.keywords = [
            '경력', '신입', '인턴', '채용', '모집', '개발', '디자인', '기획',
            '마케팅', '엔지니어', '매니저', '리드', '운영', '데이터', '담당자',
            'engineer', 'designer', 'manager', 'developer', 'marketing', 'data', 'product', 'QA', 'PM'
        ]
        self.blacklist = ['nav', 'footer', 'header', 'menu', 'sitemap', 'aside', 'sidebar']
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _validate_selector(self, soup: BeautifulSoup, selector: str) -> Optional[List[str]]:
        """기존 선택자의 유효성을 검사합니다."""
        try:
            elements = soup.select(selector)
            if not elements:
                return None
            
            titles = [elem.get_text(strip=True) for elem in elements]
            valid_titles = [t for t in titles if 10 < len(t) < 150]
            
            if len(valid_titles) >= 3:
                return valid_titles
            else:
                return None
        except Exception:
            return None

    def find_best_selector(self, soup: BeautifulSoup) -> Tuple[Optional[str], List[str]]:
        potential_elements = []
        for element in soup.find_all(['p', 'div', 'span', 'a', 'strong', 'h2', 'h3', 'h4', 'li', 'dt', 'td']):
            if any(parent.name in self.blacklist or any(b in (parent.get('class', []) + ([parent.get('id')] if parent.get('id') else [])) for b in self.blacklist) for parent in element.find_parents()):
                continue
            
            text = element.get_text(strip=True)
            if any(re.search(keyword, text, re.IGNORECASE) for keyword in self.keywords) and 5 < len(text) < 150:
                potential_elements.append(element)

        if len(potential_elements) < 3:
            return None, []

        parent_counter = Counter()
        for element in potential_elements:
            for i, parent in enumerate(element.find_parents(limit=3)):
                parent_counter[parent] += 1
        
        if not parent_counter:
            return None, []

        container = parent_counter.most_common(1)[0][0]

        child_selector_counter = Counter()
        for element in potential_elements:
            if container in element.find_parents():
                direct_child = element
                while direct_child.find_parent() != container and direct_child.find_parent() is not None:
                    direct_child = direct_child.find_parent()
                
                if direct_child and direct_child.name:
                    tag = direct_child.name
                    classes = '.' + '.'.join(sorted(direct_child.get('class', []))) if direct_child.get('class') else ''
                    child_selector_counter[f"{tag}{classes}"] += 1

        if not child_selector_counter:
            return None, []

        best_child_selector = child_selector_counter.most_common(1)[0][0]
        
        container_tag = container.name
        container_classes = '.' + '.'.join(sorted(container.get('class', []))) if container.get('class') else ''
        
        final_selector_candidates = Counter()
        try:
            for element in soup.select(f"{container_tag}{container_classes} > {best_child_selector}"):
                for p_elem in element.find_all(['p', 'strong', 'h2', 'h3', 'h4', 'div']):
                     if p_elem.get('class'):
                         cls = '.' + '.'.join(p_elem.get('class'))
                         final_selector_candidates[f"{best_child_selector} {p_elem.name}{cls}"] += 1
        except Exception:
            pass

        if not final_selector_candidates:
             final_selector = best_child_selector
        else:
            best_selector_str = None
            max_score = -1
            for selector, count in final_selector_candidates.most_common():
                if count < 3: continue
                try:
                    texts = [elem.get_text(strip=True) for elem in soup.select(selector)]
                    if not texts: continue
                    
                    valid_texts = [t for t in texts if 10 < len(t) < 150]
                    if len(valid_texts) < 3: continue

                    avg_len = sum(len(t) for t in valid_texts) / len(valid_texts)
                    
                    keyword_score = sum(1 for t in valid_texts if any(re.search(k, t, re.IGNORECASE) for k in self.keywords))
                    keyword_ratio = keyword_score / len(valid_texts)
                    
                    score = avg_len * keyword_ratio

                    if score > max_score:
                        max_score = score
                        best_selector_str = selector
                except Exception:
                    continue
            
            if best_selector_str:
                final_selector = best_selector_str
            else:
                final_selector = final_selector_candidates.most_common(1)[0][0]

        try:
            titles = [elem.get_text(strip=True) for elem in soup.select(final_selector)]
            valid_titles = [t for t in titles if len(t) > 5]

            if len(valid_titles) >= 3:
                return final_selector, valid_titles
        except Exception:
            pass

        try:
            titles = [t.get_text(strip=True) for t in soup.select(best_child_selector)]
            valid_titles = [t for t in titles if len(t) > 5]
            if len(valid_titles) >= 3:
                return best_child_selector, valid_titles
        except Exception:
            return None, []

        return None, []

class ConfigManager:
    def __init__(self, config_path: str, html_dir: str):
        self.config_path = config_path
        self.html_dir = html_dir
        self.analyzer = JobPostingSelectorAnalyzer()
        self.logger = logging.getLogger(__name__)
        self.verified_selector_cache: Set[str] = set()
    
    def update_selectors(self) -> bool:
        try:
            df_config = pd.read_csv(self.config_path)
        except FileNotFoundError:
            self.logger.error(f"설정 파일 '{self.config_path}'을(를) 찾을 수 없습니다.")
            return False

        # 선택자가 없는 회사만 필터링
        companies_without_selector = df_config[
            df_config['selector'].isna() | 
            (df_config['selector'].str.strip() == '') |
            df_config['selector'].isnull()
        ]
        
        if companies_without_selector.empty:
            print("=" * 60)
            print("모든 회사에 이미 선택자가 설정되어 있습니다.")
            print("=" * 60)
            return True
        
        print("=" * 60)
        print(f"선택자가 없는 {len(companies_without_selector)}개 회사 분석 시작")
        print("=" * 60)
        
        analyzed_selectors = self._analyze_html_files(companies_without_selector)
        
        # 결과를 원본 DataFrame에 반영
        for company_name, selector in analyzed_selectors.items():
            df_config.loc[df_config['회사명'] == company_name, 'selector'] = selector

        self._save_config(df_config)
        self._print_summary(analyzed_selectors, len(companies_without_selector))
        return True

    def _analyze_html_files(self, companies_df: pd.DataFrame) -> Dict[str, str]:
        analyzed_selectors = {}
        
        for idx, (index, row) in enumerate(companies_df.iterrows(), 1):
            company_name = row['회사명']
            print(f"\n[{idx}/{len(companies_df)}] {company_name} 분석 중...")
            
            html_file_path = os.path.join(self.html_dir, f"{company_name}.html")
            if not os.path.exists(html_file_path):
                print(f"  ❌ HTML 파일이 없어 건너뜁니다.")
                continue
            
            try:
                with open(html_file_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f, 'html.parser')
                
                # 1단계: 이번 실행에서 검증된 공유 캐시 확인
                is_cached = False
                for cached_selector in self.verified_selector_cache:
                    found_titles = self.analyzer._validate_selector(soup, cached_selector)
                    if found_titles:
                        print(f"  ✅ [공유 캐시 적중] 다른 회사에서 검증된 선택자 '{cached_selector}'를 사용합니다.")
                        analyzed_selectors[company_name] = cached_selector
                        for title in found_titles[:3]:
                            print(f"    - {title}")
                        is_cached = True
                        break
                
                if is_cached:
                    continue

                # 2단계: 새로운 분석 실행
                print("  🔍 새로 분석을 시작합니다...")
                best_selector, found_titles = self.analyzer.find_best_selector(soup)
                
                if best_selector and found_titles:
                    print(f"  ✅ 성공! 새로운 선택자: '{best_selector}'")
                    analyzed_selectors[company_name] = best_selector
                    self.verified_selector_cache.add(best_selector)
                    for title in found_titles[:3]:
                        print(f"    - {title}")
                else:
                    print("  ❌ 분석 실패: 유효한 패턴을 찾지 못했습니다.")
                    
            except Exception as e:
                self.logger.error(f"  ❌ {company_name} 분석 중 오류: {e}")
                
        return analyzed_selectors

    def _save_config(self, df_config: pd.DataFrame) -> bool:
        try:
            df_config.to_csv(self.config_path, index=False, encoding='utf-8-sig')
            print(f"\n💾 분석 결과를 '{self.config_path}'에 저장했습니다.")
            return True
        except Exception as e:
            self.logger.error(f"설정 파일 저장 중 오류: {e}")
            return False

    def _print_summary(self, analyzed_selectors: Dict[str, str], total_companies: int):
        print("\n" + "=" * 60)
        print("📊 분석 결과 요약")
        print("=" * 60)
        print(f"  분석 대상 회사: {total_companies}개")
        print(f"  성공적으로 분석된 회사: {len(analyzed_selectors)}개")
        print(f"  실패한 회사: {total_companies - len(analyzed_selectors)}개")
        
        if analyzed_selectors:
            print(f"\n🎯 발견된 선택자 예시:")
            for company, selector in list(analyzed_selectors.items())[:5]:
                print(f"    - {company}: {selector}")
        
        print(f"\n🎉 선택자가 없던 회사들의 분석이 완료되었습니다!")

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_manager = ConfigManager(
        os.path.join(base_dir, 'data', '채용공고_목록.csv'), 
        os.path.join(base_dir, 'html')
    )
    if not config_manager.update_selectors():
        print("\n❌ 일부 작업에서 오류가 발생했습니다.")

if __name__ == "__main__":
    main()