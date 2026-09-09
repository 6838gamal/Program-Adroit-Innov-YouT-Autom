import os
import uuid
import tempfile
import jwt
import httpx
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, BinaryIO
from supabase import create_client, Client
from shared.ports.storage_port import StoragePort
from config.settings import settings


class SupabaseStorageAdapter(StoragePort):
    """
    Supabase Storage Adapter with Modern JWT Authentication.
    Uses PUBLIC_KEY for read operations and SECRET_KEY for write operations.
    """
    
    def __init__(self):
        # ✅ استخراج القيم النصية من SecretStr
        self.supabase_url = settings.SUPABASE_URL
        
        # ✅ تحويل SecretStr إلى str باستخدام get_secret_value()
        self.public_key = settings.supabase_public_key_value  # الآن هي str
        self.secret_key = settings.supabase_secret_key_value  # الآن هي str
        
        self.bucket_name = settings.SUPABASE_BUCKET
        
        # Validate configuration
        if not self.supabase_url:
            raise ValueError("SUPABASE_URL environment variable is required")
        if not self.public_key:
            raise ValueError("SUPABASE_PUBLIC_KEY environment variable is required")
        if not self.secret_key:
            raise ValueError("SUPABASE_SECRET_KEY environment variable is required")
        
        # ✅ إنشاء العملاء باستخدام القيم النصية
        self.public_client: Client = create_client(self.supabase_url, self.public_key)
        self.secret_client: Client = create_client(self.supabase_url, self.secret_key)
        
        # Initialize storage
        self._ensure_bucket_exists()
        self._setup_bucket_policies()
    
    def _ensure_bucket_exists(self) -> None:
        """Ensure the storage bucket exists using SECRET_KEY."""
        try:
            # Try to get bucket info
            self.secret_client.storage.get_bucket(self.bucket_name)
            print(f"✅ Bucket '{self.bucket_name}' already exists")
        except Exception as e:
            # Create bucket with SECRET_KEY
            try:
                self.secret_client.storage.create_bucket(
                    self.bucket_name,
                    options={
                        "public": True,
                        "file_size_limit": 100 * 1024 * 1024,  # 100MB
                        "allowed_mime_types": [
                            "image/jpeg", "image/png", "image/gif", "image/webp",
                            "video/mp4", "video/quicktime", "video/webm",
                            "audio/mpeg", "audio/wav", "audio/ogg",
                            "application/pdf", "text/plain"
                        ]
                    }
                )
                print(f"✅ Bucket '{self.bucket_name}' created successfully")
            except Exception as create_error:
                raise Exception(f"Failed to create bucket: {str(create_error)}")
    
    def _setup_bucket_policies(self) -> None:
        """Set up RLS policies for the bucket using SECRET_KEY."""
        try:
            # Note: RLS policies need to be set via SQL in Supabase Dashboard
            # This is just a placeholder for best practice documentation
            print("ℹ️ Bucket policies should be configured in Supabase Dashboard")
        except Exception as e:
            print(f"⚠️ Failed to setup policies: {str(e)}")
    
    # ===== JWT Token Generation =====
    
    def generate_user_token(self, user_id: str, user_metadata: Dict[str, Any] = None) -> str:
        """
        Generate a JWT token for a user using SECRET_KEY.
        This is useful for creating temporary access tokens.
        """
        payload = {
            "sub": user_id,
            "user": user_metadata or {},
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
            "aud": "authenticated",
            "iss": self.supabase_url,
            "role": "authenticated"
        }
        
        # ✅ استخدام secret_key (str) وليس SecretStr
        return jwt.encode(payload, self.secret_key, algorithm=settings.JWT_ALGORITHM)
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify a JWT token using PUBLIC_KEY.
        """
        try:
            # ✅ استخدام public_key (str) وليس SecretStr
            payload = jwt.decode(
                token,
                self.public_key,
                algorithms=[settings.JWT_ALGORITHM],
                audience="authenticated",
                options={"verify_signature": True}
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise Exception("Token has expired")
        except jwt.InvalidTokenError as e:
            raise Exception(f"Invalid token: {str(e)}")
    
    # ===== Storage Operations =====
    
    async def save(self, source: Path, destination: str) -> str:
        """
        Upload a file using SECRET_KEY for admin operations.
        """
        try:
            with open(source, 'rb') as f:
                file_content = f.read()
            
            content_type = self._get_content_type(source)
            
            # Use SECRET_KEY for upload
            self.secret_client.storage.from_(self.bucket_name).upload(
                path=destination,
                file=file_content,
                file_options={
                    "content-type": content_type,
                    "cache-control": "3600",
                    "upsert": True
                }
            )
            
            return destination
        except Exception as e:
            raise Exception(f"Upload failed: {str(e)}")
    
    async def save_with_token(self, source: Path, destination: str, user_token: str) -> str:
        """
        Upload a file using a user's JWT token for authenticated uploads.
        """
        try:
            # Create a client with user token
            user_client = create_client(self.supabase_url, user_token)
            
            with open(source, 'rb') as f:
                file_content = f.read()
            
            content_type = self._get_content_type(source)
            
            user_client.storage.from_(self.bucket_name).upload(
                path=destination,
                file=file_content,
                file_options={
                    "content-type": content_type,
                    "cache-control": "3600"
                }
            )
            
            return destination
        except Exception as e:
            raise Exception(f"Upload failed: {str(e)}")
    
    async def save_bytes(self, data: bytes, destination: str, content_type: str = "application/octet-stream") -> str:
        """
        Upload bytes directly using SECRET_KEY.
        """
        try:
            self.secret_client.storage.from_(self.bucket_name).upload(
                path=destination,
                file=data,
                file_options={
                    "content-type": content_type,
                    "cache-control": "3600",
                    "upsert": True
                }
            )
            return destination
        except Exception as e:
            raise Exception(f"Upload failed: {str(e)}")
    
    async def get_path(self, key: str) -> Path:
        """Supabase doesn't support local paths."""
        raise NotImplementedError("Supabase uses URLs, not local paths")
    
    async def delete(self, key: str) -> None:
        """
        Delete a file using SECRET_KEY.
        """
        try:
            self.secret_client.storage.from_(self.bucket_name).remove([key])
        except Exception as e:
            raise Exception(f"Delete failed: {str(e)}")
    
    async def delete_with_token(self, key: str, user_token: str) -> None:
        """
        Delete a file using user's JWT token.
        """
        try:
            user_client = create_client(self.supabase_url, user_token)
            user_client.storage.from_(self.bucket_name).remove([key])
        except Exception as e:
            raise Exception(f"Delete failed: {str(e)}")
    
    async def exists(self, key: str) -> bool:
        """
        Check if file exists using PUBLIC_KEY.
        """
        try:
            # Try to list files with PUBLIC_KEY
            files = self.public_client.storage.from_(self.bucket_name).list(
                path=str(Path(key).parent),
                options={"limit": 100}
            )
            
            file_name = Path(key).name
            for file in files:
                if file.get("name") == file_name:
                    return True
            return False
        except Exception:
            return False
    
    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        """
        Get public URL - uses PUBLIC_KEY for read access.
        """
        return self.public_client.storage.from_(self.bucket_name).get_public_url(key)
    
    async def get_signed_url(self, key: str, expires_in: int = 3600) -> str:
        """
        Generate signed URL using SECRET_KEY.
        """
        try:
            signed_url = self.secret_client.storage.from_(self.bucket_name).create_signed_url(
                key, expires_in
            )
            return signed_url["signedURL"]
        except Exception as e:
            raise Exception(f"Failed to generate signed URL: {str(e)}")
    
    async def list_files(self, prefix: str = "", limit: int = 1000) -> list:
        """
        List files using PUBLIC_KEY.
        """
        try:
            files = self.public_client.storage.from_(self.bucket_name).list(
                path=prefix,
                options={"limit": limit}
            )
            return files
        except Exception as e:
            print(f"⚠️ Failed to list files: {str(e)}")
            return []
    
    async def copy_file(self, source_key: str, destination_key: str) -> str:
        """
        Copy a file using SECRET_KEY.
        """
        try:
            # Download with SECRET_KEY
            file_data = self.secret_client.storage.from_(self.bucket_name).download(source_key)
            
            # Upload with SECRET_KEY
            self.secret_client.storage.from_(self.bucket_name).upload(
                path=destination_key,
                file=file_data,
                file_options={"upsert": True}
            )
            
            return destination_key
        except Exception as e:
            raise Exception(f"Failed to copy file: {str(e)}")
    
    async def move_file(self, source_key: str, destination_key: str) -> str:
        """
        Move a file using SECRET_KEY.
        """
        try:
            # Copy then delete
            await self.copy_file(source_key, destination_key)
            await self.delete(source_key)
            return destination_key
        except Exception as e:
            raise Exception(f"Failed to move file: {str(e)}")
    
    async def get_file_info(self, key: str) -> Dict[str, Any]:
        """
        Get file metadata using PUBLIC_KEY.
        """
        try:
            # Try to get file info
            files = self.public_client.storage.from_(self.bucket_name).list(
                path=str(Path(key).parent),
                options={"limit": 1, "search": Path(key).name}
            )
            
            if files:
                return files[0]
            return {}
        except Exception as e:
            raise Exception(f"Failed to get file info: {str(e)}")
    
    def _get_content_type(self, file_path: Path) -> str:
        """Determine content type based on file extension."""
        ext = file_path.suffix.lower()
        content_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.svg': 'image/svg+xml',
            '.mp4': 'video/mp4',
            '.mov': 'video/quicktime',
            '.avi': 'video/x-msvideo',
            '.webm': 'video/webm',
            '.mkv': 'video/x-matroska',
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.flac': 'audio/flac',
            '.aac': 'audio/aac',
            '.ogg': 'audio/ogg',
            '.pdf': 'application/pdf',
            '.txt': 'text/plain',
            '.json': 'application/json',
            '.xml': 'application/xml',
            '.zip': 'application/zip',
        }
        return content_types.get(ext, 'application/octet-stream')
