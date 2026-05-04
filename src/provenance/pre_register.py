"""Pre-Register — fingerprint an audio file before uploading it to Suno.

This establishes a timestamped proof that the file existed in your
possession *before* it entered the AI pipeline.  The resulting JSON
receipt can be threaded into the downstream loopback record so the
final C2PA manifest carries an unbroken chain:

    your original audio → Suno processing → DAW session → signed master
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

import mutagen
from mutagen.id3 import ID3
from mutagen.wave import WAVE

from provenance.schemas import ErrorResult, PreRegistration

logger = logging.getLogger(__name__)

# Reuse the same allowlist as seed_extractor (AGENTS.md §1.3)
_ALLOWED_ID3_FRAMES = frozenset({"TSSE", "TENC", "TDRC", "TYER", "TDAT", "TOFN"})
_ALLOWED_TXXX_KEYS = frozenset({"encoder", "software", "tool", "version", "creation_date"})
_ALLOWED_RIFF_CHUNKS = frozenset({"ISFT", "ICRD", "IDIT"})

_SUPPORTED_EXTENSIONS = frozenset({".mp3", ".wav", ".aif", ".aiff", ".flac"})


def pre_register(audio_path: Union[str, Path]) -> PreRegistration | ErrorResult:
    """Fingerprint an audio file and produce a pre-registration receipt.

    Parameters
    ----------
    audio_path:
        Path to your original audio file (MP3, WAV, AIF, FLAC).

    Returns
    -------
    PreRegistration on success, ErrorResult on failure.
    """
    path = Path(audio_path)

    if not path.is_file():
        return ErrorResult(error=f"File not found: {path}", module="pre_register")

    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED_EXTENSIONS:
        return ErrorResult(
            error=f"Unsupported format '{suffix}'. Expected one of: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}",
            module="pre_register",
        )

    try:
        file_hash = _hash_file(path)
        pre_reg_id = file_hash[:16]
        registered_at = datetime.now(timezone.utc).isoformat()
        metadata = _extract_metadata(path, suffix)

        return PreRegistration(
            pre_reg_id=pre_reg_id,
            original_file_hash=file_hash,
            original_format=suffix.lstrip("."),
            registered_at=registered_at,
            metadata_fields=metadata,
        )

    except Exception as exc:
        logger.exception("pre_register failed")
        return ErrorResult(error=str(exc), module="pre_register")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_metadata(path: Path, suffix: str) -> dict[str, str]:
    """Extract only allowed mechanical metadata from the audio file."""
    metadata: dict[str, str] = {}

    # Try ID3 (works for MP3, some WAV/AIF)
    try:
        tags = ID3(str(path))
        for frame_id, frame in tags.items():
            base_id = frame_id.split(":")[0] if ":" in frame_id else frame_id
            if base_id in _ALLOWED_ID3_FRAMES:
                metadata[base_id] = str(frame)
            elif base_id == "TXXX":
                desc = getattr(frame, "desc", "").lower()
                if desc in _ALLOWED_TXXX_KEYS:
                    metadata[f"TXXX:{desc}"] = str(frame)
    except mutagen.MutagenError:
        pass

    # Try RIFF INFO for WAV
    if suffix == ".wav":
        try:
            wav = WAVE(str(path))
            if wav.tags is not None:
                for key, value in wav.tags.items():
                    upper = key.upper() if isinstance(key, str) else key
                    if upper in _ALLOWED_RIFF_CHUNKS:
                        metadata[upper] = str(value)
        except mutagen.MutagenError:
            pass

    return metadata
