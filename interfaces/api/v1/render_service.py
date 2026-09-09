# render_service.py
import os
import json
import tempfile
import subprocess
import shutil
from pathlib import Path
from typing import List, Dict, Any
import asyncio
from datetime import datetime
import aiofiles
from PIL import Image
import numpy as np

class VideoRenderer:
    """خدمة معالجة ورندر الفيديو"""
    
    def __init__(self, output_dir: str = "./rendered"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.temp_dir = Path(tempfile.mkdtemp())
        
    async def render_project(self, project_data: Dict[str, Any]) -> str:
        """
        رندر مشروع كامل إلى فيديو MP4
        
        Args:
            project_data: بيانات المشروع (clips, layers, duration)
            
        Returns:
            مسار ملف الفيديو الناتج
        """
        clips = project_data.get('clips', [])
        duration = project_data.get('duration', 10)
        layers = project_data.get('layers', [])
        
        # ترتيب المقاطع حسب الطبقة
        clips_by_layer = {}
        for clip in clips:
            layer = clip.get('layer', 0)
            if layer not in clips_by_layer:
                clips_by_layer[layer] = []
            clips_by_layer[layer].append(clip)
        
        # ترتيب الطبقات من الأسفل للأعلى
        layer_keys = sorted(clips_by_layer.keys())
        
        # إنشاء فيديو لكل طبقة
        layer_videos = []
        for layer_idx in layer_keys:
            layer_clips = sorted(clips_by_layer[layer_idx], key=lambda x: x.get('start', 0))
            layer_video = await self._render_layer(layer_clips, duration)
            if layer_video:
                layer_videos.append(layer_video)
        
        if not layer_videos:
            # إذا لم توجد مقاطع، أنشئ فيديو فارغ
            return await self._create_empty_video(duration)
        
        # دمج الطبقات
        if len(layer_videos) == 1:
            final_video = layer_videos[0]
        else:
            final_video = await self._merge_layers(layer_videos, duration)
        
        # إضافة الصوت
        audio_file = await self._extract_audio(clips, duration)
        if audio_file:
            final_video = await self._add_audio(final_video, audio_file)
        
        return final_video
    
    async def _render_layer(self, clips: List[Dict], duration: float) -> str:
        """رندر طبقة واحدة من المقاطع"""
        if not clips:
            return None
            
        # إنشاء فيديو مؤقت
        output_path = self.temp_dir / f"layer_{datetime.now().timestamp()}.mp4"
        
        # استخدام FFmpeg لتركيب المقاطع
        filter_complex = []
        inputs = []
        input_files = []
        
        for i, clip in enumerate(clips):
            clip_type = clip.get('type', 'image')
            content = clip.get('content', '')
            start = clip.get('start', 0)
            duration = clip.get('duration', 3)
            title = clip.get('title', 'مقطع')
            
            if not content or content == 'blob':
                continue
                
            # تحميل الملف المؤقت
            temp_file = await self._download_media(content, clip_type)
            if not temp_file:
                continue
                
            input_files.append(temp_file)
            inputs.append(f"-i {temp_file}")
            
            if clip_type == 'image':
                # صورة ثابتة
                filter_complex.append(
                    f"[{i}:v]scale=1280:720:force_original_aspect_ratio=decrease,"
                    f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
                    f"fps=25,"
                    f"trim=start=0:duration={duration},"
                    f"setpts=PTS-STARTPTS+{start}/TB [v{i}]"
                )
            elif clip_type == 'video':
                # فيديو
                filter_complex.append(
                    f"[{i}:v]scale=1280:720:force_original_aspect_ratio=decrease,"
                    f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
                    f"fps=25,"
                    f"trim=start=0:duration={duration},"
                    f"setpts=PTS-STARTPTS+{start}/TB [v{i}]"
                )
            elif clip_type == 'text':
                # نص - نستخدم drawtext
                text = content.replace("'", "\\'")
                filter_complex.append(
                    f"[{i}:v]drawtext=text='{text}':fontcolor=white:fontsize=48:"
                    f"x=(w-text_w)/2:y=(h-text_h)/2:"
                    f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf,"
                    f"fps=25,"
                    f"trim=start=0:duration={duration},"
                    f"setpts=PTS-STARTPTS+{start}/TB [v{i}]"
                )
            elif clip_type == 'audio':
                # صوت - نتعامل معه لاحقاً
                continue
        
        if not filter_complex:
            return None
            
        # بناء أمر FFmpeg
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output
            *inputs,
            '-filter_complex',
            f"{'; '.join(filter_complex)}; "
            f"{' '.join([f'[v{i}]' for i in range(len(filter_complex))])} "
            f"concat=n={len(filter_complex)}:v=1:a=0 [outv]",
            '-map', '[outv]',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-pix_fmt', 'yuv420p',
            '-t', str(duration),
            str(output_path)
        ]
        
        try:
            result = subprocess.run(
                ' '.join(cmd),
                shell=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode != 0:
                print(f"FFmpeg error: {result.stderr}")
                return None
                
            # تنظيف الملفات المؤقتة
            for f in input_files:
                if os.path.exists(f):
                    os.unlink(f)
                    
            return str(output_path)
            
        except Exception as e:
            print(f"Render layer error: {e}")
            return None
    
    async def _merge_layers(self, layer_videos: List[str], duration: float) -> str:
        """دمج طبقات الفيديو فوق بعضها"""
        output_path = self.temp_dir / f"merged_{datetime.now().timestamp()}.mp4"
        
        # بناء أمر FFmpeg لدمج الطبقات (overlay)
        inputs = []
        filter_complex = []
        
        for i, video in enumerate(layer_videos):
            inputs.append(f"-i {video}")
            filter_complex.append(f"[{i}:v]")
        
        # استخدام overlay لتكديس الطبقات
        overlay_filter = ""
        for i in range(len(layer_videos) - 1):
            if i == 0:
                overlay_filter = f"[0:v][1:v]overlay=0:0 [out{i}]"
            else:
                overlay_filter = f"[out{i-1}][{i+1}:v]overlay=0:0 [out{i}]"
        
        cmd = [
            'ffmpeg',
            '-y',
            *inputs,
            '-filter_complex',
            overlay_filter,
            '-map', f'[out{len(layer_videos)-2}]' if len(layer_videos) > 1 else '[0:v]',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-pix_fmt', 'yuv420p',
            '-t', str(duration),
            str(output_path)
        ]
        
        try:
            result = subprocess.run(
                ' '.join(cmd),
                shell=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode != 0:
                print(f"Merge error: {result.stderr}")
                return None
                
            # تنظيف ملفات الطبقات المؤقتة
            for v in layer_videos:
                if os.path.exists(v) and v != output_path:
                    os.unlink(v)
                    
            return str(output_path)
            
        except Exception as e:
            print(f"Merge layers error: {e}")
            return None
    
    async def _extract_audio(self, clips: List[Dict], duration: float) -> str:
        """استخراج ودمج المقاطع الصوتية"""
        audio_clips = [c for c in clips if c.get('type') == 'audio']
        if not audio_clips:
            return None
            
        output_path = self.temp_dir / f"audio_{datetime.now().timestamp()}.wav"
        
        # إنشاء ملف صوتي فارغ بالطول المطلوب
        cmd_base = [
            'ffmpeg',
            '-y',
            '-f', 'lavfi',
            '-i', f'anullsrc=r=44100:cl=stereo',
            '-t', str(duration),
            str(output_path)
        ]
        
        try:
            subprocess.run(
                ' '.join(cmd_base),
                shell=True,
                capture_output=True,
                text=True,
                timeout=60
            )
        except:
            pass
        
        # إضافة المقاطع الصوتية
        for clip in audio_clips:
            content = clip.get('content', '')
            start = clip.get('start', 0)
            dur = clip.get('duration', 2)
            
            if not content or content == 'blob':
                continue
                
            temp_audio = await self._download_media(content, 'audio')
            if not temp_audio:
                continue
                
            # دمج الصوت مع الفيديو الرئيسي
            cmd = [
                'ffmpeg',
                '-y',
                '-i', str(output_path),
                '-i', temp_audio,
                '-filter_complex',
                f'[1:a]adelay={start*1000}|{start*1000},apad [a1]; '
                f'[0:a][a1]amix=inputs=2:duration=longest [aout]',
                '-map', '[aout]',
                '-c:a', 'aac',
                '-b:a', '192k',
                str(output_path).replace('.wav', '_mixed.wav')
            ]
            
            try:
                result = subprocess.run(
                    ' '.join(cmd),
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.returncode == 0:
                    mixed_path = str(output_path).replace('.wav', '_mixed.wav')
                    if os.path.exists(mixed_path):
                        os.unlink(str(output_path))
                        os.rename(mixed_path, str(output_path))
                        
                if os.path.exists(temp_audio):
                    os.unlink(temp_audio)
                    
            except Exception as e:
                print(f"Audio mix error: {e}")
                
        return str(output_path) if os.path.exists(str(output_path)) else None
    
    async def _add_audio(self, video_path: str, audio_path: str) -> str:
        """إضافة الصوت إلى الفيديو النهائي"""
        output_path = self.temp_dir / f"final_{datetime.now().timestamp()}.mp4"
        
        cmd = [
            'ffmpeg',
            '-y',
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-shortest',
            str(output_path)
        ]
        
        try:
            result = subprocess.run(
                ' '.join(cmd),
                shell=True,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode != 0:
                print(f"Add audio error: {result.stderr}")
                return video_path
                
            # تنظيف الملفات القديمة
            if os.path.exists(video_path) and video_path != output_path:
                os.unlink(video_path)
            if os.path.exists(audio_path):
                os.unlink(audio_path)
                
            return str(output_path)
            
        except Exception as e:
            print(f"Add audio error: {e}")
            return video_path
    
    async def _create_empty_video(self, duration: float) -> str:
        """إنشاء فيديو فارغ"""
        output_path = self.temp_dir / f"empty_{datetime.now().timestamp()}.mp4"
        
        cmd = [
            'ffmpeg',
            '-y',
            '-f', 'lavfi',
            '-i', f'color=c=black:s=1280x720:d={duration}',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '23',
            '-pix_fmt', 'yuv420p',
            str(output_path)
        ]
        
        try:
            subprocess.run(
                ' '.join(cmd),
                shell=True,
                capture_output=True,
                text=True,
                timeout=60
            )
            return str(output_path)
        except:
            return None
    
    async def _download_media(self, url: str, media_type: str) -> str:
        """تحميل الملف من URL إلى ملف مؤقت"""
        if url.startswith('blob:'):
            # إذا كان blob URL لا يمكن تحميله من الخادم
            return None
            
        try:
            # استخدام aiohttp لتحميل الملف
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        ext = {
                            'image': '.jpg',
                            'video': '.mp4',
                            'audio': '.wav'
                        }.get(media_type, '.tmp')
                        
                        temp_path = self.temp_dir / f"media_{datetime.now().timestamp()}{ext}"
                        async with aiofiles.open(temp_path, 'wb') as f:
                            await f.write(await response.read())
                        return str(temp_path)
        except Exception as e:
            print(f"Download error: {e}")
            
        return None
    
    def cleanup(self):
        """تنظيف الملفات المؤقتة"""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


# ============================================================
#  API endpoint للرندر
# ============================================================
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/v1/production", tags=["production"])

class RenderRequest(BaseModel):
    project_id: str
    clips: List[Dict[str, Any]]
    layers: List[Dict[str, Any]]
    duration: float

class RenderResponse(BaseModel):
    task_id: str
    status: str
    video_url: Optional[str] = None

render_tasks = {}

@router.post("/render")
async def start_render(request: RenderRequest, background_tasks: BackgroundTasks):
    """بدء عملية الرندر"""
    task_id = f"render_{request.project_id}_{datetime.now().timestamp()}"
    
    render_tasks[task_id] = {
        "status": "processing",
        "progress": 0,
        "video_url": None
    }
    
    background_tasks.add_task(
        process_render,
        task_id,
        request.dict()
    )
    
    return RenderResponse(
        task_id=task_id,
        status="processing"
    )

async def process_render(task_id: str, project_data: dict):
    """معالجة الرندر في الخلفية"""
    try:
        renderer = VideoRenderer()
        video_path = await renderer.render_project(project_data)
        
        if video_path and os.path.exists(video_path):
            # نقل الملف إلى المجلد النهائي
            final_path = f"./rendered/{task_id}.mp4"
            shutil.move(video_path, final_path)
            
            render_tasks[task_id]["status"] = "completed"
            render_tasks[task_id]["video_url"] = f"/rendered/{task_id}.mp4"
            render_tasks[task_id]["progress"] = 100
        else:
            render_tasks[task_id]["status"] = "failed"
            
        renderer.cleanup()
        
    except Exception as e:
        print(f"Render error: {e}")
        render_tasks[task_id]["status"] = "failed"

@router.get("/render/{task_id}/status")
async def get_render_status(task_id: str):
    """الحصول على حالة الرندر"""
    if task_id not in render_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return render_tasks[task_id]
