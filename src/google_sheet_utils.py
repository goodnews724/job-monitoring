import os
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
import logging

class GoogleSheetManager:
    """Google Sheets와의 연동을 관리하는 클래스"""
    
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.sheet_key = os.getenv('GOOGLE_SHEET_KEY')
        self.creds_path = os.path.join(self.base_dir, 'key', 'credentials.json')
        self.logger = logging.getLogger(__name__)
        self.gc = self._authorize()

    def _authorize(self):
        """Google API 인증"""
        if not self.sheet_key:
            self.logger.error("GOOGLE_SHEET_KEY가 .env에 설정되지 않았습니다.")
            return None
        
        if not os.path.exists(self.creds_path):
            self.logger.error(f"인증 파일 '{self.creds_path}'을(를) 찾을 수 없습니다.")
            return None

        try:
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_file(self.creds_path, scopes=scopes)
            gc = gspread.authorize(creds)
            self.logger.info("✅ Google API 인증 성공")
            return gc
        except Exception as e:
            self.logger.error(f"❌ Google API 인증 실패: {e}")
            return None

    def get_all_records_as_df(self, sheet_name: str = None) -> pd.DataFrame:
        """시트의 모든 데이터를 Pandas DataFrame으로 가져옵니다."""
        if not self.gc:
            return pd.DataFrame()
        
        try:
            spreadsheet = self.gc.open_by_key(self.sheet_key)
            if sheet_name:
                worksheet = spreadsheet.worksheet(sheet_name)
            else:
                worksheet = spreadsheet.sheet1
            
            rows = worksheet.get_all_records()
            df = pd.DataFrame(rows)
            self.logger.info(f"✅ '{worksheet.title}' 시트 데이터 로드 성공")
            return df
        except Exception as e:
            self.logger.error(f"❌ 시트 데이터 로드 실패: {e}")
            return pd.DataFrame()

    def update_sheet_from_df(self, df: pd.DataFrame, sheet_name: str = None):
        """DataFrame의 데이터로 시트 전체를 업데이트합니다."""
        if not self.gc:
            return False
        
        try:
            spreadsheet = self.gc.open_by_key(self.sheet_key)
            if sheet_name:
                worksheet = spreadsheet.worksheet(sheet_name)
            else:
                worksheet = spreadsheet.sheet1
            
            # 기존 데이터 삭제 후 DataFrame으로 업데이트
            worksheet.clear()
            worksheet.update([df.columns.values.tolist()] + df.values.tolist())
            self.logger.info(f"✅ '{worksheet.title}' 시트 업데이트 성공")
            return True
        except Exception as e:
            self.logger.error(f"❌ 시트 업데이트 실패: {e}")
            return False
