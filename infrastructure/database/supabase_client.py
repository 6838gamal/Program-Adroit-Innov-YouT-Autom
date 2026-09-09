# infrastructure/database/supabase_client.py

import os
from supabase import create_client, Client
from typing import Optional, Dict, Any, List
import logging

from config.settings import settings

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
            supabase_url = settings.SUPABASE_URL
            supabase_key = settings.supabase_secret_key_value or settings.supabase_public_key_value
            
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
    
    # ============ عمليات المشاريع ============
    
    async def get_project_data(self, project_id: str, user_id: Optional[str] = None) -> Optional[Dict]:
        """جلب بيانات المشروع من Supabase"""
        if not self.is_available():
            return None
        
        query = self._client.table('project_data').select('*').eq('project_id', project_id)
        
        if user_id:
            query = query.eq('user_id', user_id)
        
        response = query.maybe_single().execute()
        return response.data if response.data else None
    
    async def save_project_data(self, project_id: str, user_id: str, data: Dict) -> Optional[Dict]:
        """حفظ بيانات المشروع في Supabase"""
        if not self.is_available():
            return None
        
        # التحقق من وجود المشروع
        existing = self._client.table('project_data').select('project_id').eq('project_id', project_id).execute()
        
        if existing.data:
            # تحديث المشروع الموجود
            response = self._client.table('project_data')\
                .update({
                    'data': data,
                    'updated_at': 'now()'
                })\
                .eq('project_id', project_id)\
                .execute()
        else:
            # إنشاء مشروع جديد
            response = self._client.table('project_data')\
                .insert({
                    'project_id': project_id,
                    'user_id': user_id,
                    'data': data,
                    'created_at': 'now()',
                    'updated_at': 'now()',
                    'shared_with': []
                })\
                .execute()
        
        return response.data[0] if response.data else None
    
    async def delete_project_data(self, project_id: str, user_id: str) -> bool:
        """حذف بيانات المشروع من Supabase"""
        if not self.is_available():
            return False
        
        response = self._client.table('project_data')\
            .delete()\
            .eq('project_id', project_id)\
            .eq('user_id', user_id)\
            .execute()
        
        return len(response.data) > 0
    
    async def share_project(self, project_id: str, email: str) -> Optional[Dict]:
        """مشاركة المشروع مع مستخدم آخر"""
        if not self.is_available():
            return None
        
        # جلب المشروع
        result = self._client.table('project_data')\
            .select('shared_with')\
            .eq('project_id', project_id)\
            .maybe_single()\
            .execute()
        
        if not result.data:
            return None
        
        shared_with = result.data.get('shared_with', [])
        if email not in shared_with:
            shared_with.append(email)
        
        # تحديث المشروع
        response = self._client.table('project_data')\
            .update({'shared_with': shared_with})\
            .eq('project_id', project_id)\
            .execute()
        
        return response.data[0] if response.data else None
    
    async def get_shared_project(self, project_id: str, user_email: str) -> Optional[Dict]:
        """جلب مشروع مشترك"""
        if not self.is_available():
            return None
        
        response = self._client.table('project_data')\
            .select('*')\
            .eq('project_id', project_id)\
            .contains('shared_with', [user_email])\
            .maybe_single()\
            .execute()
        
        return response.data if response.data else None
    
    async def get_user_projects(self, user_id: str, limit: int = 50) -> List[Dict]:
        """جلب جميع مشاريع المستخدم"""
        if not self.is_available():
            return []
        
        response = self._client.table('project_data')\
            .select('*')\
            .eq('user_id', user_id)\
            .order('updated_at', desc=True)\
            .limit(limit)\
            .execute()
        
        return response.data
    
    async def project_exists(self, project_id: str) -> bool:
        """التحقق من وجود مشروع"""
        if not self.is_available():
            return False
        
        response = self._client.table('project_data')\
            .select('project_id')\
            .eq('project_id', project_id)\
            .maybe_single()\
            .execute()
        
        return bool(response.data)
    
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


# ============================================================
# ✅ دوال مساعدة للاستخدام في routes/projects.py
# ============================================================

def get_supabase_admin() -> Optional[Client]:
    """
    الحصول على عميل Supabase بصلاحيات كاملة (Service Role Key)
    يستخدم في routes/projects.py للحفظ والتحميل
    """
    client = SupabaseClient()
    if client.is_available():
        return client.client
    return None


def get_supabase_client() -> Optional[Client]:
    """
    نفس الوظيفة السابقة - اسم بديل للوضوح
    """
    return get_supabase_admin()


def get_supabase() -> Optional[SupabaseClient]:
    """
    الحصول على كائن SupabaseClient الكامل
    """
    return SupabaseClient()


# إنشاء نسخة واحدة
supabase_client = SupabaseClient()
