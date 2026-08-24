import os
import json
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


class YouTubeOAuthManager:
    """إدارة OAuth 2.0 لـ YouTube Data API"""
    
    SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']
    TOKEN_DIR = Path("tokens")
    
    def __init__(self):
        self.TOKEN_DIR.mkdir(exist_ok=True)
        self.client_id = os.getenv("YOUTUBE_CLIENT_ID")
        self.client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
        self.redirect_uri = os.getenv("YOUTUBE_REDIRECT_URI")
        
    def get_credentials(self, user_id: str = "default") -> Optional[Credentials]:
        """الحصول على بيانات الاعتماد للمستخدم"""
        token_file = self.TOKEN_DIR / f"youtube_token_{user_id}.json"
        creds = None
        
        if token_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(token_file), self.SCOPES
                )
            except Exception as e:
                print(f"⚠️ خطأ في تحميل التوكن: {e}")
        
        # تحديث التوكن إذا انتهت صلاحيته
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self.save_credentials(creds, user_id)
                print("✅ تم تحديث التوكن بنجاح")
            except Exception as e:
                print(f"⚠️ فشل تحديث التوكن: {e}")
                creds = None
                
        return creds
    
    def save_credentials(self, creds: Credentials, user_id: str = "default"):
        """حفظ بيانات الاعتماد"""
        token_file = self.TOKEN_DIR / f"youtube_token_{user_id}.json"
        with open(token_file, 'w') as f:
            json.dump({
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes
            }, f)
    
    def get_auth_url(self) -> str:
        """الحصول على رابط المصادقة"""
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json',  # ملف بيانات الاعتماد من Google Cloud Console
            scopes=self.SCOPES,
            redirect_uri=self.redirect_uri
        )
        
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        # تخزين الحالة للتحقق لاحقاً
        return auth_url
    
    def exchange_code(self, code: str, user_id: str = "default") -> Optional[Credentials]:
        """تبادل الكود للحصول على توكن"""
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json',
                scopes=self.SCOPES,
                redirect_uri=self.redirect_uri
            )
            flow.fetch_token(code=code)
            creds = flow.credentials
            self.save_credentials(creds, user_id)
            return creds
        except Exception as e:
            print(f"⚠️ فشل تبادل الكود: {e}")
            return None


# عينة من credentials.json
"""
{
    "installed": {
        "client_id": "your_client_id.apps.googleusercontent.com",
        "project_id": "your_project_id",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "your_client_secret",
        "redirect_uris": ["http://localhost:8000/api/v1/auth/youtube/callback"]
    }
}
"""
