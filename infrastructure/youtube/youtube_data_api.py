import os
from typing import Optional, Dict, Any, List
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .oauth_manager import YouTubeOAuthManager


class YouTubeDataAPI:
    """خدمة YouTube Data API مع OAuth"""
    
    def __init__(self):
        self.api_key = os.getenv("YOUTUBE_API_KEY")
        self.oauth_manager = YouTubeOAuthManager()
        self._service = None
        self._authenticated_service = None
    
    def get_service(self, use_auth: bool = False):
        """الحصول على خدمة YouTube API"""
        if use_auth:
            return self._get_authenticated_service()
        return self._get_public_service()
    
    def _get_public_service(self):
        """الحصول على خدمة عامة (باستخدام API Key)"""
        if self._service is None:
            self._service = build('youtube', 'v3', developerKey=self.api_key)
        return self._service
    
    def _get_authenticated_service(self):
        """الحصول على خدمة مصادق عليها (باستخدام OAuth)"""
        creds = self.oauth_manager.get_credentials()
        if creds is None:
            raise ValueError("⚠️ لا توجد بيانات اعتماد. يرجى تسجيل الدخول أولاً.")
        
        if self._authenticated_service is None:
            self._authenticated_service = build(
                'youtube', 'v3', credentials=creds
            )
        return self._authenticated_service
    
    # ============================
    # استخراج معلومات الفيديو
    # ============================
    
    def get_video_info(self, video_id: str, use_auth: bool = False) -> Dict[str, Any]:
        """استخراج معلومات الفيديو باستخدام YouTube Data API"""
        try:
            service = self.get_service(use_auth)
            
            request = service.videos().list(
                part='snippet,contentDetails,statistics,status',
                id=video_id
            )
            response = request.execute()
            
            if not response.get('items'):
                return {}
            
            item = response['items'][0]
            
            # استخراج المعلومات
            snippet = item.get('snippet', {})
            content_details = item.get('contentDetails', {})
            statistics = item.get('statistics', {})
            status = item.get('status', {})
            
            return {
                'video_id': video_id,
                'title': snippet.get('title', ''),
                'description': snippet.get('description', ''),
                'channel_id': snippet.get('channelId', ''),
                'channel_title': snippet.get('channelTitle', ''),
                'published_at': snippet.get('publishedAt', ''),
                'thumbnail': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                'duration': self._parse_duration(content_details.get('duration', 'PT0S')),
                'view_count': int(statistics.get('viewCount', 0)),
                'like_count': int(statistics.get('likeCount', 0)),
                'comment_count': int(statistics.get('commentCount', 0)),
                'category_id': snippet.get('categoryId', ''),
                'tags': snippet.get('tags', []),
                'is_private': status.get('privacyStatus', '') == 'private',
                'is_unlisted': status.get('privacyStatus', '') == 'unlisted',
                'is_embeddable': status.get('embeddable', True),
                'dimensions': self._get_video_dimensions(content_details),
                'format': 'mp4',
                'platform': 'youtube'
            }
            
        except HttpError as e:
            print(f"⚠️ خطأ في YouTube API: {e}")
            return {}
    
    def search_videos(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """البحث عن فيديوهات"""
        try:
            service = self.get_service()
            
            request = service.search().list(
                part='snippet',
                q=query,
                type='video',
                maxResults=max_results,
                videoDuration='medium',
                order='relevance'
            )
            response = request.execute()
            
            videos = []
            for item in response.get('items', []):
                video_id = item['id']['videoId']
                snippet = item['snippet']
                videos.append({
                    'video_id': video_id,
                    'title': snippet.get('title', ''),
                    'description': snippet.get('description', ''),
                    'thumbnail': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                    'channel_title': snippet.get('channelTitle', ''),
                    'published_at': snippet.get('publishedAt', ''),
                    'url': f"https://youtube.com/watch?v={video_id}"
                })
            
            return videos
            
        except HttpError as e:
            print(f"⚠️ خطأ في البحث: {e}")
            return []
    
    def get_channel_info(self, channel_id: str) -> Dict[str, Any]:
        """الحصول على معلومات القناة"""
        try:
            service = self.get_service()
            
            request = service.channels().list(
                part='snippet,statistics',
                id=channel_id
            )
            response = request.execute()
            
            if not response.get('items'):
                return {}
            
            item = response['items'][0]
            snippet = item.get('snippet', {})
            statistics = item.get('statistics', {})
            
            return {
                'channel_id': channel_id,
                'title': snippet.get('title', ''),
                'description': snippet.get('description', ''),
                'thumbnail': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                'subscriber_count': int(statistics.get('subscriberCount', 0)),
                'video_count': int(statistics.get('videoCount', 0)),
                'view_count': int(statistics.get('viewCount', 0))
            }
            
        except HttpError as e:
            print(f"⚠️ خطأ في الحصول على معلومات القناة: {e}")
            return {}
    
    # ============================
    # دوال مساعدة
    # ============================
    
    def _parse_duration(self, duration: str) -> int:
        """تحويل مدة الفيديو من ISO 8601 إلى ثواني"""
        import re
        import datetime
        
        match = re.match(r'PT(\d+H)?(\d+M)?(\d+S)?', duration)
        if not match:
            return 0
        
        hours = int(match.group(1)[:-1]) if match.group(1) else 0
        minutes = int(match.group(2)[:-1]) if match.group(2) else 0
        seconds = int(match.group(3)[:-1]) if match.group(3) else 0
        
        return hours * 3600 + minutes * 60 + seconds
    
    def _get_video_dimensions(self, content_details: Dict) -> str:
        """الحصول على أبعاد الفيديو"""
        # الـ API لا يوفر الأبعاد مباشرة، نستخدم القيم الافتراضية
        return '1920x1080'


class YouTubeDataAPIExtended(YouTubeDataAPI):
    """نسخة موسعة مع دعم OAuth وميزات إضافية"""
    
    def get_video_with_auth(self, video_id: str) -> Dict[str, Any]:
        """الحصول على معلومات الفيديو باستخدام OAuth"""
        return self.get_video_info(video_id, use_auth=True)
    
    def get_my_uploads(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """الحصول على فيديوهات المستخدم"""
        try:
            service = self.get_service(use_auth=True)
            
            # الحصول على قناة المستخدم
            channel_request = service.channels().list(
                part='contentDetails',
                mine=True
            )
            channel_response = channel_request.execute()
            
            if not channel_response.get('items'):
                return []
            
            uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
            
            # الحصول على الفيديوهات
            request = service.playlistItems().list(
                part='snippet,contentDetails',
                playlistId=uploads_playlist_id,
                maxResults=max_results
            )
            response = request.execute()
            
            videos = []
            for item in response.get('items', []):
                snippet = item.get('snippet', {})
                content_details = item.get('contentDetails', {})
                video_id = content_details.get('videoId', '')
                
                # الحصول على معلومات إضافية
                video_info = self.get_video_info(video_id, use_auth=True)
                if video_info:
                    videos.append(video_info)
            
            return videos
            
        except HttpError as e:
            print(f"⚠️ خطأ في الحصول على التحميلات: {e}")
            return []
    
    def get_subscriptions(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """الحصول على قنوات المشترك فيها"""
        try:
            service = self.get_service(use_auth=True)
            
            request = service.subscriptions().list(
                part='snippet',
                mine=True,
                maxResults=max_results
            )
            response = request.execute()
            
            subscriptions = []
            for item in response.get('items', []):
                snippet = item.get('snippet', {})
                subscriptions.append({
                    'channel_id': snippet.get('resourceId', {}).get('channelId', ''),
                    'title': snippet.get('title', ''),
                    'thumbnail': snippet.get('thumbnails', {}).get('high', {}).get('url', '')
                })
            
            return subscriptions
            
        except HttpError as e:
            print(f"⚠️ خطأ في الحصول على المشترك بها: {e}")
            return []
