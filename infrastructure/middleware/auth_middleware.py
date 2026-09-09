from fastapi import Request, HTTPException
from typing import Optional
from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter


class SupabaseAuthMiddleware:
    """
    Authentication middleware using Supabase JWT tokens.
    Verifies tokens with PUBLIC_KEY.
    """
    
    def __init__(self):
        self.storage = SupabaseStorageAdapter()
    
    async def __call__(self, request: Request):
        token = self._extract_token(request)
        if token:
            try:
                user_data = self.storage.verify_token(token)
                request.state.user = user_data
                request.state.token = token
            except Exception as e:
                raise HTTPException(status_code=401, detail=str(e))
    
    def _extract_token(self, request: Request) -> Optional[str]:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header.split(" ")[1]
        return None
