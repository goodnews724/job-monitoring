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
        self.job_keywords = [
            '개발자', '엔지니어', '디자이너', '기획자', '매니저', 'PM', '팀장', '전문가', '담당자',
            'developer', 'engineer', 'designer', 'manager', 'planner', 'lead', 'specialist', 'analyst',
            # 직무 분야 추가
            '개발', '사업', 'R&D', '연구', '기술', '데이터', '보안', 'AI', '인공지능', '클라우드',
            '마케팅', '영업', '운영', '인사', '재무', '법무', 'UX', 'UI', '품질', 'QA',
            '컨설팅', '솔루션', '서비스', '플랫폼', '시스템', '네트워크', '인프라',
            # 채용 관련 키워드 추가
            '채용', '인턴', '체험형', '수시채용', '신입', '경력', '정규직', '계약직',
            'BM', '디자인', '생산직', '충포장', 'NEOPHARM'
        ]
        self.position_keywords = ['신입', '경력', '인턴', '정규직', '계약직']
        self.exclude_patterns = [
            r'^경력\s*\d+', r'^신입$', r'^인턴$', r'\d+년\s*이상', r'\d+년\s*이하',
            r'채용\s*프로세스', r'지원\s*방법', r'복리후생', r'기타\s*사항',
            r'관계사\s*선택', r'전체\s*선택', r'초기화', r'닫기', r'Contact',
            r'^[가-힣]+팀$', r'^[가-힣]+본부$', r'^[가-힣]+부문$'
        ]
        self.blacklist = ['nav', 'footer', 'header', 'menu', 'sitemap', 'aside', 'sidebar', 'breadcrumb']
        self.selector_blacklist = [
            'div.ViewFooterLink_link-text__yC2ls',  # 푸터 링크
            'p.official__apply__company__title',  # HD현대 회사명 목록 (채용공고 아님)
            'footer',
            'nav',
            '.footer',
            '.navbar',
            '.breadcrumb',
            '.copyright',
            '.privacy',
            '.terms'
        ]
        # DOM 구조 기반 필터링을 위한 영역 정의
        self.excluded_sections = ['nav', 'header', 'footer', 'aside', 'sidebar']
        self.ui_element_patterns = [
            r'(blog|youtube|facebook|instagram|twitter|linkedin)',  # 소셜미디어
            r'(바로가기|more|view|link|copy|share|공유)',  # 버튼/링크 텍스트
            r'(faq|q&a|notice|contact|about|문의|공지)',  # 정보성 메뉴
            r'^(talent|careers?|culture|people)$',  # 채용 관련 메뉴명
        ]
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

    def _is_potential_job_posting(self, text: str) -> bool:
        """텍스트가 채용공고일 가능성을 판단합니다."""
        # 길이 체크 - 한국어 채용공고는 짧을 수 있음
        if not (3 <= len(text) <= 150):  # 더 짧은 텍스트도 허용 (R&D 같은)
            return False

        # 회사명 패턴 제외 - HD현대 같은 케이스 대응
        company_name_patterns = [
            r'^(건설기계|HD현대\w*|HD\w+|현대\w*|삼성\w*|LG\w*|SK\w*|포스코\w*|롯데\w*|한화\w*|KT\w*|네이버\w*|카카오\w*|우아한\w*|배달의민족\w*|쿠팡\w*|토스\w*)$',  # 회사명
            r'^(\w+그룹|\w+홀딩스|\w+계열|\w+그룹사|\w+지주)$',  # 그룹사명
            r'^(\w+\s*주식회사|\w+\s*\(주\)|\w+\s*inc\.?|\w+\s*corp\.?|\w+\s*co\.?|\w+\s*ltd\.?)$',  # 법인명
            r'^(\w+오일뱅크|\w+텍|\w+솔루션|\w+시스템|\w+엔지니어링|\w+소프트|\w+테크|\w+랩|\w+스튜디오)$',  # 사업체명
        ]

        for pattern in company_name_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False

        # 추가 필터링: 날짜/시간/태그/상태 패턴들
        datetime_and_ui_patterns = [
            r'^\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2}.*$',  # 날짜시간 패턴
            r'^D-\d+.*$',  # D-8, D-1 같은 패턴
            r'^d-\d+.*$',  # d-8, d-1 같은 패턴 (소문자)
            r'^D-\d+$|^D-DAY$',  # 남은 일수 패턴
            r'^#[^#]+(\s+외\s*\d+)?$',  # 태그 패턴 (#분당(GRC) 외 10)
            r'^[가-힣]+\s*등$',  # "조선해양 등" 패턴
            r'^[가-힣]{2,6}$',  # 짧은 한글 단어 (회사명/부서명)
            r'^\d+\s*외\s*\d+$',  # "10 외 3" 패턴
        ]

        for pattern in datetime_and_ui_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False

        # 제외 패턴 체크 - UI 요소들 추가
        ui_elements = [
            r'^(경력\s*\d+.*년|신입|인턴|정규직|계약직|인재풀)$',  # 필터 항목들
            r'^(채용\s*FAQ|지원서\s*작성|마이페이지|공지사항|홍보영상|CEO\s*메시지|채용\s*Q&A|지원서\s*수정|인재상|경영이념|인재육성|복리후생)$',  # 메뉴 항목들
            r'^(자율\s*복장|점심시간|연차|간식|건강검진|동호회|인센티브|시차출퇴근|임신기|맛있는|1시간|8시~10시).*$',  # 복리후생
            r'^(DESIGN|SALES|PRODUCT|STORE|STAFF|GLOBAL|CX|SCM|OFF-SALES|CEO\s*STAFF)$',  # 부서명만
            r'^(Tech|마케팅/홍보|경영지원|디자인|콘텐츠\s*비즈니스)$',  # 카테고리명
            r'^\-$',  # 단순 대시
            r'^(경력\s*무관|경력\s*\d+~\d+년|경력\s*\d+년\s*이상|베리시.*스토어)$',  # 기타 필터들
            r'^(개인정보\s*처리방침|이용약관|저작권|All\s*Rights\s*Reserved|Copyright).*$',  # 푸터 관련
            r'^(사이트맵|Contact\s*Us|고객센터|문의|안내)$',  # 네비게이션
            r'^(#[가-힣]+|#[가-힣]+\([^)]+\)|#ICT|#연구|#영업|#설계|#생산직|#대산|#분당).*$',  # 해시태그들
            # 네비게이션 링크 패턴 추가
            r'^(.*\s*바로가기\s*≫?)$',  # "채용공고 바로가기 ≫", "직무소개 바로가기" 등
            r'^(.*\s*바로가기)$',  # "채용공고 바로가기" 등
            r'^(채용정보|직무소개|복리후생|기업문화|회사소개|오시는길|Contact|문의하기)\s*(바로가기)?.*$',  # 주요 네비게이션 메뉴들
        ]

        # 새로 추가된 UI 요소 패턴들 적용
        for pattern in self.ui_element_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False

        for pattern in self.exclude_patterns + ui_elements:
            if re.search(pattern, text, re.IGNORECASE):
                return False
        
        # 직무 키워드 포함 여부
        has_job_keyword = any(keyword in text for keyword in self.job_keywords)
        
        # 직무명 + 직책 패턴 (예: "백엔드 개발자", "UI/UX 디자이너") 
        job_title_pattern = r'(백엔드|프론트엔드|풀스택|모바일|웹|UI/UX|그래픽|브랜드|마케팅|데이터|AI|ML|DevOps|QA|기획|운영|영업|HR|재무|법무|개발자|디자이너|엔지니어|매니저|기획자|사이언티스트)'
        has_job_pattern = bool(re.search(job_title_pattern, text))
        
        # 최소 조건: 직무 관련 키워드나 패턴이 있어야 함
        # 또는 채용 페이지/섹션에 있는 짧은 텍스트들도 허용 (3-15글자)
        if not (has_job_keyword or has_job_pattern):
            # 짧은 텍스트이고 한글+영문+&기호만 포함된 경우 허용 (직무명일 가능성)
            if len(text) <= 15 and re.match(r'^[가-힣a-zA-Z&\s]+$', text.strip()):
                pass  # 허용
            else:
                return False
            
        # 단순한 팀명이나 부서명 제외 (끝에 '팀', '본부', '부문'으로 끝나는 것들)
        if re.search(r'^[\가-힣]+팀$|^[\가-힣]+본부$|^[\가-힣]+부문$', text):
            return False
            
        return True

    def _calculate_job_posting_weight(self, text: str) -> float:
        """채용공고일 가능성에 따른 가중치를 계산합니다."""
        weight = 1.0
        
        # 실제 채용공고 제목 패턴들에 높은 가중치
        job_title_patterns = [
            r'.*(개발자|엔지니어|디자이너|기획자|매니저|전문가|담당자|팀장|부장|대리|과장|주임)',
            r'.*(백엔드|프론트엔드|풀스택|모바일|웹|UI/UX|DevOps|QA)',
            r'.*(시니어|주니어|신입|경력).*채용',
            r'(프로덕트|서비스|비즈니스|콘텐츠).*\s+(기획|개발|운영)',
            r'.*채용.*\s+(전형|공고)',  # "신입사원 채용 I'M전형" 같은 패턴
            r'.*\s+(인턴|체험형).*',    # 인턴 채용
        ]
        
        for pattern in job_title_patterns:
            if re.search(pattern, text):
                weight += 3.0  # 가중치 증가
                break
        
        # 회사명이 포함된 경우 (예: [NEOPHARM], [SNOW])
        if re.search(r'\[.*\]', text):
            weight += 2.0
            
        # 연도가 포함된 경우 (예: 2025년)
        if re.search(r'20\d{2}년', text):
            weight += 2.0
        
        # 회사명이나 구체적인 직무가 포함된 경우
        if any(keyword in text for keyword in ['팀', '센터', '본부', '사업부']):
            weight += 1.0
            
        # 길이에 따른 가중치 - 채용공고 제목은 보통 길다
        if 15 <= len(text) <= 80:
            weight += 2.0
        elif 10 <= len(text) < 15:
            weight += 1.0
        elif len(text) < 8:
            weight -= 1.0
            
        return weight

    def _filter_valid_job_titles(self, titles: List[str]) -> List[str]:
        """채용공고 제목을 필터링합니다."""
        valid_titles = []
        for title in titles:
            if self._is_potential_job_posting(title):
                # 중복 제거 (유사한 제목들)
                if not any(self._is_similar_title(title, existing) for existing in valid_titles):
                    valid_titles.append(title)
        return valid_titles

    def _is_similar_title(self, title1: str, title2: str) -> bool:
        """두 제목이 유사한지 판단합니다."""
        # 길이가 매우 다르면 다른 제목
        if abs(len(title1) - len(title2)) > min(len(title1), len(title2)) * 0.5:
            return False
        
        # 공통 단어 비율 체크
        words1 = set(title1.split())
        words2 = set(title2.split())
        common_words = words1.intersection(words2)
        
        if not common_words:
            return False
        
        similarity = len(common_words) / max(len(words1), len(words2))
        return similarity > 0.7

    def _validate_selector(self, soup: BeautifulSoup, selector: str) -> Optional[List[str]]:
        """기존 선택자의 유효성을 검사합니다."""
        try:
            elements = soup.select(selector)
            if not elements:
                return None
            
            titles = [elem.get_text(strip=True) for elem in elements]
            valid_titles = self._filter_valid_job_titles(titles)
            
            if len(valid_titles) >= 2:
                return valid_titles
            else:
                return None
        except Exception:
            return None

    def _find_job_posting_containers(self, soup: BeautifulSoup) -> List[Tuple[str, List[str]]]:
        """채용공고 전용 컨테이너를 찾습니다."""
        job_container_patterns = [
            # ID 기반 패턴
            r'job|recruit|career|position|opening|notice|list',
            # 클래스 기반 패턴
            r'job|recruit|career|position|opening|notice|list|bbs'
        ]

        potential_containers = []

        # 1. ID 기반 컨테이너 우선 검색
        for element in soup.find_all(attrs={'id': True}):
            element_id = element.get('id', '').lower()
            if any(re.search(pattern, element_id, re.IGNORECASE) for pattern in job_container_patterns):
                # 이 컨테이너 안에서 채용공고 링크 찾기
                job_links = []
                for link in element.find_all('a', href=True):
                    text = link.get_text(strip=True)
                    if self._is_potential_job_posting(text) and len(text) > 10:
                        job_links.append(text)

                if len(job_links) >= 1:  # 최소 1개 이상
                    # 더 구체적인 선택자 생성
                    specific_selectors = self._generate_specific_selectors(element, job_links, soup)
                    for selector, titles in specific_selectors:
                        potential_containers.append((selector, titles))

        # 2. 클래스 기반 컨테이너 검색
        for element in soup.find_all(attrs={'class': True}):
            classes = ' '.join(element.get('class', [])).lower()
            if any(re.search(pattern, classes, re.IGNORECASE) for pattern in job_container_patterns):
                # 이 컨테이너 안에서 채용공고 링크 찾기
                job_links = []
                for link in element.find_all('a', href=True):
                    text = link.get_text(strip=True)
                    if self._is_potential_job_posting(text) and len(text) > 10:
                        job_links.append(text)

                if len(job_links) >= 1:
                    specific_selectors = self._generate_specific_selectors(element, job_links, soup)
                    for selector, titles in specific_selectors:
                        potential_containers.append((selector, titles))

        return potential_containers

    def _generate_specific_selectors(self, container, job_links: List[str], soup: BeautifulSoup) -> List[Tuple[str, List[str]]]:
        """컨테이너 내에서 구체적인 선택자를 생성합니다."""
        selectors = []

        # 컨테이너 선택자 생성
        container_selector = self._get_element_selector(container)

        # 채용공고 링크들의 공통 경로 찾기
        job_link_elements = []
        for link in container.find_all('a', href=True):
            text = link.get_text(strip=True)
            if text in job_links:
                job_link_elements.append(link)

        if not job_link_elements:
            return selectors

        # 공통 부모-자식 관계 패턴 찾기
        common_patterns = self._find_common_path_patterns(job_link_elements, container)

        for pattern in common_patterns:
            full_selector = f"{container_selector} {pattern}"
            try:
                # 선택자 검증
                elements = soup.select(full_selector)
                titles = [elem.get_text(strip=True) for elem in elements]
                # 채용공고만 필터링
                valid_titles = [t for t in titles if self._is_potential_job_posting(t) and len(t) > 10]

                if len(valid_titles) >= 1:
                    selectors.append((full_selector, valid_titles))
            except Exception:
                continue

        return selectors

    def _get_element_selector(self, element) -> str:
        """요소의 CSS 선택자를 생성합니다."""
        if element.get('id'):
            return f"#{element.get('id')}"
        elif element.get('class'):
            classes = '.'.join(element.get('class'))
            return f"{element.name}.{classes}"
        else:
            return element.name

    def _find_common_path_patterns(self, elements: List, container) -> List[str]:
        """요소들의 공통 경로 패턴을 찾습니다."""
        patterns = set()

        for element in elements:
            # 요소까지의 경로 생성
            path_parts = []
            current = element

            while current and current != container and current.parent:
                if current.name == 'a':
                    path_parts.append('a')
                elif current.get('class'):
                    classes = '.'.join(current.get('class'))
                    path_parts.append(f"{current.name}.{classes}")
                else:
                    path_parts.append(current.name)
                current = current.parent

            if path_parts:
                path_parts.reverse()
                patterns.add(' '.join(path_parts))

        return list(patterns)

    def find_best_selector(self, soup: BeautifulSoup) -> Tuple[Optional[str], List[str]]:
        # 1. 새로운 알고리즘 우선 적용: 구체적인 채용공고 컨테이너 찾기
        specific_containers = self._find_job_posting_containers(soup)
        if specific_containers:
            # 가장 많은 채용공고를 찾은 선택자 반환
            best_container = max(specific_containers, key=lambda x: len(x[1]))
            if len(best_container[1]) >= 1:
                return best_container[0], best_container[1]

        # 2. 기존 알고리즘으로 폴백
        # 먼저 링크 텍스트를 우선으로 검사
        link_elements = []
        for link in soup.find_all('a', href=True):
            if any(parent.name in self.blacklist or any(b in (parent.get('class', []) + ([parent.get('id')] if parent.get('id') else [])) for b in self.blacklist) for parent in link.find_parents()):
                continue

            text = link.get_text(strip=True)
            if self._is_potential_job_posting(text) and len(text) > 5:  # 링크 조건 완화
                link_elements.append(link)
        
        # 링크에서 충분한 채용공고를 찾았으면 링크 우선 사용
        if len(link_elements) >= 2:
            potential_elements = link_elements
        else:
            # 2. 일반 요소들도 검사
            potential_elements = []
            for element in soup.find_all(['p', 'div', 'span', 'a', 'strong', 'h2', 'h3', 'h4', 'li', 'dt', 'td']):
                if any(parent.name in self.blacklist or any(b in (parent.get('class', []) + ([parent.get('id')] if parent.get('id') else [])) for b in self.blacklist) for parent in element.find_parents()):
                    continue
                
                text = element.get_text(strip=True)
                if self._is_potential_job_posting(text):
                    potential_elements.append(element)
            
            # 링크 요소들도 추가
            potential_elements.extend(link_elements)

        if len(potential_elements) < 2:
            return None, []

        # 가중치 기반 부모 컨테이너 선택
        parent_scores = {}
        for element in potential_elements:
            text = element.get_text(strip=True)
            weight = self._calculate_job_posting_weight(text)
            
            for parent in element.find_parents(limit=3):
                if parent not in parent_scores:
                    parent_scores[parent] = 0
                parent_scores[parent] += weight
        
        if not parent_scores:
            return None, []

        # 점수가 가장 높은 컨테이너 선택
        container = max(parent_scores.items(), key=lambda x: x[1])[0]

        child_selector_counter = Counter()
        for element in potential_elements:
            if container in element.find_parents():
                # 더 구체적인 선택자 생성
                tag = element.name
                classes = element.get('class', [])
                element_id = element.get('id', '')

                # 구체적인 선택자 만들기
                if element_id:
                    # ID가 있으면 ID 사용
                    selector_key = f"{tag}#{element_id}"
                elif classes:
                    # 클래스가 있으면 클래스 사용
                    class_str = '.' + '.'.join(sorted(classes))
                    selector_key = f"{tag}{class_str}"
                else:
                    # 클래스나 ID가 없으면 부모와의 관계로 구체화
                    parent = element.parent
                    if parent and parent != container:
                        parent_tag = parent.name
                        parent_classes = parent.get('class', [])
                        if parent_classes:
                            parent_class_str = '.' + '.'.join(sorted(parent_classes))
                            selector_key = f"{parent_tag}{parent_class_str} > {tag}"
                        else:
                            selector_key = f"{parent_tag} > {tag}"
                    else:
                        # 최후의 수단: 태그명 + 속성
                        attrs = []
                        if element.get('href'):
                            attrs.append('[href]')
                        if element.get('title'):
                            attrs.append('[title]')
                        if attrs:
                            selector_key = f"{tag}{''.join(attrs)}"
                        else:
                            # 정말 마지막에만 태그명만 사용
                            selector_key = tag

                child_selector_counter[selector_key] += 1

        if not child_selector_counter:
            return None, []

        # 가장 구체적인 선택자 우선 선택
        best_child_selector = None
        for selector, count in child_selector_counter.most_common():
            # 단순 태그명은 피하고 더 구체적인 것 선택
            if ('.' in selector or '#' in selector or '>' in selector or '[' in selector):
                best_child_selector = selector
                break

        # 구체적인 선택자가 없으면 가장 많이 사용된 것 사용
        if not best_child_selector:
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
                if count < 2: continue
                try:
                    texts = [elem.get_text(strip=True) for elem in soup.select(selector)]
                    if not texts: continue
                    
                    valid_texts = [t for t in texts if 10 < len(t) < 150]
                    if len(valid_texts) < 2: continue

                    avg_len = sum(len(t) for t in valid_texts) / len(valid_texts)
                    
                    keyword_score = sum(1 for t in valid_texts if any(re.search(k, t, re.IGNORECASE) for k in self.job_keywords))
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

        # 최종 선택자 검증 및 반환
        def is_specific_selector(selector):
            """선택자가 충분히 구체적인지 확인"""
            return ('.' in selector or '#' in selector or '>' in selector or '[' in selector or ':' in selector)

        def is_blacklisted_selector(selector):
            """선택자가 블랙리스트에 있는지 확인"""
            # 기본 블랙리스트
            for blacklisted in self.selector_blacklist:
                if blacklisted in selector:
                    return True

            # 너무 일반적인 선택자들 금지
            generic_selectors = [
                'a[href]',  # 모든 링크
                'a',        # 모든 링크
                'div > a',  # 너무 일반적
                'li > a',   # 너무 일반적 (하지만 구체적인 컨텍스트가 있으면 허용)
                'td > a',   # 너무 일반적
                'p > a',    # 너무 일반적
                'tr > td',  # 너무 일반적
                'ul > li',  # 너무 일반적
                'div > p',  # 너무 일반적
                'li',       # 너무 일반적
                'td',       # 너무 일반적
                'dt',       # 너무 일반적
            ]

            # 단순히 태그만 있는 선택자는 금지
            if selector.strip() in generic_selectors:
                return True

            return False

        def clean_selector(selector):
            """선택자에서 마지막 요소의 nth-child만 제거하여 전체 목록을 가져올 수 있게 함"""
            # 선택자를 > 기준으로 분할
            parts = selector.split(' > ')
            if parts:
                # 마지막 요소에서만 nth-child/nth-of-type 제거
                parts[-1] = re.sub(r':nth-child\(\d+\)', '', parts[-1])
                parts[-1] = re.sub(r':nth-of-type\(\d+\)', '', parts[-1])
                cleaned = ' > '.join(parts)
            else:
                # 공백으로 분리된 경우 (> 없는 경우)
                parts = selector.split()
                if parts:
                    parts[-1] = re.sub(r':nth-child\(\d+\)', '', parts[-1])
                    parts[-1] = re.sub(r':nth-of-type\(\d+\)', '', parts[-1])
                    cleaned = ' '.join(parts)
                else:
                    cleaned = selector

            # 연속된 공백 정리
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            # > 앞뒤 공백 정리
            cleaned = re.sub(r'\s*>\s*', ' > ', cleaned)
            return cleaned

        def validate_job_selector(selector, soup):
            """선택자가 실제 채용공고를 가져오는지 검증"""
            try:
                elements = soup.select(selector)
                if not elements:
                    return None, []

                titles = [elem.get_text(strip=True) for elem in elements]
                valid_titles = [t for t in titles if len(t) > 5]

                if len(valid_titles) >= 2:
                    # 채용공고 관련성 검사
                    job_related_count = sum(1 for t in valid_titles if self._is_potential_job_posting(t))
                    if job_related_count >= 1:  # 최소 1개 이상의 채용공고
                        return selector, valid_titles

                return None, []
            except Exception:
                return None, []

        # 1. final_selector 검증
        if final_selector and is_specific_selector(final_selector) and not is_blacklisted_selector(final_selector):
            cleaned_final = clean_selector(final_selector)
            result_selector, result_titles = validate_job_selector(cleaned_final, soup)
            if result_selector:
                return result_selector, result_titles

        # 2. best_child_selector 검증
        if best_child_selector and is_specific_selector(best_child_selector) and not is_blacklisted_selector(best_child_selector):
            cleaned_best = clean_selector(best_child_selector)
            result_selector, result_titles = validate_job_selector(cleaned_best, soup)
            if result_selector:
                return result_selector, result_titles

        # 구체적인 선택자를 찾지 못한 경우 None 반환
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
        
        for idx, (_, row) in enumerate(companies_df.iterrows(), 1):
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