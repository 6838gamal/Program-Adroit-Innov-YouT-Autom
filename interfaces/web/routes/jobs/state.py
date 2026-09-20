"""Shared in-memory state للـ jobs والأصوات."""
from typing import Any, Dict

CLONED_VOICE_CACHE: Dict[str, str] = {}
TALKING_HEAD_JOBS: Dict[str, Dict[str, Any]] = {}
