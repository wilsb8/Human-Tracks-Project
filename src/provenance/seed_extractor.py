"""Seed Extractor — parse a Suno audio file and extract provenance fields."""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

import mutagen
from mutagen.id3 import ID3
from mutagen.wave import WAVE

from provenance.schemas import ErrorResult, SeedResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metadata allowlist (AGENTS.md §1.3)
# ---------------------------------------------------------------------------

_ALLOWED_ID3_FRAMES = frozenset({"TSSE", "TENC", "TDRC", "TYER", "TDAT", "TOFN"})
_ALLOWED_TXXX_KEYS = frozenset({"encoder", "software", "tool", "version", "creation_date"})
_ALLOWED_RIFF_CHUNKS = frozenset({"ISFT", "ICRD", "IDIT"})


def extract_seed(audio_path: Union[str, Path]) -> SeedResult | ErrorResult:
    """Extract provenance fields from a Suno-exported audio file.

    Parameters
    ----------
    audio_path:
        Path to an MP3 or WAV file downloaded from Suno.

    Returns
    -------
    SeedResult on success, ErrorResult on failure.
    """
    path = Path(audio_path)

    if not path.is_file():
        return ErrorResult(error=f"File not found: {path}", module="seed_extractor")

    suffix = path.suffix.lower()
    if suffix not in (".mp3", ".wav"):
        return ErrorResult(
            error=f"Unsupported format '{suffix}'. Expected .mp3 or .wav",
            module="seed_extractor",
        )

    try:
        file_hash = _hash_file(path)
        seed_id = file_hash[:16]

        if suffix == ".mp3":
            metadata, timestamp = _parse_mp3(path)
        else:
            metadata, timestamp = _parse_wav(path)

        # Fallback timestamp: file creation time
        if not timestamp:
            stat = path.stat()
            ctime = getattr(stat, "st_birthtime", stat.st_mtime)
            timestamp = datetime.fromtimestamp(ctime, tz=timezone.utc).isoformat()

        return SeedResult(
            seed_id=seed_id,
            origin_timestamp=timestamp,
            source_format=suffix.lstrip("."),
            source_file_hash=file_hash,
            metadata_fields=metadata,
        )

    except Exception as exc:
        logger.exception("seed_extractor failed")
        return ErrorResult(error=str(exc), module="seed_extractor")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hash_file(path: Path) -> str:
    """Return the full SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_mp3(path: Path) -> tuple[dict[str, str], str]:
    """Extract allowed ID3v2 metadata from an MP3 file."""
    metadata: dict[str, str] = {}
    timestamp = ""

    try:
        tags = ID3(str(path))
    except mutagen.MutagenError:
        logger.warning("No ID3 tags found in %s", path.name)
        return metadata, timestamp

    for frame_id, frame in tags.items():
        base_id = frame_id.split(":")[0] if ":" in frame_id else frame_id

        # Standard allowed frames
        if base_id in _ALLOWED_ID3_FRAMES:
            value = str(frame)
            metadata[base_id] = value
            if base_id in ("TDRC", "TYER") and not timestamp:
                timestamp = _normalise_timestamp(value)

        # TXXX custom frames — check key allowlist
        elif base_id == "TXXX":
            desc = getattr(frame, "desc", "").lower()
            if desc in _ALLOWED_TXXX_KEYS:
                metadata[f"TXXX:{desc}"] = str(frame)

    return metadata, timestamp


def _parse_wav(path: Path) -> tuple[dict[str, str], str]:
    """Extract allowed RIFF INFO / ID3 metadata from a WAV file."""
    metadata: dict[str, str] = {}
    timestamp = ""

    try:
        wav = WAVE(str(path))
    except mutagen.MutagenError:
        logger.warning("Cannot read WAV metadata from %s", path.name)
        return metadata, timestamp

    # mutagen exposes RIFF INFO tags on WAVE objects
    if wav.tags is not None:
        for key, value in wav.tags.items():
            upper_key = key.upper() if isinstance(key, str) else key
            if upper_key in _ALLOWED_RIFF_CHUNKS:
                val_str = str(value)
                metadata[upper_key] = val_str
                if upper_key in ("ICRD", "IDIT") and not timestamp:
                    timestamp = _normalise_timestamp(val_str)

    # Some WAVs carry an embedded ID3 chunk
    try:
        id3_tags = ID3(str(path))
        for frame_id, frame in id3_tags.items():
            base_id = frame_id.split(":")[0] if ":" in frame_id else frame_id
            if base_id in _ALLOWED_ID3_FRAMES:
                metadata[base_id] = str(frame)
                if base_id in ("TDRC", "TYER") and not timestamp:
                    timestamp = _normalise_timestamp(str(frame))
    except mutagen.MutagenError:
        pass  # No embedded ID3 — that's fine for WAV

    return metadata, timestamp


def _normalise_timestamp(raw: str) -> str:
    """Best-effort conversion to ISO-8601."""
    raw = raw.strip()
    # Already ISO-ish
    if "T" in raw or len(raw) == 10 and "-" in raw:
        return raw
    # Plain year
    if raw.isdigit() and len(raw) == 4:
        return f"{raw}-01-01T00:00:00+00:00"
    return raw
