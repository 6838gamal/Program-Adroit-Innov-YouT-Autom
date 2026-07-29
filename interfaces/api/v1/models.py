"""
HuggingFace Model Library API.
CRUD for the user's personal HF model registry + enable/disable/activate actions.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.session import get_db
from infrastructure.database.models.hf_model_model import HFModelModel
from infrastructure.repositories.sql_hf_model_repository import SQLHFModelRepository

router = APIRouter(prefix="/models", tags=["models"])
logger = logging.getLogger(__name__)

# ── Schemas ───────────────────────────────────────────────────────────────────

class AddModelRequest(BaseModel):
    hf_model_id: str          # e.g. "facebook/mms-tts-ara"
    model_type: str           # "tts" | "text-to-image" | "text-to-video"
    name: Optional[str] = ""
    description: Optional[str] = ""
    config: Optional[dict] = {}

class UpdateModelRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_enabled: Optional[bool] = None
    is_active: Optional[bool] = None
    config: Optional[dict] = None

# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_hf_metadata(hf_model_id: str) -> dict:
    """Fetch model card metadata from HuggingFace Hub (best-effort)."""
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        info = api.model_info(hf_model_id)
        return {
            "pipeline_tag": getattr(info, "pipeline_tag", ""),
            "library_name": getattr(info, "library_name", ""),
            "tags": list(getattr(info, "tags", []) or []),
            "languages": list(getattr(info, "card_data", None) and
                              getattr(info.card_data, "language", []) or []),
            "downloads": getattr(info, "downloads", 0),
            "likes": getattr(info, "likes", 0),
        }
    except Exception as e:
        logger.warning("Could not fetch HF metadata for %s: %s", hf_model_id, e)
        return {}

# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_models(
    model_type: Optional[str] = None,
    session: AsyncSession = Depends(get_db),
):
    repo = SQLHFModelRepository(session)
    models = await repo.list_all(model_type=model_type)
    return [m.to_dict() for m in models]


@router.post("", status_code=201)
async def add_model(
    body: AddModelRequest,
    session: AsyncSession = Depends(get_db),
):
    repo = SQLHFModelRepository(session)

    # Check duplicate
    existing = await repo.get_by_hf_id(body.hf_model_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"النموذج {body.hf_model_id!r} موجود بالفعل")

    # Validate type
    valid_types = ("tts", "text-to-image", "text-to-video")
    if body.model_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"نوع النموذج يجب أن يكون أحد: {valid_types}")

    # Fetch HF metadata
    meta = _fetch_hf_metadata(body.hf_model_id)

    model = HFModelModel(
        hf_model_id=body.hf_model_id,
        name=body.name or body.hf_model_id.split("/")[-1],
        model_type=body.model_type,
        description=body.description or meta.get("pipeline_tag", ""),
        tags=meta.get("tags", []),
        languages=meta.get("languages", []),
        config=body.config or {},
        hf_metadata=meta,
        is_enabled=True,
        is_active=False,
    )
    await repo.save(model)
    await session.commit()
    return model.to_dict()


@router.get("/{model_id}")
async def get_model(model_id: str, session: AsyncSession = Depends(get_db)):
    repo = SQLHFModelRepository(session)
    model = await repo.get(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="النموذج غير موجود")
    return model.to_dict()


@router.patch("/{model_id}")
async def update_model(
    model_id: str,
    body: UpdateModelRequest,
    session: AsyncSession = Depends(get_db),
):
    repo = SQLHFModelRepository(session)
    model = await repo.get(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="النموذج غير موجود")

    if body.name is not None:
        model.name = body.name
    if body.description is not None:
        model.description = body.description
    if body.is_enabled is not None:
        model.is_enabled = body.is_enabled
    if body.config is not None:
        model.config = {**model.config, **body.config}

    # Setting active deactivates others of same type
    if body.is_active is True:
        await repo.set_active(model_id, model.model_type)
    elif body.is_active is False:
        model.is_active = False

    await repo.save(model)
    await session.commit()
    return model.to_dict()


@router.post("/{model_id}/activate")
async def activate_model(model_id: str, session: AsyncSession = Depends(get_db)):
    """Set this model as the active default for its type."""
    repo = SQLHFModelRepository(session)
    model = await repo.get(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="النموذج غير موجود")
    await repo.set_active(model_id, model.model_type)
    await session.commit()
    return {"ok": True, "active": model_id}


@router.delete("/{model_id}", status_code=204)
async def delete_model(model_id: str, session: AsyncSession = Depends(get_db)):
    repo = SQLHFModelRepository(session)
    deleted = await repo.delete(model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="النموذج غير موجود")
    await session.commit()


@router.post("/{model_id}/test")
async def test_model(model_id: str, session: AsyncSession = Depends(get_db)):
    """Quick connectivity test — tries to call HF Inference API with a short prompt."""
    repo = SQLHFModelRepository(session)
    model = await repo.get(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="النموذج غير موجود")

    try:
        from huggingface_hub import InferenceClient
        client = InferenceClient()

        if model.model_type == "tts":
            audio = client.text_to_speech("مرحبا", model=model.hf_model_id)
            return {"ok": True, "bytes": len(audio), "model": model.hf_model_id}

        elif model.model_type == "text-to-image":
            import io
            img = client.text_to_image("a simple test image", model=model.hf_model_id,
                                       width=256, height=256)
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            return {"ok": True, "bytes": buf.tell(), "model": model.hf_model_id}

        else:
            return {"ok": True, "note": "نوع النموذج لا يدعم الاختبار المباشر حالياً"}

    except Exception as e:
        return {"ok": False, "error": str(e)}
