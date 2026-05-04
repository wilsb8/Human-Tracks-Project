#!/usr/bin/env python3
"""Digital Provenance & Metadata Loopback Tool — standalone entry point.

Run directly without installing the package:

    python3 provenance-tool.py seed-extract suno_output.mp3
    python3 provenance-tool.py daw-audit Session.logicx --seed-hash <hash>
    python3 provenance-tool.py loopback --seed seed.json --session session.json
    python3 provenance-tool.py sign --master master.wav --seed-audio suno.mp3 \\
        --provenance provenance.json --cert certs/es256_certs.pem \\
        --key certs/es256_private.key --output signed_master.wav
    python3 provenance-tool.py run --seed-audio suno.mp3 --logicx Session.logicx \\
        --master master.wav --cert certs/es256_certs.pem \\
        --key certs/es256_private.key --output signed_master.wav
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the src/ directory is on the import path so the provenance
# package can be found even when the tool is not pip-installed.
_SRC_DIR = str(Path(__file__).resolve().parent / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from provenance.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
