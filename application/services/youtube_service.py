from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

from infrastructure.youtube.youtube_data_api import YouTubeDataAPIExtended
from infrastructure.youtube.oauth_manager import YouTubeOAuthManager


class YouTubeService:
    """خدمة YouTube المتكاملة"""
    
    def __init__(self):
        self.api = YouTubeDataAPIExtended()
        self.oauth = YouTubeOAuthManager()
    
    def get_video_info(self, video_id: str, use_auth: bool = False) -> Dict[str, Any]:
        """الحصول على معلومات الفيديو"""
        return self.api.get_video_info(video_id, use_auth)
    
    def get_video_from_url(self, url: str, use_auth: bool = False) -> Dict[str, Any]:
        """استخراج معلومات الفيديو من الرابط"""
        video_id = self.extract_video_id(url)
        if not video_id:
            raise ValueError("⚠️ رابط يوتيوب غير صحيح")
        
        return self.get_video_info(video_id, use_auth)
    
    def search_videos(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """البحث عن فيديوهات"""
        return self.api.search_videos(query, max_results)
    
    def get_channel_info(self, channel_id: str) -> Dict[str, Any]:
        """الحصول على معلومات القناة"""
        return self.api.get_channel_info(channel_id)
    
    def get_my_uploads(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """الحصول على فيديوهات المستخدم"""
        return self.api.get_my_uploads(max_results)
    
    def get_subscriptions(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """الحصول على قنوات المشترك فيها"""
        return self.api.get_subscriptions(max_results)
    
    def get_auth_url(self) -> str:
        """الحصول على رابط المصادقة"""
        return self.oauth.get_auth_url()
    
    def authenticate(self, code: str, user_id: str = "default") -> bool:
        """مصادقة المستخدم"""
        creds = self.oauth.exchange_code(code, user_id)
        return creds is not None
    
    def is_authenticated(self, user_id: str = "default") -> bool:
        """التحقق من المصادقة"""
        creds = self.oauth.get_credentials(user_id)
        return creds is not None
    
    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        """استخراج معرف الفيديو من رابط يوتيوب"""
        import re
        
        patterns = [
            r'(?:youtube\.com\/watch\?v=)([\w-]+)',
            r'(?:youtu\.be\/)([\w-]+)',
            r'(?:youtube\.com\/embed\/)([\w-]+)',
            r'(?:youtube\.com\/shorts\/)([\w-]+)',
            r'(?:youtube\.com\/v\/)([\w-]+)',
            r'(?:youtube\.com\/watch\?.*?v=)([\w-]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
