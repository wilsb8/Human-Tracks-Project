"""Loopback Engine — marry the Seed ID with the Logic session audit."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from provenance.schemas import (
    ErrorResult,
    ProvenanceRecord,
    SeedResult,
    SeedSection,
    SessionResult,
    SessionSection,
)

logger = logging.getLogger(__name__)


def build_provenance(
    seed: SeedResult,
    session: SessionResult,
) -> ProvenanceRecord | ErrorResult:
    """Combine seed extraction and session audit into a single provenance record.

    Parameters
    ----------
    seed:
        Output of ``seed_extractor.extract_seed``.
    session:
        Output of ``daw_auditor.audit_session``.

    Returns
    -------
    ProvenanceRecord on success, ErrorResult on failure.
    """
    try:
        summary = session["track_summary"]

        # Validate: at least one seed track must exist
        if summary["seed_count"] == 0:
            return ErrorResult(
                error=(
                    "No seed track found in the session. "
                    "Cannot establish provenance chain — the seed audio "
                    "was not detected in the Logic project's Media folder."
                ),
                module="loopback_engine",
            )

        # Warning (non-fatal): no human-led tracks
        if summary["human_led_count"] == 0:
            logger.warning(
                "Session contains zero human-led tracks. "
                "The provenance record will reflect no evidence of "
                "human recording activity."
            )

        # Compute deterministic loopback ID
        raw = (
            seed["seed_id"]
            + session["project_file"]
            + str(summary["total_tracks"])
            + str(summary["human_led_count"])
        )
        loopback_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

        meta = session["session_metadata"]

        return ProvenanceRecord(
            loopback_id=loopback_id,
            seed=SeedSection(
                seed_id=seed["seed_id"],
                origin_timestamp=seed["origin_timestamp"],
                source_file_hash=seed["source_file_hash"],
            ),
            session=SessionSection(
                project_file=session["project_file"],
                tempo_bpm=meta["tempo_bpm"],
                key_signature=meta["key_signature"],
                time_signature=meta["time_signature"],
                sample_rate=meta["sample_rate"],
                total_tracks=summary["total_tracks"],
                human_led_count=summary["human_led_count"],
                seed_count=summary["seed_count"],
                programmed_count=summary["programmed_count"],
            ),
            provenance_timestamp=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as exc:
        logger.exception("loopback_engine failed")
        return ErrorResult(error=str(exc), module="loopback_engine")
