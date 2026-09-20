"""Diagnostic helpers — print + log immediately."""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _diag(msg: str) -> None:
    """Print + log a diagnostic message immediately."""
    print(msg, flush=True)
    logger.info(msg)


def _diag_err(msg: str, exc: Optional[BaseException] = None) -> None:
    """Print + log an error."""
    print(msg, flush=True)
    if exc is not None:
        logger.error(msg, exc_info=exc)
    else:
        logger.error(msg)
