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
    _table_checked: bool = False  # ✅ منع التكرار
    _table_created: bool = False  # ✅ تتبع حالة الإنشاء
    
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
    
    # ============================================================
    # التحقق من الجدول وإنشاؤه (مرة واحدة فقط)
    # ============================================================
    
    def ensure_table(self) -> bool:
        """
        التأكد من وجود جدول project_data، وإنشاؤه إذا لم يكن موجوداً
        يتم التحقق مرة واحدة فقط في دورة حياة التطبيق
        """
        # ✅ إذا تم التحقق مسبقاً والجدول موجود، نعيد النتيجة فوراً
        if self._table_checked and self._table_created:
            return True
        
        # ✅ إذا تم التحقق مسبقاً وفشل، نعيد false
        if self._table_checked and not self._table_created:
            return False
        
        # ✅ لم يتم التحقق من قبل، نقوم بالتحقق الآن
        self._table_checked = True
        
        if not self.is_available():
            logger.error("❌ Supabase client not available")
            self._table_created = False
            return False
        
        try:
            # محاولة الاستعلام من الجدول
            self._client.table('project_data').select('id').limit(1).execute()
            logger.info("✅ Table 'project_data' already exists")
            self._table_created = True
            return True
            
        except Exception as e:
            error_msg = str(e)
            # إذا كان الجدول غير موجود
            if 'PGRST205' in error_msg or 'Could not find the table' in error_msg:
                logger.info("📦 Table 'project_data' not found, creating...")
                result = self._create_table()
                self._table_created = result
                return result
            else:
                logger.error(f"❌ Error checking table: {e}")
                self._table_created = False
                return False
    
    def _create_table(self) -> bool:
        """إنشاء جدول project_data (يتم استدعاؤها مرة واحدة فقط)"""
        if not self.is_available():
            return False
        
        try:
            sql = """
            CREATE TABLE IF NOT EXISTS project_data (
                id BIGSERIAL PRIMARY KEY,
                project_id UUID NOT NULL,
                user_id UUID,
                data JSONB NOT NULL,
                shared_with TEXT[] DEFAULT '{}',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            
            CREATE UNIQUE INDEX IF NOT EXISTS idx_project_data_project_id ON project_data(project_id);
            CREATE INDEX IF NOT EXISTS idx_project_data_user_id ON project_data(user_id);
            CREATE INDEX IF NOT EXISTS idx_project_data_updated_at ON project_data(updated_at DESC);
            
            ALTER TABLE project_data ENABLE ROW LEVEL SECURITY;
            """
            
            # محاولة الطريقة الأولى: RPC
            try:
                response = self._client.rpc('exec_sql', {'sql': sql}).execute()
                logger.info("✅ Table 'project_data' created successfully via RPC")
                return True
            except Exception as e1:
                logger.warning(f"⚠️ RPC method failed: {e1}, trying alternative...")
                
                # محاولة الطريقة الثانية: SQL مباشر
                try:
                    # استخدام raw SQL عبر postgrest
                    response = self._client.postgrest.rpc('exec_sql', {'sql': sql}).execute()
                    logger.info("✅ Table 'project_data' created successfully via postgrest")
                    return True
                except Exception as e2:
                    logger.warning(f"⚠️ Postgrest method failed: {e2}")
                    
                    # محاولة الطريقة الثالثة: استخدام create_table إذا كانت متوفرة
                    try:
                        # استخدام raw SQL
                        self._client.table('_sql').insert({'query': sql}).execute()
                        logger.info("✅ Table 'project_data' created successfully via _sql")
                        return True
                    except Exception as e3:
                        logger.error(f"❌ All creation methods failed: {e3}")
                        return False
            
        except Exception as e:
            logger.error(f"❌ Failed to create table: {e}")
            return False
    
    # ============================================================
    # عمليات المشاريع
    # ============================================================
    
    async def get_project_data(self, project_id: str, user_id: Optional[str] = None) -> Optional[Dict]:
        """جلب بيانات المشروع من Supabase"""
        if not self.is_available():
            return None
        
        # ✅ التحقق من الجدول (مرة واحدة فقط)
        if not self.ensure_table():
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
        
        # ✅ التحقق من الجدول (مرة واحدة فقط)
        if not self.ensure_table():
            return None
        
        try:
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
            
        except Exception as e:
            logger.error(f"❌ Error saving project: {e}")
            return None
    
    async def delete_project_data(self, project_id: str, user_id: str) -> bool:
        """حذف بيانات المشروع من Supabase"""
        if not self.is_available():
            return False
        
        if not self.ensure_table():
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
        
        if not self.ensure_table():
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
        
        if not self.ensure_table():
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
        
        if not self.ensure_table():
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
        
        if not self.ensure_table():
            return False
        
        response = self._client.table('project_data')\
            .select('project_id')\
            .eq('project_id', project_id)\
            .maybe_single()\
            .execute()
        
        return bool(response.data)
    
    # ============================================================
    # عمليات الفيديوهات
    # ============================================================
    
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
# دوال مساعدة للاستخدام في routes/projects.py
# ============================================================

def get_supabase_admin() -> Optional[Client]:
    """
    الحصول على عميل Supabase بصلاحيات كاملة (Service Role Key)
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


def ensure_project_data_table() -> bool:
    """
    التأكد من وجود جدول project_data (يتم التحقق مرة واحدة فقط)
    """
    client = SupabaseClient()
    return client.ensure_table()


# إنشاء نسخة واحدة
supabase_client = SupabaseClient()


# ============================================================
# ✅ تهيئة الجدول عند تحميل الملف (اختياري)
# ============================================================

# ✅ التحقق من الجدول عند بدء التشغيل (مرة واحدة)
def initialize():
    """تهيئة الجدول عند بدء التشغيل"""
    if supabase_client.is_available():
        supabase_client.ensure_table()


# تنفيذ التهيئة
initialize()
