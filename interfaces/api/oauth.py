"""
OAuth2 callback routes for platform connections.
Handles Google/YouTube OAuth2 flow.
"""
import json
import logging
import os
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.session import get_db
from infrastructure.repositories.sql_publishing_repository import SQLAccountRepository
from publishing.domain.publisher_account import PublisherAccount

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/oauth", tags=["oauth"])


def _get_redirect_uri(request: Request) -> str:
    """Build the OAuth callback URL dynamically from the request host."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/oauth/youtube/callback"


def _youtube_plugin():
    from plugins.publishers.youtube.youtube_plugin import YouTubePublisherPlugin
    return YouTubePublisherPlugin()


# ── Step 1: Start OAuth flow ──────────────────────────────────────────────────
@router.get("/youtube/start")
async def youtube_oauth_start(request: Request):
    plugin = _youtube_plugin()

    if not plugin.is_configured:
        return HTMLResponse(
            content=_error_page(
                "يوتيوب غير مهيأ",
                "لم يتم ضبط YOUTUBE_CLIENT_ID و YOUTUBE_CLIENT_SECRET بعد. "
                "أضف المتغيرات في إعدادات المشروع ثم أعد المحاولة.",
            ),
            status_code=503,
        )

    redirect_uri = _get_redirect_uri(request)
    auth_url, state = plugin.get_authorization_url(redirect_uri)

    # Store state in session cookie for CSRF check
    response = RedirectResponse(auth_url)
    response.set_cookie("yt_oauth_state", state, httponly=True, samesite="lax", max_age=600)
    return response


# ── Step 2: Google redirects back ─────────────────────────────────────────────
@router.get("/youtube/callback")
async def youtube_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: AsyncSession = Depends(get_db),
):
    # Handle user denial
    if error:
        return RedirectResponse(
            f"/platforms?error={error}",
            status_code=302,
        )

    if not code:
        return HTMLResponse(_error_page("خطأ OAuth", "لم يتم استلام رمز التفويض."), status_code=400)

    # CSRF state check (best-effort)
    stored_state = request.cookies.get("yt_oauth_state")
    if stored_state and stored_state != state:
        return HTMLResponse(_error_page("خطأ أمني", "قيمة state غير متطابقة — أعد المحاولة."), status_code=403)

    plugin = _youtube_plugin()
    redirect_uri = _get_redirect_uri(request)

    try:
        credentials = plugin.exchange_code(code, redirect_uri)
    except Exception as e:
        logger.error("OAuth token exchange failed: %s", e)
        return HTMLResponse(_error_page("فشل استبدال الرمز", str(e)), status_code=400)

    # Validate credentials and fetch channel info
    auth_result = await plugin.authenticate(credentials)
    if not auth_result.success:
        return HTMLResponse(_error_page("فشل التحقق", auth_result.error or "خطأ غير معروف"), status_code=401)

    # Persist channel info inside credentials
    credentials["channel_info"] = auth_result.channel_info

    # Save account
    channel_title = auth_result.channel_info.get("channel_title", "قناة YouTube")
    account = PublisherAccount(
        name=channel_title,
        platform_name="youtube",
        credentials_encrypted=json.dumps(credentials),
    )
    account.verify()

    repo = SQLAccountRepository(session)
    await repo.save(account)

    logger.info("YouTube account connected: %s", channel_title)

    response = RedirectResponse("/platforms?connected=youtube", status_code=302)
    response.delete_cookie("yt_oauth_state")
    return response


# ── Helper HTML ───────────────────────────────────────────────────────────────
def _error_page(title: str, message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head><meta charset="UTF-8"><title>{title}</title>
<style>body{{background:#0f172a;color:#e2e8f0;font-family:system-ui;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.box{{background:#1e293b;border:1px solid #334155;border-radius:1rem;padding:2rem;max-width:480px;text-align:center}}
h1{{color:#f87171;margin:0 0 1rem}}p{{color:#94a3b8;margin:0 0 1.5rem}}
a{{background:#2563eb;color:#fff;padding:.6rem 1.5rem;border-radius:.5rem;text-decoration:none;display:inline-block}}
</style></head>
<body><div class="box">
<h1>⚠️ {title}</h1>
<p>{message}</p>
<a href="/platforms">← العودة للمنصات</a>
</div></body></html>"""
