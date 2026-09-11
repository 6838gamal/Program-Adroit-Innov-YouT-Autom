"""Backward-compatibility alias for Supabase client access.

This module exists because production_service.py imports:
    from infrastructure.storage.supabase_storage import get_supabase_client

But the actual adapter lives in supabase_storage_adapter.py.
"""
import logging
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

_supabase_client = None


def get_supabase_client():
    """
    Return a Supabase client instance compatible with the legacy API.

    Tries multiple strategies:
      1. Use SupabaseStorageAdapter if it exposes a `.client` attribute.
      2. Build a raw supabase.Client from settings.
    """
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    # Strategy 1: delegate to SupabaseStorageAdapter
    try:
        from infrastructure.storage.supabase_storage_adapter import SupabaseStorageAdapter
        adapter = SupabaseStorageAdapter()
        client = getattr(adapter, "client", None)
        if client is not None:
            _supabase_client = client
            return _supabase_client
    except Exception as e:
        logger.warning("SupabaseStorageAdapter path failed: %s", e)

    # Strategy 2: build raw supabase.Client
    try:
        from supabase import create_client
        url = settings.SUPABASE_URL
        key = settings.supabase_secret_key_value or settings.supabase_public_key_value
        if url and key:
            _supabase_client = create_client(url, key)
            logger.info("✅ Supabase client created (raw)")
            return _supabase_client
        else:
            logger.warning("Supabase URL/key missing — client not created")
            return None
    except Exception as e:
        logger.error("Failed to create Supabase client: %s", e)
        return None
