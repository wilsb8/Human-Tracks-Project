# Human-Tracks-Project: Digital Provenance & Metadata Loopback

The Mission

To provide an ironclad, mechanical "Proof of Work" for professional musicians working with AI-generated audio seeds. This project delineates years of human musicianship from low-effort AI "slop" by establishing a cryptographically signed chain of custody from the initial audio seed to the final master export.

# Digital Provenance & Metadata Loopback Tool

A Python CLI that produces a verifiable Proof-of-Work manifest linking an AI-generated audio seed (Suno) to a DAW session audit (Logic Pro), signed with a [C2PA](https://c2pa.org/) content credential.

## Prerequisites

- Python 3.10+
- macOS (required for `.logicx` bundle access)
- [c2patool](https://github.com/contentauth/c2pa-rs) (for verification only)

## Installation

```bash
# Clone and install
git clone <repo-url> && cd project-suno
pip3 install -e .
```

This installs the `provenance-tool` CLI and its two dependencies (`mutagen`, `c2pa-python`).

## Quick Start

### Full Pipeline (single command)

```bash
provenance-tool run \
  --seed-audio  /path/to/suno_export.mp3 \
  --logicx      /path/to/Session.logicx \
  --master      /path/to/final_master.wav \
  --cert        certs/es256_certs.pem \
  --key         certs/es256_private.key \
  --output      signed_master.wav
```

### Step-by-Step

```bash
# 1. Extract seed metadata from the Suno file
provenance-tool seed-extract suno_export.mp3 > seed.json

# 2. Audit the Logic Pro session (pass --seed-hash for track classification)
HASH=$(python3 -c "import hashlib,sys; h=hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest(); print(h)" suno_export.mp3)
provenance-tool daw-audit Session.logicx --seed-hash "$HASH" > session.json

# 3. Build the provenance record
provenance-tool loopback --seed seed.json --session session.json > provenance.json

# 4. Sign the master
provenance-tool sign \
  --master      final_master.wav \
  --seed-audio  suno_export.mp3 \
  --provenance  provenance.json \
  --cert        certs/es256_certs.pem \
  --key         certs/es256_private.key \
  --output      signed_master.wav
```

### Verify a Signed Master

```bash
c2patool signed_master.wav
```

The output includes the `com.provenance.music.loopback` assertion with the full provenance record (seed ID, track counts, session metadata).

## C2PA Environment Setup

The signing step requires an X.509 certificate and private key. Below are instructions for generating a **development** keypair and for obtaining a **production** certificate.

### Development (self-signed, testing only)

```bash
mkdir -p certs && cd certs

# Generate an ES256 private key
openssl ecparam -name prime256v1 -genkey -noout -out es256_private.key

# Generate a self-signed certificate (valid 365 days)
openssl req -new -x509 -key es256_private.key \
  -out es256_certs.pem -days 365 \
  -subj "/CN=Provenance Tool Dev/O=Dev"

cd ..
```

> **Note:** Self-signed certificates will produce manifests that validate structurally but show as "untrusted" in C2PA verifiers like [Content Credentials Verify](https://contentcredentials.org/verify). This is expected for development.

### Production

For manifests that validate on the [C2PA Trust List](https://opensource.contentauthenticity.org/docs/conformance/trust-lists):

1. **Obtain a certificate** from a C2PA-recognized Certificate Authority. Options include:
   - [GlobalSign](https://www.globalsign.com/) — issues Content Credentials signing certificates
   - [DigiCert](https://www.digicert.com/) — provides timestamping and signing services
   - Any CA whose root is on the C2PA Trust List

2. **Place files** in your project:
   ```
   certs/
   ├── es256_certs.pem      # Full certificate chain (leaf + intermediates)
   └── es256_private.key    # Corresponding private key
   ```

3. **Add a timestamp authority** for long-term validity:
   ```bash
   provenance-tool run \
     --seed-audio suno_export.mp3 \
     --logicx     Session.logicx \
     --master     final_master.wav \
     --cert       certs/es256_certs.pem \
     --key        certs/es256_private.key \
     --output     signed_master.wav \
     --ta-url     http://timestamp.digicert.com
   ```

### Installing c2patool (for verification)

```bash
# macOS via Homebrew
brew install c2patool

# Or download a prebuilt binary from:
# https://github.com/contentauth/c2pa-rs/releases
```

## What Gets Embedded

The signed master contains a C2PA manifest with two assertions:

**`c2pa.actions.v2`** — declares the asset as a composite containing AI-generated material:
```json
{
  "actions": [{
    "action": "c2pa.created",
    "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
  }]
}
```

**`com.provenance.music.loopback`** — the provenance record:
```json
{
  "loopback_id": "a1b2c3d4e5f67890",
  "seed": {
    "seed_id": "f0e1d2c3b4a59687",
    "origin_timestamp": "2026-04-15T00:00:00+00:00",
    "source_file_hash": "sha256..."
  },
  "session": {
    "project_file": "MySession.logicx",
    "tempo_bpm": 120.0,
    "key_signature": "C minor",
    "time_signature": "4/4",
    "sample_rate": 44100,
    "total_tracks": 12,
    "human_led_count": 8,
    "seed_count": 1,
    "programmed_count": 3
  },
  "provenance_timestamp": "2026-05-04T20:00:00+00:00"
}
```

No subjective data (track names, lyrics, plugin names, artist info) is included — only mechanical provenance.

## Project Structure

```
src/provenance/
├── schemas.py           # TypedDict contracts for all data flowing between modules
├── seed_extractor.py    # Parses Suno MP3/WAV metadata (ID3 + RIFF), computes seed ID
├── daw_auditor.py       # Parses .logicx bundles (plist + binary FourCC scanning)
├── loopback_engine.py   # Marries seed ↔ session, computes deterministic loopback ID
├── c2pa_signer.py       # Builds and signs C2PA manifest via c2pa-python
└── cli.py               # CLI entry point with subcommands
```

## Running Tests

```bash
pip3 install pytest
PYTHONPATH=src python3 -m pytest tests/ -v
```

## Rules

See [PRODUCT.md](PRODUCT.md) for the full product specification and [AGENTS.md](AGENTS.md) for development constraints and data-handling rules.
