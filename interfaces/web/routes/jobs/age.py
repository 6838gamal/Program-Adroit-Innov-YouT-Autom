"""Compute job age for stale-job detection."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _compute_job_age_seconds(job: Dict[str, Any]) -> Optional[float]:
    """
    احسب عمر الـ job بالثواني.
    يتعامل مع timestamps مع/بدون timezone.
    """
    updated = job.get("_updated_at") or job.get("created_at")
    if not updated:
        return None

    try:
        updated_str = str(updated)

        if updated_str.endswith("Z"):
            updated_str = updated_str[:-1]

        if "+" in updated_str:
            updated_str = updated_str.split("+")[0]

        updated_dt = datetime.fromisoformat(updated_str)
        now_naive = datetime.utcnow()
        age_seconds = (now_naive - updated_dt).total_seconds()

        return age_seconds

    except Exception as e:
        logger.warning(f"Failed to compute job age: {e}")
        return None
