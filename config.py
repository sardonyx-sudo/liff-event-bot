import os
from dotenv import load_dotenv

# 嘗試讀取 .env 檔案 (本地開發用)
load_dotenv()

class Config:
    # LINE Bot 設定
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
    
    # LIFF 設定
    LIFF_ID_ADMIN = os.getenv("LIFF_ID_ADMIN")
    LIFF_ID_MEMBER = os.getenv("LIFF_ID_MEMBER")

    # 管理員啟動碼
    ADMIN_SETUP_CODE = os.getenv("ADMIN_SETUP_CODE", "8888")

    # Firestore 憑證 (本地開發需要路徑，Cloud Run 會自動抓 Default Credentials)
    GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    # 目標群組 ID (之後會存入 DB，這邊先保留預設值)
    TARGET_GROUP_ID = os.getenv("TARGET_GROUP_ID")

config = Config()