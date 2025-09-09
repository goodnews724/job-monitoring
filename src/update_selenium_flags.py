import pandas as pd
import requests
from bs4 import BeautifulSoup
import numpy as np
import os
from typing import Optional, Union
import time

class SeleniumRequirementChecker:
    """채용공고 URL에 대해 Selenium 필요 여부를 판별하는 클래스"""
    
    def __init__(self, timeout: int = 15, delay: float = 0.5):
        self.timeout = timeout
        self.delay = delay  # 요청 간 지연시간
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def check_selenium_requirement(self, url: str, selector: Optional[str] = None) -> bool:
        """
        URL과 CSS 선택자를 기준으로 Selenium 필요 여부를 판별
        
        Args:
            url: 확인할 URL
            selector: CSS 선택자 (선택적)
            
        Returns:
            bool: Selenium이 필요하면 True, 불필요하면 False
        """
        try:
            print(f"확인 중: {url}")
            
            # HTTP 요청
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # GreetingHR 특별 처리
            if "greetinghr.com" in url:
                return self._check_greetinghr(url, soup)
            
            # 일반적인 선택자 확인
            return self._check_general_selector(url, selector, soup)
            
        except requests.exceptions.RequestException as e:
            print(f"  ❌ 요청 실패: {e}")
            return True
        except Exception as e:
            print(f"  ❌ 예상치 못한 오류: {e}")
            return True
        finally:
            # 요청 간 지연
            time.sleep(self.delay)
    
    def _check_greetinghr(self, url: str, soup: BeautifulSoup) -> bool:
        """GreetingHR 사이트 전용 확인 로직"""
        link_element = soup.select_one('a[href^="/ko/o/"]')
        
        if link_element:
            print("  ✅ [GreetingHR] 링크 발견 - Selenium 불필요")
            return False
        else:
            print("  ⚠️ [GreetingHR] 링크 미발견 - Selenium 필요")
            return True
    
    def _check_general_selector(self, url: str, selector: Optional[str], soup: BeautifulSoup) -> bool:
        """일반적인 CSS 선택자 확인 로직"""
        if pd.isna(selector) or not selector:
            print("  ⚠️ 선택자 없음 - Selenium 필요")
            return True
        
        element = soup.select_one(selector)
        
        if element:
            print("  ✅ 요소 발견 - Selenium 불필요")
            return False
        else:
            print("  ⚠️ 요소 미발견 - Selenium 필요")
            return True

class ConfigUpdater:
    """CSV 설정 파일을 업데이트하는 클래스"""
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.checker = SeleniumRequirementChecker()
    
    def load_config(self) -> Optional[pd.DataFrame]:
        """설정 파일 로드"""
        try:
            df = pd.read_csv(
                self.config_path,
                keep_default_na=True,
                na_values=['', ' ', 'nan', 'NaN', 'null']
            )
            
            # selenium_required 컬럼이 없으면 추가
            if 'selenium_required' not in df.columns:
                df['selenium_required'] = np.nan
                print("selenium_required 컬럼을 새로 생성했습니다.")
            
            return df
            
        except FileNotFoundError:
            print(f"❌ 설정 파일을 찾을 수 없습니다: {self.config_path}")
            return None
        except Exception as e:
            print(f"❌ 파일 로드 중 오류 발생: {e}")
            return None
    
    def save_config(self, df: pd.DataFrame) -> bool:
        """설정 파일 저장"""
        try:
            df.to_csv(self.config_path, index=False, encoding='utf-8-sig')
            print(f"✅ 설정 파일이 성공적으로 저장되었습니다: {self.config_path}")
            return True
        except Exception as e:
            print(f"❌ 파일 저장 중 오류 발생: {e}")
            return False
    
    def update_selenium_flags(self) -> bool:
        """비어있는 selenium_required 컬럼만 업데이트"""
        print("=" * 60)
        print("Selenium 필요 여부 확인 시작")
        print("=" * 60)
        
        # 설정 파일 로드
        df_config = self.load_config()
        if df_config is None:
            return False
        
        # 업데이트가 필요한 행 찾기
        needs_update = df_config['selenium_required'].isna()
        update_count = needs_update.sum()
        
        if update_count == 0:
            print("\n✅ 모든 항목이 이미 확인되었습니다. 업데이트할 내용이 없습니다.")
            return True
        
        print(f"\n📋 총 {len(df_config)}개 항목 중 {update_count}개 항목을 확인합니다.\n")
        
        # 업데이트 진행
        updated_count = 0
        for index, row in df_config[needs_update].iterrows():
            try:
                url = row['채용공고 URL']
                selector = row.get('selector', None)
                
                print(f"[{updated_count + 1}/{update_count}]", end=" ")
                
                selenium_required = self.checker.check_selenium_requirement(url, selector)
                df_config.at[index, 'selenium_required'] = selenium_required
                updated_count += 1
                
            except Exception as e:
                print(f"  ❌ 처리 중 오류 발생: {e}")
                df_config.at[index, 'selenium_required'] = True  # 기본값으로 True 설정
        
        # 결과 저장
        print("\n" + "=" * 60)
        print(f"작업 완료: {updated_count}개 항목이 업데이트되었습니다.")
        
        success = self.save_config(df_config)
        
        if success:
            # 결과 요약 출력
            self._print_summary(df_config)
        
        return success
    
    def _print_summary(self, df: pd.DataFrame):
        """결과 요약 출력"""
        selenium_true = (df['selenium_required'] == True).sum()
        selenium_false = (df['selenium_required'] == False).sum()
        total = len(df)
        
        print("\n📊 결과 요약:")
        print(f"  • Selenium 필요: {selenium_true}개")
        print(f"  • Selenium 불필요: {selenium_false}개")
        print(f"  • 전체: {total}개")

def main():
    """메인 실행 함수"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_folder = os.path.join(base_dir, 'data')
    config_csv_path = os.path.join(data_folder, '채용공고_목록.csv')
    
    # 업데이트 실행
    updater = ConfigUpdater(config_csv_path)
    success = updater.update_selenium_flags()
    
    if success:
        print("\n🎉 모든 작업이 성공적으로 완료되었습니다!")
    else:
        print("\n⚠️ 작업 중 일부 오류가 발생했습니다.")

if __name__ == "__main__":
    main()