"""
HuggingFace Image Generation Plugin.
Runs any HF text-to-image model via the HF Inference API.
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class HFImagePlugin:
    """
    Image generation plugin backed by a HuggingFace text-to-image model.
    model_id: e.g. "stabilityai/stable-diffusion-xl-base-1.0",
                   "black-forest-labs/FLUX.1-schnell"
    """

    def __init__(self, model_id: str, hf_token: str | None = None, config: dict | None = None):
        self._model_id = model_id
        self._token = hf_token
        self._config = config or {}

    def is_available(self) -> bool:
        try:
            from huggingface_hub import InferenceClient  # noqa: F401
            return True
        except ImportError:
            return False

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        width: int = 1024,
        height: int = 576,
        negative_prompt: str = "",
        seed: Optional[int] = None,
    ) -> Path:
        """Generate an image from text prompt via HF Inference API."""
        try:
            from huggingface_hub import InferenceClient

            loop = asyncio.get_event_loop()

            def _call_api():
                client = InferenceClient(token=self._token)
                kwargs = dict(
                    prompt=prompt,
                    model=self._model_id,
                    width=width,
                    height=height,
                )
                if negative_prompt:
                    kwargs["negative_prompt"] = negative_prompt
                if seed is not None:
                    kwargs["seed"] = seed
                # Returns a PIL Image
                img = client.text_to_image(**kwargs)
                return img

            pil_img = await loop.run_in_executor(None, _call_api)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pil_img.save(str(output_path), "JPEG", quality=95)
            logger.info("HF Image [%s] → %s", self._model_id, output_path.name)
            return output_path

        except Exception as e:
            logger.error("HF Image [%s] failed: %s — falling back to Pillow", self._model_id, e)
            return await self._pillow_fallback(prompt, output_path, width, height)

    @staticmethod
    async def _pillow_fallback(text: str, output_path: Path, width: int, height: int) -> Path:
        """Fall back to Pillow generator if HF API fails."""
        from plugins.image_gen.pillow_generator import SceneImageGenerator
        gen = SceneImageGenerator(width=width, height=height)
        return await gen.generate_scene_image(
            text=text, output_path=output_path, scene_index=0
        )
