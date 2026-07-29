"""Repository for HuggingFace model registry."""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from infrastructure.database.models.hf_model_model import HFModelModel


class SQLHFModelRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, model_id: str) -> HFModelModel | None:
        result = await self._session.execute(
            select(HFModelModel).where(HFModelModel.id == model_id)
        )
        return result.scalar_one_or_none()

    async def get_by_hf_id(self, hf_model_id: str) -> HFModelModel | None:
        result = await self._session.execute(
            select(HFModelModel).where(HFModelModel.hf_model_id == hf_model_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self, model_type: str | None = None) -> list[HFModelModel]:
        q = select(HFModelModel).order_by(HFModelModel.created_at.desc())
        if model_type:
            q = q.where(HFModelModel.model_type == model_type)
        result = await self._session.execute(q)
        return list(result.scalars().all())

    async def list_enabled(self, model_type: str | None = None) -> list[HFModelModel]:
        q = (select(HFModelModel)
             .where(HFModelModel.is_enabled == True)
             .order_by(HFModelModel.is_active.desc(), HFModelModel.created_at.desc()))
        if model_type:
            q = q.where(HFModelModel.model_type == model_type)
        result = await self._session.execute(q)
        return list(result.scalars().all())

    async def get_active(self, model_type: str) -> HFModelModel | None:
        result = await self._session.execute(
            select(HFModelModel).where(
                HFModelModel.model_type == model_type,
                HFModelModel.is_active == True,
                HFModelModel.is_enabled == True,
            )
        )
        return result.scalar_one_or_none()

    async def save(self, model: HFModelModel) -> HFModelModel:
        self._session.add(model)
        await self._session.flush()
        return model

    async def delete(self, model_id: str) -> bool:
        model = await self.get(model_id)
        if not model:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    async def set_active(self, model_id: str, model_type: str) -> None:
        """Deactivate all models of this type, then activate the given one."""
        await self._session.execute(
            update(HFModelModel)
            .where(HFModelModel.model_type == model_type)
            .values(is_active=False)
        )
        await self._session.execute(
            update(HFModelModel)
            .where(HFModelModel.id == model_id)
            .values(is_active=True)
        )
        await self._session.flush()
