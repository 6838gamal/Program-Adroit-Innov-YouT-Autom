# infrastructure/database/supabase_client.py
import os
from supabase import create_client, Client
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)

class SupabaseClient:
    """Client for interacting with Supabase via REST API"""
    
    _instance: Optional['SupabaseClient'] = None
    _client: Optional[Client] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._client is None:
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_PUBLIC_KEY")
            
            if not supabase_url or not supabase_key:
                logger.warning("⚠️ Supabase credentials not configured!")
                return
            
            self._client = create_client(supabase_url, supabase_key)
            logger.info("✅ Supabase client initialized")
    
    @property
    def client(self) -> Optional[Client]:
        return self._client
    
    def is_available(self) -> bool:
        return self._client is not None
    
    # ============ عمليات الفيديوهات ============
    
    async def get_video(self, video_id: str) -> Optional[Dict]:
        if not self.is_available():
            return None
        response = self._client.table('videos').select('*').eq('id', video_id).execute()
        return response.data[0] if response.data else None
    
    async def get_videos(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        if not self.is_available():
            return []
        response = self._client.table('videos')\
            .select('*')\
            .order('created_at', desc=True)\
            .limit(limit)\
            .offset(offset)\
            .execute()
        return response.data
    
    async def create_video(self, video_data: Dict) -> Optional[Dict]:
        if not self.is_available():
            return None
        response = self._client.table('videos').insert(video_data).execute()
        return response.data[0] if response.data else None
    
    async def update_video(self, video_id: str, video_data: Dict) -> Optional[Dict]:
        if not self.is_available():
            return None
        response = self._client.table('videos')\
            .update(video_data)\
            .eq('id', video_id)\
            .execute()
        return response.data[0] if response.data else None
    
    async def delete_video(self, video_id: str) -> bool:
        if not self.is_available():
            return False
        response = self._client.table('videos').delete().eq('id', video_id).execute()
        return len(response.data) > 0
    
    async def get_user_videos(self, user_id: str, limit: int = 50) -> List[Dict]:
        if not self.is_available():
            return []
        response = self._client.table('videos')\
            .select('*')\
            .eq('user_id', user_id)\
            .order('created_at', desc=True)\
            .limit(limit)\
            .execute()
        return response.data
    
    async def search_videos(self, query: str, limit: int = 20) -> List[Dict]:
        if not self.is_available():
            return []
        response = self._client.table('videos')\
            .select('*')\
            .text_search('title', query)\
            .limit(limit)\
            .execute()
        return response.data

# إنشاء نسخة واحدة
supabase_client = SupabaseClient()
