"""DAW Auditor — parse a Logic Pro 11 .logicx bundle and classify tracks."""

from __future__ import annotations

import hashlib
import logging
import plistlib
import struct
from pathlib import Path
from typing import Union

from provenance.schemas import (
    ErrorResult,
    SessionMetadata,
    SessionResult,
    TrackInfo,
    TrackSummary,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reversed FourCC markers in ProjectData binary (AGENTS.md §3.1)
# ---------------------------------------------------------------------------

MARKER_TRACK = b"karT"          # Track
MARKER_AUDIO_REGION = b"gRuA"   # AudioRegion
MARKER_MIDI_SEQ = b"qeSM"      # MIDISequence
MARKER_INSTRUMENT = b"tSnI"     # Instrument
MARKER_AUDIO_FILE = b"LFUA"    # AudioFile reference

_ALL_MARKERS = {
    MARKER_TRACK: "Track",
    MARKER_AUDIO_REGION: "AudioRegion",
    MARKER_MIDI_SEQ: "MIDISequence",
    MARKER_INSTRUMENT: "Instrument",
    MARKER_AUDIO_FILE: "AudioFile",
}


def audit_session(
    logicx_path: Union[str, Path],
    seed_file_hash: str = "",
) -> SessionResult | ErrorResult:
    """Audit a Logic Pro .logicx bundle.

    Parameters
    ----------
    logicx_path:
        Path to the .logicx bundle (directory).
    seed_file_hash:
        SHA-256 hex digest of the seed audio file.  Used to distinguish
        seed tracks from human-led tracks.  If empty, all audio tracks
        are classified as ``human_led``.

    Returns
    -------
    SessionResult on success, ErrorResult on failure.
    """
    bundle = Path(logicx_path)

    if not bundle.is_dir():
        return ErrorResult(
            error=f"Not a directory / bundle: {bundle}", module="daw_auditor"
        )

    plist_path = bundle / "Alternatives" / "000" / "MetaData.plist"
    project_data_path = bundle / "Alternatives" / "000" / "ProjectData"

    if not plist_path.is_file():
        return ErrorResult(
            error=f"MetaData.plist not found at {plist_path}", module="daw_auditor"
        )
    if not project_data_path.is_file():
        return ErrorResult(
            error=f"ProjectData not found at {project_data_path}", module="daw_auditor"
        )

    try:
        meta = _parse_plist(plist_path)
        marker_counts, audio_file_hashes = _scan_project_data(
            project_data_path, bundle
        )
        tracks = _classify_tracks(marker_counts, audio_file_hashes, seed_file_hash)

        summary = _summarise(tracks)

        return SessionResult(
            project_file=bundle.name,
            logic_version=meta.get("logic_version", "unknown"),
            session_metadata=SessionMetadata(
                tempo_bpm=meta.get("tempo_bpm", 0.0),
                key_signature=meta.get("key_signature", ""),
                time_signature=meta.get("time_signature", ""),
                sample_rate=meta.get("sample_rate", 0),
            ),
            track_summary=summary,
            tracks=tracks,
        )

    except Exception as exc:
        logger.exception("daw_auditor failed")
        return ErrorResult(error=str(exc), module="daw_auditor")


# ---------------------------------------------------------------------------
# Plist parsing (AGENTS.md §3.3)
# ---------------------------------------------------------------------------


def _parse_plist(plist_path: Path) -> dict:
    """Extract session-level metadata from MetaData.plist."""
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    result: dict = {}

    # Tempo
    for key in ("tempo", "Tempo", "bpm", "BPM"):
        if key in plist:
            result["tempo_bpm"] = float(plist[key])
            break

    # Key signature
    for key in ("keySignature", "Key Signature", "key"):
        if key in plist:
            result["key_signature"] = str(plist[key])
            break
    result.setdefault("key_signature", "")

    # Time signature
    for key in ("timeSignature", "Time Signature"):
        if key in plist:
            result["time_signature"] = str(plist[key])
            break
    result.setdefault("time_signature", "")

    # Sample rate
    for key in ("sampleRate", "Sample Rate"):
        if key in plist:
            result["sample_rate"] = int(plist[key])
            break
    result.setdefault("sample_rate", 0)

    # Logic version
    for key in ("applicationVersion", "Application Version", "version"):
        if key in plist:
            result["logic_version"] = str(plist[key])
            break
    result.setdefault("logic_version", "unknown")

    return result


# ---------------------------------------------------------------------------
# Binary scanning (AGENTS.md §3.1)
# ---------------------------------------------------------------------------


def _scan_project_data(
    project_data_path: Path, bundle: Path
) -> tuple[dict[str, list[int]], set[str]]:
    """Slide a 4-byte window over ProjectData, recording marker offsets.

    Also collects SHA-256 hashes of audio files referenced in the Media/
    folder for seed-matching purposes.

    Returns
    -------
    marker_counts:
        ``{marker_name: [offset, ...]}``
    audio_file_hashes:
        Set of SHA-256 hex digests for files found under ``bundle/Media/``.
    """
    data = project_data_path.read_bytes()
    marker_offsets: dict[str, list[int]] = {name: [] for name in _ALL_MARKERS.values()}

    # Scan for FourCC markers
    for i in range(len(data) - 3):
        window = data[i : i + 4]
        if window in _ALL_MARKERS:
            name = _ALL_MARKERS[window]
            marker_offsets[name].append(i)

    # Hash audio files in Media/ for seed comparison
    audio_hashes: set[str] = set()
    media_dir = bundle / "Media"
    if media_dir.is_dir():
        for audio_file in media_dir.rglob("*"):
            if audio_file.is_file() and audio_file.suffix.lower() in (
                ".wav",
                ".aif",
                ".aiff",
                ".mp3",
                ".caf",
            ):
                audio_hashes.add(_hash_file(audio_file))

    return marker_offsets, audio_hashes


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Track classification (AGENTS.md §3.2)
# ---------------------------------------------------------------------------


def _classify_tracks(
    marker_offsets: dict[str, list[int]],
    audio_file_hashes: set[str],
    seed_file_hash: str,
) -> list[TrackInfo]:
    """Build a per-track classification list.

    Because ProjectData's binary format is not fully documented, we use
    aggregate heuristics rather than per-track chunk parsing:

    - Total track count comes from ``karT`` markers.
    - Audio region count comes from ``gRuA`` markers.
    - MIDI sequence count comes from ``qeSM`` markers.

    If we can match the seed hash inside the Media/ folder, at least one
    track is classified as ``seed``.  The remaining audio tracks are
    ``human_led``.  Tracks inferred to be MIDI-only are ``programmed``.
    """
    track_count = len(marker_offsets.get("Track", []))
    audio_region_count = len(marker_offsets.get("AudioRegion", []))
    midi_seq_count = len(marker_offsets.get("MIDISequence", []))

    if track_count == 0:
        # Fallback: estimate from other markers
        track_count = max(1, audio_region_count + midi_seq_count)

    seed_present = seed_file_hash and seed_file_hash in audio_file_hashes

    # Heuristic allocation:
    # - If seed is present, allocate 1 track as seed.
    # - Distribute audio regions across remaining audio tracks.
    # - Remaining tracks with no audio regions are programmed.

    tracks: list[TrackInfo] = []
    seed_assigned = False

    # Estimate how many tracks have audio vs MIDI
    # Simple model: each audio region belongs to a distinct audio track
    # (capped at track_count), each MIDI seq to a distinct MIDI track.
    audio_track_estimate = min(audio_region_count, track_count)
    midi_track_estimate = min(midi_seq_count, max(0, track_count - audio_track_estimate))

    for i in range(track_count):
        if i < audio_track_estimate:
            # Audio track
            if seed_present and not seed_assigned:
                tracks.append(
                    TrackInfo(
                        index=i,
                        classification="seed",
                        has_audio_regions=True,
                        audio_region_count=1,
                    )
                )
                seed_assigned = True
            else:
                tracks.append(
                    TrackInfo(
                        index=i,
                        classification="human_led",
                        has_audio_regions=True,
                        audio_region_count=max(
                            1, audio_region_count // max(audio_track_estimate, 1)
                        ),
                    )
                )
        else:
            # MIDI / programmed track
            tracks.append(
                TrackInfo(
                    index=i,
                    classification="programmed",
                    has_audio_regions=False,
                    audio_region_count=0,
                )
            )

    return tracks


def _summarise(tracks: list[TrackInfo]) -> TrackSummary:
    return TrackSummary(
        total_tracks=len(tracks),
        human_led_count=sum(1 for t in tracks if t["classification"] == "human_led"),
        seed_count=sum(1 for t in tracks if t["classification"] == "seed"),
        programmed_count=sum(1 for t in tracks if t["classification"] == "programmed"),
    )
