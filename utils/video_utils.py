import re
from typing import Dict, Any, Optional
from pytube import YouTube


def get_download_info(video_id: str) -> Dict[str, Any]:
    """الحصول على معلومات التحميل باستخدام pytube"""
    try:
        url = f"https://youtube.com/watch?v={video_id}"
        yt = YouTube(url)
        
        streams = []
        for stream in yt.streams.filter(progressive=True):
            streams.append({
                'itag': stream.itag,
                'resolution': stream.resolution,
                'fps': stream.fps,
                'mime_type': stream.mime_type,
                'filesize': stream.filesize,
                'filesize_mb': round(stream.filesize / (1024 * 1024), 2),
                'url': stream.url if hasattr(stream, 'url') else None
            })
        
        return {
            'video_id': video_id,
            'title': yt.title,
            'author': yt.author,
            'length': yt.length,
            'thumbnail': yt.thumbnail_url,
            'description': yt.description[:500] if yt.description else '',
            'streams': streams,
            'best_stream': streams[0] if streams else None
        }
        
    except Exception as e:
        print(f"⚠️ خطأ في pytube: {e}")
        return {
            'video_id': video_id,
            'error': str(e),
            'available': False
        }


def download_video(video_id: str, resolution: str = '720p') -> Optional[str]:
    """تحميل الفيديو"""
    try:
        url = f"https://youtube.com/watch?v={video_id}"
        yt = YouTube(url)
        
        stream = yt.streams.filter(
            progressive=True,
            resolution=resolution
        ).first()
        
        if not stream:
            stream = yt.streams.get_highest_resolution()
        
        if stream:
            output_path = stream.download(output_path='downloads')
            return output_path
        
        return None
        
    except Exception as e:
        print(f"⚠️ خطأ في التحميل: {e}")
        return None


def get_youtube_thumbnail(video_id: str, quality: str = 'hqdefault') -> str:
    """الحصول على رابط الصورة المصغرة"""
    qualities = {
        'default': f'https://img.youtube.com/vi/{video_id}/default.jpg',
        'mqdefault': f'https://img.youtube.com/vi/{video_id}/mqdefault.jpg',
        'hqdefault': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
        'sddefault': f'https://img.youtube.com/vi/{video_id}/sddefault.jpg',
        'maxresdefault': f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg'
    }
    return qualities.get(quality, qualities['hqdefault'])
