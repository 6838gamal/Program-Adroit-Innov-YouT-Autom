"""Edge TTS service — free Microsoft TTS."""
from fastapi import HTTPException


async def edge_tts_generate(
    text: str,
    voice: str = "ar-SA-HamedNeural",
    rate: str = "+0%",
    volume: str = "+0%",
    pitch: str = "+0Hz",
) -> bytes:
    """توليد صوت عبر Edge TTS (Microsoft)."""
    try:
        import edge_tts

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            volume=volume,
            pitch=pitch,
        )

        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        if not audio_chunks:
            raise RuntimeError("Edge TTS returned no audio")

        return b"".join(audio_chunks)

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="Edge TTS غير مثبت. شغّل: pip install edge-tts",
        )
