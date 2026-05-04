"""Tests for the first three pipeline stages."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


# ======================================================================
# Seed Extractor
# ======================================================================


class TestSeedExtractor:
    def test_extract_mp3_happy_path(self, synthetic_mp3: Path) -> None:
        from provenance.seed_extractor import extract_seed

        result = extract_seed(synthetic_mp3)
        assert "error" not in result
        assert len(result["seed_id"]) == 16
        assert result["source_format"] == "mp3"
        assert len(result["source_file_hash"]) == 64  # SHA-256 hex

    def test_extract_wav_happy_path(self, synthetic_wav: Path) -> None:
        from provenance.seed_extractor import extract_seed

        result = extract_seed(synthetic_wav)
        assert "error" not in result
        assert result["source_format"] == "wav"
        assert result["origin_timestamp"]  # should at least have filesystem fallback

    def test_extract_missing_file(self, tmp_dir: Path) -> None:
        from provenance.seed_extractor import extract_seed

        result = extract_seed(tmp_dir / "nonexistent.mp3")
        assert result["error"].startswith("File not found")
        assert result["module"] == "seed_extractor"

    def test_extract_unsupported_format(self, tmp_dir: Path) -> None:
        from provenance.seed_extractor import extract_seed

        bad = tmp_dir / "song.ogg"
        bad.write_bytes(b"\x00")
        result = extract_seed(bad)
        assert "Unsupported format" in result["error"]

    def test_seed_id_is_deterministic(self, synthetic_mp3: Path) -> None:
        from provenance.seed_extractor import extract_seed

        r1 = extract_seed(synthetic_mp3)
        r2 = extract_seed(synthetic_mp3)
        assert r1["seed_id"] == r2["seed_id"]
        assert r1["source_file_hash"] == r2["source_file_hash"]

    def test_metadata_allowlist(self, synthetic_mp3: Path) -> None:
        """Only allowed ID3 frames should appear in metadata_fields."""
        from provenance.seed_extractor import extract_seed

        result = extract_seed(synthetic_mp3)
        assert "error" not in result
        for key in result["metadata_fields"]:
            # Must be one of the allowed frames or a TXXX with allowed desc
            assert key in ("TSSE", "TENC", "TDRC", "TYER", "TDAT", "TOFN") or key.startswith("TXXX:")


# ======================================================================
# DAW Auditor
# ======================================================================


class TestDAWAuditor:
    def test_audit_happy_path(self, synthetic_logicx: Path, seed_file_hash: str) -> None:
        from provenance.daw_auditor import audit_session

        result = audit_session(synthetic_logicx, seed_file_hash=seed_file_hash)
        assert "error" not in result
        assert result["project_file"] == "TestProject.logicx"
        assert result["logic_version"] == "11.1"
        assert result["session_metadata"]["tempo_bpm"] == 120.0
        assert result["session_metadata"]["key_signature"] == "C minor"
        assert result["session_metadata"]["sample_rate"] == 44100

    def test_track_counts(self, synthetic_logicx: Path, seed_file_hash: str) -> None:
        from provenance.daw_auditor import audit_session

        result = audit_session(synthetic_logicx, seed_file_hash=seed_file_hash)
        summary = result["track_summary"]
        assert summary["total_tracks"] == 3
        assert summary["seed_count"] == 1
        assert summary["human_led_count"] == 1
        assert summary["programmed_count"] == 1

    def test_audit_missing_bundle(self, tmp_dir: Path) -> None:
        from provenance.daw_auditor import audit_session

        result = audit_session(tmp_dir / "nope.logicx")
        assert "error" in result
        assert result["module"] == "daw_auditor"

    def test_audit_missing_plist(self, tmp_dir: Path) -> None:
        from provenance.daw_auditor import audit_session

        # Bundle exists but no plist
        bundle = tmp_dir / "Empty.logicx"
        bundle.mkdir()
        result = audit_session(bundle)
        assert "MetaData.plist not found" in result["error"]

    def test_no_seed_hash_classifies_all_as_human(self, synthetic_logicx: Path) -> None:
        from provenance.daw_auditor import audit_session

        result = audit_session(synthetic_logicx, seed_file_hash="")
        summary = result["track_summary"]
        # Without seed hash, all audio tracks should be human_led
        assert summary["seed_count"] == 0
        assert summary["human_led_count"] == 2


# ======================================================================
# Pre-Register
# ======================================================================


class TestPreRegister:
    def test_pre_register_mp3(self, synthetic_mp3: Path) -> None:
        from provenance.pre_register import pre_register

        result = pre_register(synthetic_mp3)
        assert "error" not in result
        assert len(result["pre_reg_id"]) == 16
        assert len(result["original_file_hash"]) == 64
        assert result["original_format"] == "mp3"
        assert result["registered_at"]  # non-empty ISO timestamp

    def test_pre_register_wav(self, synthetic_wav: Path) -> None:
        from provenance.pre_register import pre_register

        result = pre_register(synthetic_wav)
        assert "error" not in result
        assert result["original_format"] == "wav"

    def test_pre_register_missing_file(self, tmp_dir: Path) -> None:
        from provenance.pre_register import pre_register

        result = pre_register(tmp_dir / "ghost.wav")
        assert result["error"].startswith("File not found")
        assert result["module"] == "pre_register"

    def test_pre_register_unsupported(self, tmp_dir: Path) -> None:
        from provenance.pre_register import pre_register

        bad = tmp_dir / "song.ogg"
        bad.write_bytes(b"\x00")
        result = pre_register(bad)
        assert "Unsupported format" in result["error"]

    def test_deterministic_hash(self, synthetic_mp3: Path) -> None:
        from provenance.pre_register import pre_register

        r1 = pre_register(synthetic_mp3)
        r2 = pre_register(synthetic_mp3)
        assert r1["pre_reg_id"] == r2["pre_reg_id"]
        assert r1["original_file_hash"] == r2["original_file_hash"]


# ======================================================================
# Loopback Engine
# ======================================================================


class TestLoopbackEngine:
    def _make_seed_result(self) -> dict:
        return {
            "seed_id": "abcdef1234567890",
            "origin_timestamp": "2026-04-15T00:00:00+00:00",
            "source_format": "mp3",
            "source_file_hash": "a" * 64,
            "metadata_fields": {"TSSE": "Suno/v3.5"},
        }

    def _make_session_result(self, seed_count: int = 1, human_led: int = 2) -> dict:
        return {
            "project_file": "Test.logicx",
            "logic_version": "11.1",
            "session_metadata": {
                "tempo_bpm": 120.0,
                "key_signature": "C minor",
                "time_signature": "4/4",
                "sample_rate": 44100,
            },
            "track_summary": {
                "total_tracks": seed_count + human_led + 1,
                "human_led_count": human_led,
                "seed_count": seed_count,
                "programmed_count": 1,
            },
            "tracks": [],
        }

    def test_happy_path(self) -> None:
        from provenance.loopback_engine import build_provenance

        result = build_provenance(self._make_seed_result(), self._make_session_result())
        assert "error" not in result
        assert len(result["loopback_id"]) == 16
        assert result["seed"]["seed_id"] == "abcdef1234567890"
        assert result["session"]["human_led_count"] == 2

    def test_no_seed_track_errors(self) -> None:
        from provenance.loopback_engine import build_provenance

        result = build_provenance(
            self._make_seed_result(),
            self._make_session_result(seed_count=0),
        )
        assert "error" in result
        assert "No seed track" in result["error"]

    def test_deterministic_loopback_id(self) -> None:
        from provenance.loopback_engine import build_provenance

        seed = self._make_seed_result()
        session = self._make_session_result()
        r1 = build_provenance(seed, session)
        r2 = build_provenance(seed, session)
        assert r1["loopback_id"] == r2["loopback_id"]

    def test_zero_human_led_still_succeeds(self) -> None:
        from provenance.loopback_engine import build_provenance

        result = build_provenance(
            self._make_seed_result(),
            self._make_session_result(human_led=0),
        )
        # Should succeed with a warning (non-fatal)
        assert "error" not in result
        assert result["session"]["human_led_count"] == 0

    def test_with_pre_registration(self) -> None:
        from provenance.loopback_engine import build_provenance

        pre_reg = {
            "pre_reg_id": "1234567890abcdef",
            "original_file_hash": "b" * 64,
            "original_format": "wav",
            "registered_at": "2026-04-14T12:00:00+00:00",
            "metadata_fields": {},
        }
        result = build_provenance(
            self._make_seed_result(),
            self._make_session_result(),
            pre_registration=pre_reg,
        )
        assert "error" not in result
        assert "pre_registration" in result
        assert result["pre_registration"]["pre_reg_id"] == "1234567890abcdef"

    def test_without_pre_registration_omits_field(self) -> None:
        from provenance.loopback_engine import build_provenance

        result = build_provenance(
            self._make_seed_result(),
            self._make_session_result(),
        )
        assert "error" not in result
        assert "pre_registration" not in result
