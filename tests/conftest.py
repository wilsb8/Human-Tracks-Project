"""Shared test fixtures — synthetic audio files and .logicx bundles."""

from __future__ import annotations

import hashlib
import plistlib
import struct
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# Synthetic MP3 with minimal valid ID3v2 header + allowed frames
# ---------------------------------------------------------------------------

def _make_id3v2_tag(frames: dict[str, bytes]) -> bytes:
    """Build a minimal ID3v2.3 tag from a {frame_id: payload} dict."""
    frame_data = b""
    for fid, payload in frames.items():
        fid_bytes = fid.encode("ascii")[:4].ljust(4, b"\x00")
        size = struct.pack(">I", len(payload))
        flags = b"\x00\x00"
        frame_data += fid_bytes + size + flags + payload

    # ID3v2 header: "ID3" + version 2.3 + no flags + synchsafe size
    tag_size = len(frame_data)
    ss = _synchsafe(tag_size)
    header = b"ID3" + b"\x03\x00" + b"\x00" + ss
    return header + frame_data


def _synchsafe(n: int) -> bytes:
    """Encode an integer as 4-byte synchsafe (7 bits per byte)."""
    out = bytearray(4)
    for i in range(3, -1, -1):
        out[i] = n & 0x7F
        n >>= 7
    return bytes(out)


def _text_frame(text: str) -> bytes:
    """UTF-8 text frame payload (encoding byte 0x03 = UTF-8)."""
    return b"\x03" + text.encode("utf-8")


@pytest.fixture()
def synthetic_mp3(tmp_dir: Path) -> Path:
    """Create a tiny file with a valid ID3v2 header and dummy MPEG frames."""
    frames = {
        "TSSE": _text_frame("Suno/v3.5"),
        "TENC": _text_frame("suno-encoder"),
        "TDRC": _text_frame("2026-04-15"),
    }
    tag = _make_id3v2_tag(frames)
    # Append a minimal (silent) MPEG frame so mutagen doesn't reject it.
    # MPEG1 Layer3 44100Hz 128kbps frame header + zero padding
    mpeg_header = b"\xff\xfb\x90\x00"
    mpeg_frame = mpeg_header + b"\x00" * 413  # ~417 bytes per frame at 128kbps

    mp3_path = tmp_dir / "seed.mp3"
    mp3_path.write_bytes(tag + mpeg_frame)
    return mp3_path


# ---------------------------------------------------------------------------
# Synthetic WAV (44-byte header + 0 samples is valid RIFF)
# ---------------------------------------------------------------------------

@pytest.fixture()
def synthetic_wav(tmp_dir: Path) -> Path:
    """Create a minimal valid WAV file."""
    sample_rate = 44100
    num_channels = 1
    bits_per_sample = 16
    data = b"\x00\x00" * 100  # 100 silent samples

    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(data)
    riff_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", riff_size, b"WAVE",
        b"fmt ", 16, 1,  # PCM
        num_channels, sample_rate, byte_rate, block_align, bits_per_sample,
        b"data", data_size,
    )

    wav_path = tmp_dir / "seed.wav"
    wav_path.write_bytes(header + data)
    return wav_path


# ---------------------------------------------------------------------------
# Synthetic .logicx bundle
# ---------------------------------------------------------------------------

@pytest.fixture()
def synthetic_logicx(tmp_dir: Path, synthetic_mp3: Path) -> Path:
    """Create a minimal .logicx bundle with known markers."""
    bundle = tmp_dir / "TestProject.logicx"
    alt_dir = bundle / "Alternatives" / "000"
    media_dir = bundle / "Media"
    alt_dir.mkdir(parents=True)
    media_dir.mkdir(parents=True)

    # MetaData.plist
    plist_data = {
        "tempo": 120.0,
        "keySignature": "C minor",
        "timeSignature": "4/4",
        "sampleRate": 44100,
        "applicationVersion": "11.1",
    }
    with open(alt_dir / "MetaData.plist", "wb") as f:
        plistlib.dump(plist_data, f)

    # ProjectData: inject known FourCC markers
    # 3 tracks, 2 audio regions, 1 MIDI sequence
    pd = bytearray()
    pd += b"\x00" * 16
    pd += b"karT" + b"\x00" * 32  # Track 0
    pd += b"gRuA" + b"\x00" * 32  # AudioRegion
    pd += b"karT" + b"\x00" * 32  # Track 1
    pd += b"gRuA" + b"\x00" * 32  # AudioRegion
    pd += b"karT" + b"\x00" * 32  # Track 2
    pd += b"qeSM" + b"\x00" * 32  # MIDISequence
    pd += b"\x00" * 16
    (alt_dir / "ProjectData").write_bytes(bytes(pd))

    # Copy seed into Media/ so hash matching works
    import shutil
    shutil.copy2(synthetic_mp3, media_dir / "seed.mp3")

    return bundle


@pytest.fixture()
def seed_file_hash(synthetic_mp3: Path) -> str:
    """SHA-256 of the synthetic MP3."""
    h = hashlib.sha256()
    with open(synthetic_mp3, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()
