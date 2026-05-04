"""Integration tests — full provenance chain from pre-registration to signing.

These tests drive real module calls through every pipeline stage,
validate cross-module data linkage, determinism guarantees, metadata
stripping, binary edge cases, CLI subprocess invocation, and c2pa_signer
input validation.
"""

from __future__ import annotations

import hashlib
import json
import plistlib
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest


# ======================================================================
# Helpers
# ======================================================================

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI as a subprocess to test real argument parsing."""
    return subprocess.run(
        [sys.executable, "-m", "provenance.cli", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
             "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )


# ======================================================================
# Full chain: pre-register → seed-extract → daw-audit → loopback
# ======================================================================


class TestFullChainIntegration:
    """Drive the complete pipeline through Python API calls and verify
    every inter-module contract."""

    def test_workflow_b_full_chain(
        self, synthetic_mp3: Path, synthetic_logicx: Path, seed_file_hash: str
    ) -> None:
        """Workflow B: pre-register → seed-extract → daw-audit → loopback.
        Verify the provenance record carries all three data layers."""
        from provenance.daw_auditor import audit_session
        from provenance.loopback_engine import build_provenance
        from provenance.pre_register import pre_register
        from provenance.seed_extractor import extract_seed

        # Stage 0 — Pre-register
        pre_reg = pre_register(synthetic_mp3)
        assert "error" not in pre_reg

        # Stage 1 — Seed extract (same file simulates Suno returning it)
        seed = extract_seed(synthetic_mp3)
        assert "error" not in seed

        # Stage 2 — DAW audit
        session = audit_session(synthetic_logicx, seed_file_hash=seed["source_file_hash"])
        assert "error" not in session

        # Stage 3 — Loopback with pre-registration
        provenance = build_provenance(seed, session, pre_registration=pre_reg)
        assert "error" not in provenance

        # --- Verify provenance record structure ---
        assert "loopback_id" in provenance
        assert "seed" in provenance
        assert "session" in provenance
        assert "provenance_timestamp" in provenance
        assert "pre_registration" in provenance

        # Verify seed section links back to the file
        assert provenance["seed"]["seed_id"] == seed["seed_id"]
        assert provenance["seed"]["source_file_hash"] == seed["source_file_hash"]

        # Verify session section carries DAW metadata
        assert provenance["session"]["project_file"] == "TestProject.logicx"
        assert provenance["session"]["tempo_bpm"] == 120.0
        assert provenance["session"]["total_tracks"] == 3
        assert provenance["session"]["human_led_count"] == 1
        assert provenance["session"]["seed_count"] == 1
        assert provenance["session"]["programmed_count"] == 1

        # Verify pre-registration carries the original fingerprint
        assert provenance["pre_registration"]["pre_reg_id"] == pre_reg["pre_reg_id"]
        assert provenance["pre_registration"]["original_file_hash"] == pre_reg["original_file_hash"]

    def test_workflow_a_no_pre_reg(
        self, synthetic_mp3: Path, synthetic_logicx: Path, seed_file_hash: str
    ) -> None:
        """Workflow A: seed-extract → daw-audit → loopback (no pre-reg).
        pre_registration must be absent from the output."""
        from provenance.daw_auditor import audit_session
        from provenance.loopback_engine import build_provenance
        from provenance.seed_extractor import extract_seed

        seed = extract_seed(synthetic_mp3)
        session = audit_session(synthetic_logicx, seed_file_hash=seed["source_file_hash"])
        provenance = build_provenance(seed, session)

        assert "error" not in provenance
        assert "pre_registration" not in provenance
        assert provenance["session"]["seed_count"] == 1


# ======================================================================
# Hash linkage — the core trust property
# ======================================================================


class TestHashLinkage:
    """The chain of trust relies on SHA-256 hashes matching across stages."""

    def test_pre_reg_hash_equals_seed_hash_for_same_file(self, synthetic_mp3: Path) -> None:
        """When the same file is both pre-registered and seed-extracted,
        the hashes must be identical."""
        from provenance.pre_register import pre_register
        from provenance.seed_extractor import extract_seed

        pre_reg = pre_register(synthetic_mp3)
        seed = extract_seed(synthetic_mp3)

        assert pre_reg["original_file_hash"] == seed["source_file_hash"]
        # pre_reg_id and seed_id are both hash[:16] of the same file
        assert pre_reg["pre_reg_id"] == seed["seed_id"]

    def test_seed_hash_matches_daw_media_detection(
        self, synthetic_mp3: Path, synthetic_logicx: Path, seed_file_hash: str
    ) -> None:
        """The seed file hash must match one of the files in .logicx/Media/."""
        from provenance.seed_extractor import extract_seed

        seed = extract_seed(synthetic_mp3)
        # The conftest copies synthetic_mp3 into Media/, so:
        media_hash = _sha256(synthetic_logicx / "Media" / "seed.mp3")
        assert seed["source_file_hash"] == media_hash

    def test_hash_computed_on_raw_bytes_not_parsed_content(self, synthetic_mp3: Path) -> None:
        """AGENTS.md §2.4: hash computations use raw file bytes."""
        from provenance.seed_extractor import extract_seed

        expected = _sha256(synthetic_mp3)
        result = extract_seed(synthetic_mp3)
        assert result["source_file_hash"] == expected

    def test_different_files_produce_different_hashes(
        self, synthetic_mp3: Path, synthetic_wav: Path
    ) -> None:
        from provenance.seed_extractor import extract_seed

        r1 = extract_seed(synthetic_mp3)
        r2 = extract_seed(synthetic_wav)
        assert r1["source_file_hash"] != r2["source_file_hash"]
        assert r1["seed_id"] != r2["seed_id"]


# ======================================================================
# Determinism — identical inputs → identical outputs (AGENTS.md §2.4)
# ======================================================================


class TestDeterminism:
    def test_loopback_id_deterministic_across_runs(self) -> None:
        from provenance.loopback_engine import build_provenance

        seed = {
            "seed_id": "aaaa1111bbbb2222",
            "origin_timestamp": "2026-01-01T00:00:00+00:00",
            "source_format": "mp3",
            "source_file_hash": "c" * 64,
            "metadata_fields": {},
        }
        session = {
            "project_file": "Determinism.logicx",
            "logic_version": "11.1",
            "session_metadata": {
                "tempo_bpm": 90.0,
                "key_signature": "A major",
                "time_signature": "3/4",
                "sample_rate": 48000,
            },
            "track_summary": {
                "total_tracks": 5,
                "human_led_count": 3,
                "seed_count": 1,
                "programmed_count": 1,
            },
            "tracks": [],
        }
        results = [build_provenance(seed, session) for _ in range(10)]
        ids = {r["loopback_id"] for r in results}
        assert len(ids) == 1, "loopback_id must be identical across runs"

    def test_json_sort_order_is_stable(self) -> None:
        """Canonical JSON must have sorted keys."""
        from provenance.cli import _canonical_json

        obj = {"z": 1, "a": 2, "m": {"z": 3, "a": 4}}
        output = _canonical_json(obj)
        parsed = json.loads(output)
        assert list(parsed.keys()) == ["a", "m", "z"]
        assert list(parsed["m"].keys()) == ["a", "z"]


# ======================================================================
# Metadata stripping — no subjective data (AGENTS.md §1.2)
# ======================================================================


class TestMetadataStripping:
    """Verify that prohibited ID3/RIFF fields never appear in output."""

    def test_prohibited_id3_frames_stripped(self, tmp_dir: Path) -> None:
        """TIT2 (title), TPE1 (artist), TALB (album) must not leak."""
        from tests.conftest import _make_id3v2_tag, _text_frame
        from provenance.seed_extractor import extract_seed

        frames = {
            "TSSE": _text_frame("Suno/v3.5"),       # allowed
            "TIT2": _text_frame("My Secret Song"),   # prohibited
            "TPE1": _text_frame("Artist Name"),      # prohibited
            "TALB": _text_frame("Album Name"),       # prohibited
            "TDRC": _text_frame("2026"),             # allowed
        }
        tag = _make_id3v2_tag(frames)
        mpeg_frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
        mp3 = tmp_dir / "tagged.mp3"
        mp3.write_bytes(tag + mpeg_frame)

        result = extract_seed(mp3)
        assert "error" not in result
        meta = result["metadata_fields"]
        assert "TIT2" not in meta
        assert "TPE1" not in meta
        assert "TALB" not in meta
        assert "TSSE" in meta

    def test_prohibited_txxx_frames_stripped(self, tmp_dir: Path) -> None:
        """TXXX frames with non-allowed descriptions must be dropped."""
        from tests.conftest import _make_id3v2_tag
        from provenance.seed_extractor import extract_seed

        # TXXX frame: encoding(1) + description(null-terminated) + value
        def _txxx_payload(desc: str, value: str) -> bytes:
            return b"\x03" + desc.encode("utf-8") + b"\x00" + value.encode("utf-8")

        frames = {
            "TSSE": b"\x03Suno",
        }
        tag_data = _make_id3v2_tag(frames)

        # Manually inject TXXX frames (one allowed, one prohibited)
        import struct as s

        def _frame(fid: str, payload: bytes) -> bytes:
            return fid.encode("ascii") + s.pack(">I", len(payload)) + b"\x00\x00" + payload

        extra = _frame("TXXX", _txxx_payload("encoder", "suno-v3"))
        extra += _frame("TXXX", _txxx_payload("lyrics", "some secret lyrics"))

        # Rebuild: ID3 header + original frames + extra, recalculate size
        from tests.conftest import _synchsafe
        original_frames = tag_data[10:]  # skip 10-byte header
        all_frames = original_frames + extra
        header = b"ID3\x03\x00\x00" + _synchsafe(len(all_frames))
        mpeg_frame = b"\xff\xfb\x90\x00" + b"\x00" * 413

        mp3 = tmp_dir / "txxx.mp3"
        mp3.write_bytes(header + all_frames + mpeg_frame)

        result = extract_seed(mp3)
        assert "error" not in result
        meta = result["metadata_fields"]
        assert "TXXX:encoder" in meta
        # "lyrics" is not on the allowlist
        assert "TXXX:lyrics" not in meta

    def test_pre_register_also_strips_prohibited_fields(self, tmp_dir: Path) -> None:
        """pre_register uses the same allowlist as seed_extractor."""
        from tests.conftest import _make_id3v2_tag, _text_frame
        from provenance.pre_register import pre_register

        frames = {
            "TSSE": _text_frame("encoder-ok"),
            "TIT2": _text_frame("Prohibited Title"),
            "COMM": _text_frame("Some comment"),
        }
        tag = _make_id3v2_tag(frames)
        mpeg_frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
        mp3 = tmp_dir / "prereg_strip.mp3"
        mp3.write_bytes(tag + mpeg_frame)

        result = pre_register(mp3)
        assert "error" not in result
        assert "TIT2" not in result["metadata_fields"]
        assert "COMM" not in result["metadata_fields"]
        assert "TSSE" in result["metadata_fields"]


# ======================================================================
# Binary parsing edge cases (AGENTS.md §3)
# ======================================================================


class TestBinaryParsingEdgeCases:
    """ProjectData binary scanning must be resilient."""

    def _make_bundle(self, tmp_dir: Path, project_data: bytes, name: str = "Edge.logicx") -> Path:
        bundle = tmp_dir / name
        alt = bundle / "Alternatives" / "000"
        alt.mkdir(parents=True)
        plist = {"tempo": 100.0, "sampleRate": 48000, "applicationVersion": "11.0"}
        with open(alt / "MetaData.plist", "wb") as f:
            plistlib.dump(plist, f)
        (alt / "ProjectData").write_bytes(project_data)
        return bundle

    def test_empty_project_data(self, tmp_dir: Path) -> None:
        """Zero-length ProjectData should not crash (AGENTS.md §2.2)."""
        from provenance.daw_auditor import audit_session

        bundle = self._make_bundle(tmp_dir, b"", "Empty.logicx")
        result = audit_session(bundle)
        assert "error" not in result
        assert result["track_summary"]["total_tracks"] == 1  # fallback

    def test_truncated_markers(self, tmp_dir: Path) -> None:
        """Partial FourCC at end of file must not crash."""
        from provenance.daw_auditor import audit_session

        # 3 bytes of a marker at the end = incomplete, should be skipped
        data = b"karT" + b"\x00" * 32 + b"kar"
        bundle = self._make_bundle(tmp_dir, data, "Truncated.logicx")
        result = audit_session(bundle)
        assert "error" not in result
        assert result["track_summary"]["total_tracks"] == 1

    def test_markers_at_every_offset(self, tmp_dir: Path) -> None:
        """Markers embedded back-to-back should all be counted."""
        from provenance.daw_auditor import audit_session

        data = b"karT" * 10 + b"gRuA" * 5 + b"qeSM" * 3
        bundle = self._make_bundle(tmp_dir, data, "Dense.logicx")
        result = audit_session(bundle)
        assert "error" not in result
        assert result["track_summary"]["total_tracks"] == 10

    def test_no_markers_at_all(self, tmp_dir: Path) -> None:
        """Binary with no FourCC markers should yield a single fallback track."""
        from provenance.daw_auditor import audit_session

        data = b"\xDE\xAD\xBE\xEF" * 100
        bundle = self._make_bundle(tmp_dir, data, "NoMarkers.logicx")
        result = audit_session(bundle)
        assert "error" not in result
        # No markers → max(1, 0+0) = 1
        assert result["track_summary"]["total_tracks"] == 1

    def test_interleaved_markers(self, tmp_dir: Path) -> None:
        """Overlapping bytes that form partial markers must not double-count."""
        from provenance.daw_auditor import audit_session

        # "karTkarT" contains 2 Track markers at offsets 0 and 4
        data = b"karTkarT" + b"gRuA" + b"\x00" * 16
        bundle = self._make_bundle(tmp_dir, data, "Interleaved.logicx")
        result = audit_session(bundle)
        assert result["track_summary"]["total_tracks"] == 2
        assert result["track_summary"]["human_led_count"] == 1  # 1 audio region, no seed hash


# ======================================================================
# C2PA signer — input validation (no real certs needed)
# ======================================================================


class TestC2PASignerValidation:
    """Test c2pa_signer error handling without requiring real certificates."""

    def test_missing_master_file(self, tmp_dir: Path) -> None:
        from provenance.c2pa_signer import sign_master

        result = sign_master(
            master_path=tmp_dir / "missing.wav",
            seed_audio_path=tmp_dir / "also_missing.mp3",
            provenance={"loopback_id": "x", "seed": {}, "session": {},
                        "provenance_timestamp": ""},
            cert_path=tmp_dir / "c.pem",
            key_path=tmp_dir / "k.pem",
            output_path=tmp_dir / "out.wav",
        )
        assert "error" in result
        assert result["module"] == "c2pa_signer"
        assert "master not found" in result["error"]

    def test_missing_cert_file(self, synthetic_wav: Path, synthetic_mp3: Path, tmp_dir: Path) -> None:
        from provenance.c2pa_signer import sign_master

        result = sign_master(
            master_path=synthetic_wav,
            seed_audio_path=synthetic_mp3,
            provenance={"loopback_id": "x", "seed": {}, "session": {},
                        "provenance_timestamp": ""},
            cert_path=tmp_dir / "nonexistent.pem",
            key_path=tmp_dir / "nonexistent.key",
            output_path=tmp_dir / "out.wav",
        )
        assert "error" in result
        assert "cert not found" in result["error"]

    def test_missing_seed_audio(self, synthetic_wav: Path, tmp_dir: Path) -> None:
        from provenance.c2pa_signer import sign_master

        result = sign_master(
            master_path=synthetic_wav,
            seed_audio_path=tmp_dir / "ghost.mp3",
            provenance={"loopback_id": "x", "seed": {}, "session": {},
                        "provenance_timestamp": ""},
            cert_path=tmp_dir / "c.pem",
            key_path=tmp_dir / "k.pem",
            output_path=tmp_dir / "out.wav",
        )
        assert "error" in result
        assert "seed_audio not found" in result["error"]


# ======================================================================
# CLI subprocess tests
# ======================================================================


class TestCLISubprocess:
    """Drive the CLI as a subprocess to test real arg parsing + JSON output."""

    def test_pre_register_cli(self, synthetic_mp3: Path) -> None:
        proc = _run_cli("pre-register", str(synthetic_mp3))
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert len(data["pre_reg_id"]) == 16
        assert data["original_format"] == "mp3"

    def test_seed_extract_cli(self, synthetic_mp3: Path) -> None:
        proc = _run_cli("seed-extract", str(synthetic_mp3))
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert data["source_format"] == "mp3"

    def test_daw_audit_cli(self, synthetic_logicx: Path) -> None:
        proc = _run_cli("daw-audit", str(synthetic_logicx))
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert data["project_file"] == "TestProject.logicx"

    def test_loopback_cli_with_pre_reg(
        self, synthetic_mp3: Path, synthetic_logicx: Path, seed_file_hash: str, tmp_dir: Path
    ) -> None:
        """Full step-by-step CLI: pre-register → seed-extract → daw-audit → loopback."""
        # pre-register
        p1 = _run_cli("pre-register", str(synthetic_mp3))
        assert p1.returncode == 0, p1.stderr
        pre_reg_path = tmp_dir / "pre_reg.json"
        pre_reg_path.write_text(p1.stdout)

        # seed-extract
        p2 = _run_cli("seed-extract", str(synthetic_mp3))
        assert p2.returncode == 0, p2.stderr
        seed_path = tmp_dir / "seed.json"
        seed_path.write_text(p2.stdout)

        # daw-audit with seed hash
        p3 = _run_cli("daw-audit", str(synthetic_logicx), "--seed-hash", seed_file_hash)
        assert p3.returncode == 0, p3.stderr
        session_path = tmp_dir / "session.json"
        session_path.write_text(p3.stdout)

        # loopback with pre-reg
        p4 = _run_cli(
            "loopback",
            "--seed", str(seed_path),
            "--session", str(session_path),
            "--pre-reg", str(pre_reg_path),
        )
        assert p4.returncode == 0, p4.stderr
        provenance = json.loads(p4.stdout)
        assert "loopback_id" in provenance
        assert "pre_registration" in provenance
        assert provenance["session"]["seed_count"] == 1

    def test_cli_error_exits_nonzero(self, tmp_dir: Path) -> None:
        proc = _run_cli("seed-extract", str(tmp_dir / "nonexistent.mp3"))
        assert proc.returncode != 0
        err = json.loads(proc.stderr)
        assert "error" in err

    def test_cli_output_is_valid_json(self, synthetic_mp3: Path) -> None:
        proc = _run_cli("pre-register", str(synthetic_mp3))
        assert proc.returncode == 0
        # Must be parseable JSON
        data = json.loads(proc.stdout)
        assert isinstance(data, dict)

    def test_cli_help_shows_all_subcommands(self) -> None:
        proc = _run_cli("--help")
        assert proc.returncode == 0
        for cmd in ("pre-register", "seed-extract", "daw-audit", "loopback", "sign", "run"):
            assert cmd in proc.stdout


# ======================================================================
# Provenance record schema completeness
# ======================================================================


class TestProvenanceRecordSchema:
    """Verify all required fields are present and correctly typed."""

    def _build_record(self, with_pre_reg: bool = False) -> dict:
        from provenance.loopback_engine import build_provenance

        seed = {
            "seed_id": "abcdef1234567890",
            "origin_timestamp": "2026-04-15T00:00:00+00:00",
            "source_format": "mp3",
            "source_file_hash": "a" * 64,
            "metadata_fields": {"TSSE": "Suno/v3.5"},
        }
        session = {
            "project_file": "Schema.logicx",
            "logic_version": "11.1",
            "session_metadata": {
                "tempo_bpm": 120.0,
                "key_signature": "C minor",
                "time_signature": "4/4",
                "sample_rate": 44100,
            },
            "track_summary": {
                "total_tracks": 4,
                "human_led_count": 2,
                "seed_count": 1,
                "programmed_count": 1,
            },
            "tracks": [],
        }
        pre_reg = {
            "pre_reg_id": "1111222233334444",
            "original_file_hash": "b" * 64,
            "original_format": "wav",
            "registered_at": "2026-04-14T12:00:00+00:00",
            "metadata_fields": {},
        } if with_pre_reg else None
        return build_provenance(seed, session, pre_registration=pre_reg)

    def test_required_fields_present(self) -> None:
        record = self._build_record()
        for key in ("loopback_id", "seed", "session", "provenance_timestamp"):
            assert key in record, f"Missing required field: {key}"

    def test_seed_section_fields(self) -> None:
        record = self._build_record()
        for key in ("seed_id", "origin_timestamp", "source_file_hash"):
            assert key in record["seed"], f"Missing seed field: {key}"

    def test_session_section_fields(self) -> None:
        record = self._build_record()
        for key in ("project_file", "tempo_bpm", "key_signature", "time_signature",
                     "sample_rate", "total_tracks", "human_led_count",
                     "seed_count", "programmed_count"):
            assert key in record["session"], f"Missing session field: {key}"

    def test_pre_registration_fields_when_present(self) -> None:
        record = self._build_record(with_pre_reg=True)
        pre = record["pre_registration"]
        for key in ("pre_reg_id", "original_file_hash", "original_format",
                     "registered_at", "metadata_fields"):
            assert key in pre, f"Missing pre_registration field: {key}"

    def test_loopback_id_is_hex_16(self) -> None:
        record = self._build_record()
        lid = record["loopback_id"]
        assert len(lid) == 16
        int(lid, 16)  # must be valid hex

    def test_provenance_timestamp_is_iso8601(self) -> None:
        from datetime import datetime

        record = self._build_record()
        ts = record["provenance_timestamp"]
        # Must parse without error
        datetime.fromisoformat(ts)

    def test_numeric_fields_are_correct_types(self) -> None:
        record = self._build_record()
        s = record["session"]
        assert isinstance(s["tempo_bpm"], float)
        assert isinstance(s["sample_rate"], int)
        assert isinstance(s["total_tracks"], int)
        assert isinstance(s["human_led_count"], int)

    def test_full_record_roundtrips_through_json(self) -> None:
        """The full record must survive JSON serialization and deserialization."""
        record = self._build_record(with_pre_reg=True)
        serialized = json.dumps(record, sort_keys=True, separators=(",", ":"))
        deserialized = json.loads(serialized)
        assert deserialized["loopback_id"] == record["loopback_id"]
        assert deserialized["pre_registration"]["pre_reg_id"] == record["pre_registration"]["pre_reg_id"]
