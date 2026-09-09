import os
import uuid
import tempfile
import jwt
import httpx
import socket
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, BinaryIO, List
from supabase import create_client, Client
from shared.ports.storage_port import StoragePort
from config.settings import settings


class SupabaseStorageAdapter(StoragePort):
    """
    Supabase Storage Adapter with Modern JWT Authentication.
    Uses PUBLIC_KEY for read operations and SECRET_KEY for write operations.
    """
    
    def __init__(self, max_retries: int = 3, timeout: int = 30):
        # Load configuration from environment
        self.supabase_url = settings.SUPABASE_URL
        self.public_key = settings.supabase_public_key_value
        self.secret_key = settings.supabase_secret_key_value
        self.bucket_name = settings.SUPABASE_BUCKET
        self.max_retries = max_retries
        self.timeout = timeout
        
        # Validate configuration
        if not self.supabase_url:
            raise ValueError("SUPABASE_URL environment variable is required")
        if not self.public_key:
            raise ValueError("SUPABASE_PUBLIC_KEY environment variable is required")
        if not self.secret_key:
            raise ValueError("SUPABASE_SECRET_KEY environment variable is required")
        
        # Create clients
        self._init_clients()
        
        # Initialize storage
        self._ensure_bucket_exists()
    
    def _init_clients(self):
        """Initialize Supabase clients."""
        try:
            self.public_client: Client = create_client(
                self.supabase_url, 
                self.public_key
            )
            self.secret_client: Client = create_client(
                self.supabase_url, 
                self.secret_key
            )
            print("✅ Supabase clients created successfully")
        except Exception as e:
            raise Exception(f"Failed to create Supabase clients: {str(e)}")
    
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
        
        return jwt.encode(payload, self.secret_key, algorithm=settings.JWT_ALGORITHM)
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify a JWT token using PUBLIC_KEY.
        """
        try:
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
            response = self.public_client.storage.from_(self.bucket_name).list(
                path=str(Path(key).parent),
                options={"limit": 100}
            )
            
            # Handle different response types
            if isinstance(response, list):
                file_name = Path(key).name
                for file in response:
                    if file.get("name") == file_name:
                        return True
            elif isinstance(response, dict):
                data = response.get("data", [])
                file_name = Path(key).name
                for file in data:
                    if file.get("name") == file_name:
                        return True
            
            return False
        except Exception as e:
            print(f"⚠️ exists() error: {e}")
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
            response = self.secret_client.storage.from_(self.bucket_name).create_signed_url(
                key, expires_in
            )
            
            # Handle different response types
            if isinstance(response, dict):
                return response.get("signedURL", response.get("url", str(response)))
            return str(response)
        except Exception as e:
            raise Exception(f"Failed to generate signed URL: {str(e)}")
    
    async def list_files(self, prefix: str = "", limit: int = 1000) -> List[Dict[str, Any]]:
        """
        List files using PUBLIC_KEY.
        """
        try:
            response = self.public_client.storage.from_(self.bucket_name).list(
                path=prefix,
                options={"limit": limit}
            )
            
            # Handle different response types
            if isinstance(response, list):
                return response
            elif isinstance(response, dict):
                return response.get("data", [])
            else:
                return []
            
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
            response = self.public_client.storage.from_(self.bucket_name).list(
                path=str(Path(key).parent),
                options={"limit": 1, "search": Path(key).name}
            )
            
            # Handle different response types
            if isinstance(response, list) and response:
                return response[0]
            elif isinstance(response, dict):
                data = response.get("data", [])
                if data:
                    return data[0]
            
            return {}
        except Exception as e:
            print(f"⚠️ Failed to get file info: {str(e)}")
            return {}
    
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
    
    # ===== Helper Methods =====
    
    async def get_bucket_info(self) -> Dict[str, Any]:
        """
        Get information about the bucket using SECRET_KEY.
        """
        try:
            bucket_info = self.secret_client.storage.get_bucket(self.bucket_name)
            return {
                "name": bucket_info.name,
                "public": bucket_info.public,
                "created_at": bucket_info.created_at,
                "updated_at": bucket_info.updated_at,
                "file_size_limit": getattr(bucket_info, "file_size_limit", None),
                "allowed_mime_types": getattr(bucket_info, "allowed_mime_types", [])
            }
        except Exception as e:
            raise Exception(f"Failed to get bucket info: {str(e)}")
    
    async def get_storage_usage(self) -> Dict[str, Any]:
        """
        Get storage usage information.
        """
        try:
            files = await self.list_files(limit=10000)
            total_size = 0
            
            for file in files:
                if isinstance(file, dict):
                    metadata = file.get("metadata", {})
                    if isinstance(metadata, dict):
                        total_size += metadata.get("size", 0)
            
            return {
                "total_files": len(files),
                "total_size_bytes": total_size,
                "total_size_mb": total_size / (1024 * 1024),
                "total_size_gb": total_size / (1024 * 1024 * 1024)
            }
        except Exception as e:
            raise Exception(f"Failed to get storage usage: {str(e)}")
    
    async def create_folder(self, folder_path: str) -> str:
        """
        Create a folder in the bucket by uploading an empty placeholder.
        """
        try:
            # Create a placeholder file to represent the folder
            placeholder_path = f"{folder_path}/.keep"
            empty_content = b""
            
            self.secret_client.storage.from_(self.bucket_name).upload(
                path=placeholder_path,
                file=empty_content,
                file_options={
                    "content-type": "text/plain",
                    "cache-control": "3600",
                    "upsert": True
                }
            )
            
            return folder_path
        except Exception as e:
            raise Exception(f"Failed to create folder: {str(e)}")
    
    async def delete_folder(self, folder_path: str) -> bool:
        """
        Delete a folder and all its contents.
        """
        try:
            # List all files in the folder
            files = await self.list_files(prefix=folder_path)
            
            if not files:
                return True
            
            # Extract file keys
            keys = []
            for file in files:
                if isinstance(file, dict):
                    name = file.get("name")
                    if name:
                        keys.append(f"{folder_path}/{name}" if folder_path else name)
            
            if keys:
                self.secret_client.storage.from_(self.bucket_name).remove(keys)
            
            return True
        except Exception as e:
            raise Exception(f"Failed to delete folder: {str(e)}")
