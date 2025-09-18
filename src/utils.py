import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
from typing import Optional

def stabilize_selector(selector, conservative=True):
    """선택자를 안정적인 형태로 변환합니다."""
    if pd.isna(selector):
        return selector


    if conservative:
        # 보수적 모드: 최소한의 안정화만 수행
        # 1. 확실한 동적 ID만 제거 (UUID 형태 + 추가로 랜덤한 숫자/문자가 많은 경우)
        # UUID가 아닌 일반적인 긴 ID는 보존
        uuid_pattern = r'#[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}(?=\s|>|$)'
        if re.search(uuid_pattern, selector):
            # UUID 다음에 바로 공백이나 >가 오는 경우만 제거 고려
            # 하지만 실제로는 제거하지 않고 보존 (정답에서 유효할 수 있음)
            pass

        # 2. nth-child는 보존 (정답에서 많이 사용됨)

        # 3. 공백만 정리
        selector = re.sub(r'\s+', ' ', selector).strip()
        selector = re.sub(r'\s*>', ' > ', selector)

    else:
        # 기존 적극적 모드
        # 1. 동적 ID 제거
        selector = re.sub(r'#[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\s*>', '', selector)

        # 2. 모든 nth-child 제거
        selector = re.sub(r':nth-child\(\d+\)', '', selector)

        # 3. 공백 정리
        selector = re.sub(r'\s+', ' ', selector).strip()
        selector = re.sub(r'\s*>', ' > ', selector)

    return selector

class SeleniumRequirementChecker:
    """채용공고 URL에 대해 Selenium 필요 여부를 판별하는 클래스"""
    
    def __init__(self, timeout: int = 15, delay: float = 0.5):
        self.timeout = timeout
        self.delay = delay
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def check_selenium_requirement(self, url: str, selector: Optional[str] = None) -> bool:
        """
        URL과 CSS 선택자를 기준으로 Selenium 필요 여부를 판별
        """
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            if "greetinghr.com" in url:
                return self._check_greetinghr(url, soup)
            
            return self._check_general_selector(url, selector, soup)
            
        except requests.exceptions.RequestException:
            return True
        except Exception:
            return True
        finally:
            time.sleep(self.delay)
    
    def _check_greetinghr(self, _: str, soup: BeautifulSoup) -> bool:
        link_element = soup.select_one('a[href^="/ko/o/"]')
        return False if link_element else True

    def _check_general_selector(self, _: str, selector: Optional[str], soup: BeautifulSoup) -> bool:
        # SPA/JavaScript 앱 감지
        if self._is_spa_site(soup):
            return True
            
        if pd.isna(selector) or not selector:
            return True
        
        element = soup.select_one(selector)
        return False if element else True
    
    def _is_spa_site(self, soup: BeautifulSoup) -> bool:
        """SPA(Single Page Application) 사이트인지 감지"""
        
        body = soup.find('body')
        body_text = body.get_text(strip=True) if body else ""
        
        # 1. React/Next.js/Vue 등의 강력한 SPA 지표
        strong_spa_indicators = [
            '__next', 'buildId', '__NEXT_DATA__',  # Next.js
            'reactroot', 'react-root',            # React
            '__vue__', '__nuxt__',                # Vue/Nuxt
            'ng-app', 'ng-version'                # Angular
        ]
        
        html_content = str(soup).lower()
        strong_indicators_found = [ind for ind in strong_spa_indicators if ind in html_content]
        
        # 강력한 지표가 있으면서 body 텍스트가 적으면 SPA
        if strong_indicators_found and len(body_text) < 500:
            return True
            
        # 2. 극도로 적은 body 내용 + 많은 스크립트 = SPA
        scripts = soup.find_all('script')
        if len(body_text) < 50 and len(scripts) > 5:
            return True
            
        # 3. 특정 패턴: body가 거의 비어있고 script/div만 있는 구조
        if body:
            body_children = [child for child in body.children if hasattr(child, 'name') and child.name]
            meaningful_children = [child for child in body_children if child.name not in ['script', 'noscript']]
            
            # script를 제외한 의미있는 요소가 3개 이하이면서 body 텍스트가 적으면 SPA
            if len(meaningful_children) <= 3 and len(body_text) < 100:
                return True
        
        return False