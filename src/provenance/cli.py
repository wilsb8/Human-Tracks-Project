"""CLI entry point for the Digital Provenance & Metadata Loopback Tool."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from provenance.schemas import ErrorResult


def _canonical_json(obj: dict) -> str:
    """Deterministic JSON output (AGENTS.md §2.4)."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)


def _fail(result: ErrorResult) -> None:
    sys.stderr.write(json.dumps(result, indent=2) + "\n")
    sys.exit(1)


def _is_error(result: dict) -> bool:
    return "error" in result


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_seed_extract(args: argparse.Namespace) -> None:
    from provenance.seed_extractor import extract_seed

    result = extract_seed(args.audio_file)
    if _is_error(result):
        _fail(result)
    print(_canonical_json(result))


def cmd_daw_audit(args: argparse.Namespace) -> None:
    from provenance.daw_auditor import audit_session

    seed_hash = getattr(args, "seed_hash", "") or ""
    result = audit_session(args.logicx_bundle, seed_file_hash=seed_hash)
    if _is_error(result):
        _fail(result)
    print(_canonical_json(result))


def cmd_loopback(args: argparse.Namespace) -> None:
    from provenance.loopback_engine import build_provenance

    seed = json.loads(Path(args.seed).read_text())
    session = json.loads(Path(args.session).read_text())
    result = build_provenance(seed, session)
    if _is_error(result):
        _fail(result)
    print(_canonical_json(result))


def cmd_sign(args: argparse.Namespace) -> None:
    from provenance.c2pa_signer import sign_master

    provenance = json.loads(Path(args.provenance).read_text())
    result = sign_master(
        master_path=args.master,
        seed_audio_path=args.seed_audio,
        provenance=provenance,
        cert_path=args.cert,
        key_path=args.key,
        output_path=args.output,
        ta_url=getattr(args, "ta_url", "") or "",
    )
    if _is_error(result):
        _fail(result)
    print(_canonical_json(result))


def cmd_run(args: argparse.Namespace) -> None:
    """Full pipeline: seed-extract → daw-audit → loopback → sign."""
    from provenance.c2pa_signer import sign_master
    from provenance.daw_auditor import audit_session
    from provenance.loopback_engine import build_provenance
    from provenance.seed_extractor import extract_seed

    # 1. Seed extraction
    seed = extract_seed(args.seed_audio)
    if _is_error(seed):
        _fail(seed)

    # 2. DAW audit (pass seed hash for track classification)
    session = audit_session(args.logicx, seed_file_hash=seed["source_file_hash"])
    if _is_error(session):
        _fail(session)

    # 3. Loopback
    provenance = build_provenance(seed, session)
    if _is_error(provenance):
        _fail(provenance)

    # 4. Sign
    result = sign_master(
        master_path=args.master,
        seed_audio_path=args.seed_audio,
        provenance=provenance,
        cert_path=args.cert,
        key_path=args.key,
        output_path=args.output,
        ta_url=getattr(args, "ta_url", "") or "",
    )
    if _is_error(result):
        _fail(result)

    print(_canonical_json(result))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="provenance-tool",
        description="Digital Provenance & Metadata Loopback Tool",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- seed-extract --
    p_seed = sub.add_parser("seed-extract", help="Extract seed metadata from a Suno audio file")
    p_seed.add_argument("audio_file", help="Path to Suno MP3 or WAV file")
    p_seed.set_defaults(func=cmd_seed_extract)

    # -- daw-audit --
    p_daw = sub.add_parser("daw-audit", help="Audit a Logic Pro .logicx session")
    p_daw.add_argument("logicx_bundle", help="Path to .logicx bundle")
    p_daw.add_argument("--seed-hash", dest="seed_hash", default="",
                       help="SHA-256 hash of seed file for track classification")
    p_daw.set_defaults(func=cmd_daw_audit)

    # -- loopback --
    p_loop = sub.add_parser("loopback", help="Combine seed and session into provenance record")
    p_loop.add_argument("--seed", required=True, help="Path to seed JSON")
    p_loop.add_argument("--session", required=True, help="Path to session JSON")
    p_loop.set_defaults(func=cmd_loopback)

    # -- sign --
    p_sign = sub.add_parser("sign", help="Sign a master audio file with C2PA manifest")
    p_sign.add_argument("--master", required=True, help="Path to master audio file")
    p_sign.add_argument("--seed-audio", required=True, help="Path to seed audio file")
    p_sign.add_argument("--provenance", required=True, help="Path to provenance JSON")
    p_sign.add_argument("--cert", required=True, help="Path to signing certificate (PEM)")
    p_sign.add_argument("--key", required=True, help="Path to private key (PEM)")
    p_sign.add_argument("--output", required=True, help="Output path for signed file")
    p_sign.add_argument("--ta-url", default="", help="Time Stamp Authority URL")
    p_sign.set_defaults(func=cmd_sign)

    # -- run (full pipeline) --
    p_run = sub.add_parser("run", help="Execute the full provenance pipeline")
    p_run.add_argument("--seed-audio", required=True, help="Path to Suno audio file")
    p_run.add_argument("--logicx", required=True, help="Path to .logicx bundle")
    p_run.add_argument("--master", required=True, help="Path to master audio file")
    p_run.add_argument("--cert", required=True, help="Path to signing certificate (PEM)")
    p_run.add_argument("--key", required=True, help="Path to private key (PEM)")
    p_run.add_argument("--output", required=True, help="Output path for signed file")
    p_run.add_argument("--ta-url", default="", help="Time Stamp Authority URL")
    p_run.set_defaults(func=cmd_run)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(name)s %(levelname)s: %(message)s")

    args.func(args)


if __name__ == "__main__":
    main()
