"""C2PA Signer — sign the final master with an embedded provenance manifest."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Union

import c2pa

from provenance.schemas import ErrorResult, ProvenanceRecord

logger = logging.getLogger(__name__)

# IPTC digital source type for composite content containing AI material
_DIGITAL_SOURCE_TYPE = (
    "http://cv.iptc.org/newscodes/digitalsourcetype/"
    "compositeWithTrainedAlgorithmicMedia"
)


def sign_master(
    master_path: Union[str, Path],
    seed_audio_path: Union[str, Path],
    provenance: ProvenanceRecord,
    cert_path: Union[str, Path],
    key_path: Union[str, Path],
    output_path: Union[str, Path],
    ta_url: str = "",
) -> dict | ErrorResult:
    """Sign a master audio file with a C2PA manifest containing the provenance record.

    Parameters
    ----------
    master_path:
        Path to the final master audio file (WAV or MP3).
    seed_audio_path:
        Path to the original Suno seed file (added as ingredient).
    provenance:
        The assembled ProvenanceRecord from the loopback engine.
    cert_path:
        Path to the PEM-encoded signing certificate.
    key_path:
        Path to the PEM-encoded private key.
    output_path:
        Where to write the signed master.
    ta_url:
        Optional Time Stamp Authority URL.

    Returns
    -------
    Dict with ``{"signed_file": str, "manifest_summary": dict}`` on success,
    ErrorResult on failure.
    """
    master = Path(master_path)
    seed_audio = Path(seed_audio_path)
    cert = Path(cert_path)
    key = Path(key_path)
    output = Path(output_path)

    for label, p in [("master", master), ("seed_audio", seed_audio),
                     ("cert", cert), ("key", key)]:
        if not p.is_file():
            return ErrorResult(error=f"{label} not found: {p}", module="c2pa_signer")

    try:
        mime = _mime_for(master)
        seed_mime = _mime_for(seed_audio)

        cert_bytes = cert.read_text(encoding="utf-8")
        key_bytes = key.read_bytes()

        # --- Build manifest definition (AGENTS.md §4.1) ---
        manifest_def = {
            "claim_generator_info": [
                {
                    "name": "provenance-tool",
                    "version": "0.1.0",
                }
            ],
            "format": mime,
            "assertions": [
                {
                    "label": "c2pa.actions.v2",
                    "data": {
                        "actions": [
                            {
                                "action": "c2pa.created",
                                "digitalSourceType": _DIGITAL_SOURCE_TYPE,
                            }
                        ],
                    },
                },
                {
                    "label": "com.provenance.music.loopback",
                    "data": dict(provenance),
                },
            ],
        }

        # Ingredient definition for the seed file (AGENTS.md §4.2)
        ingredient_def = {
            "title": "seed_audio",
            "format": seed_mime,
            "relationship": "parentOf",
        }

        # --- Sign via c2pa-python ---
        signer_info = c2pa.C2paSignerInfo(
            alg=c2pa.C2paSigningAlg.ES256,
            certs=cert_bytes,
            private_key=key_bytes.decode("utf-8"),
            ta_url=ta_url if ta_url else None,
        )

        with c2pa.Context() as ctx:
            with c2pa.Signer(signer_info) as signer:
                with c2pa.Builder(manifest_def, ctx) as builder:
                    # Add seed as ingredient
                    with open(seed_audio, "rb") as seed_f:
                        builder.add_ingredient(ingredient_def, seed_mime, seed_f)

                    # Sign master → output
                    builder.sign_file(str(master), str(output), signer)

        logger.info("Signed master written to %s", output)

        return {
            "signed_file": str(output),
            "manifest_summary": {
                "loopback_id": provenance["loopback_id"],
                "seed_id": provenance["seed"]["seed_id"],
                "human_led_count": provenance["session"]["human_led_count"],
                "total_tracks": provenance["session"]["total_tracks"],
            },
        }

    except Exception as exc:
        logger.exception("c2pa_signer failed")
        return ErrorResult(error=str(exc), module="c2pa_signer")


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".aif": "audio/aiff",
        ".aiff": "audio/aiff",
        ".flac": "audio/flac",
    }.get(ext, "application/octet-stream")
