# Human-Tracks-Project: Digital Provenance & Metadata Loopback

## The Mission

An ironclad, mechanical Proof of Work for professional musicians working with AI-generated audio seeds. This project delineates 42 years of human musicianship from low-effort AI "slop" by establishing a cryptographically signed chain of custody from the initial audio seed to the final master export.

For professionals facing label/distributor scrutiny, this provides:

- **Legal protection** — verifiable proof of hybrid authorship for copyright and contract compliance
- **Technical integrity** — no degradation of audio quality; only file metadata headers are touched
- **Forensic evidence** — a signed manifest that objectively proves the hours of human labor recorded in the DAW

## Prerequisites

- Python 3.10+
- macOS (required for `.logicx` bundle access)
- A signing certificate and private key (ES256) — see [Certificate Setup](#certificate-setup) below
- [c2patool](https://github.com/contentauth/c2pa-rs) (for verification only)

## Installation

```bash
git clone <repo-url> && cd project-suno
pip3 install -e .
```

---

## Where Are You in the Process?

### I haven't uploaded to Suno yet — I have my own audio I want to protect

Run this **before** uploading your file to Suno. It fingerprints your audio and creates a timestamped receipt proving the file existed before Suno touched it.

**Step 1 — Fingerprint your original audio:**
```bash
provenance-tool pre-register my_recording.wav > pre_reg.json
```

Save `pre_reg.json`. Then upload `my_recording.wav` to Suno.

When Suno returns its output and you've finished your session in Logic Pro, continue with the steps in the next section and include `--pre-reg pre_reg.json` in the final sign step.

---

### I have my Suno output and my Logic Pro session is finished

Run these steps in order. Each command writes a JSON file that feeds into the next.

**Step 1 — Extract provenance data from the Suno file:**
```bash
provenance-tool seed-extract suno_output.mp3 > seed.json
```

This reads the Suno MP3 or WAV, strips any subjective metadata, computes a SHA-256 fingerprint, and records the origin timestamp.

**Step 2 — Audit your Logic Pro session:**
```bash
provenance-tool daw-audit Session.logicx \
  --seed-hash $(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" suno_output.mp3) \
  > session.json
```

This scans the `.logicx` bundle and classifies every track as `seed`, `human_led`, or `programmed` based on what audio and MIDI data is present.

**Step 3 — Build the provenance record:**
```bash
# Without pre-registration (Suno export was your starting point)
provenance-tool loopback --seed seed.json --session session.json > provenance.json

# With pre-registration (you fingerprinted your audio before Suno)
provenance-tool loopback --seed seed.json --session session.json --pre-reg pre_reg.json > provenance.json
```

This links the seed fingerprint to the session audit and computes a deterministic `loopback_id`.

**Step 4 — Sign the master:**
```bash
provenance-tool sign \
  --master      final_master.wav \
  --seed-audio  suno_output.mp3 \
  --provenance  provenance.json \
  --cert        certs/es256_certs.pem \
  --key         certs/es256_private.key \
  --output      signed_master.wav
```

This embeds the full provenance record into the master file as a cryptographically signed C2PA manifest. The original audio quality is untouched.

---

### I want to run the full pipeline in one command

If you don't need to inspect intermediate JSON files, you can run everything at once:

```bash
# Without pre-registration
provenance-tool run \
  --seed-audio  suno_output.mp3 \
  --logicx      Session.logicx \
  --master      final_master.wav \
  --cert        certs/es256_certs.pem \
  --key         certs/es256_private.key \
  --output      signed_master.wav

# With pre-registration receipt
provenance-tool run \
  --seed-audio  suno_output.mp3 \
  --logicx      Session.logicx \
  --master      final_master.wav \
  --cert        certs/es256_certs.pem \
  --key         certs/es256_private.key \
  --output      signed_master.wav \
  --pre-reg     pre_reg.json
```

---

### I want to verify a signed master

```bash
c2patool signed_master.wav
```

The output will contain the `com.provenance.music.loopback` assertion with the full provenance record — seed ID, track classification counts, session metadata, and timestamp.

---

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

---

## Certificate Setup

The signing step requires an X.509 ES256 certificate and private key.

### Development (self-signed, for testing)

```bash
mkdir -p certs

openssl ecparam -name prime256v1 -genkey -noout -out certs/es256_private.key

openssl req -new -x509 -key certs/es256_private.key \
  -out certs/es256_certs.pem -days 365 \
  -subj "/CN=Provenance Dev/O=Dev"
```

> Self-signed certificates validate structurally but show as "untrusted" in public C2PA verifiers like [Content Credentials Verify](https://contentcredentials.org/verify). This is expected for development.

### Production

For manifests that validate on the [C2PA Trust List](https://opensource.contentauthenticity.org/docs/conformance/trust-lists), obtain a certificate from a recognized CA such as [GlobalSign](https://www.globalsign.com/) or [DigiCert](https://www.digicert.com/). Place the files at `certs/es256_certs.pem` (full chain) and `certs/es256_private.key`.

To add a trusted timestamp for long-term validity, append `--ta-url http://timestamp.digicert.com` to any `sign` or `run` command.

### Installing c2patool (verification only)

```bash
brew install c2patool
```

---

## Running Tests

```bash
pip3 install pytest
PYTHONPATH=src python3 -m pytest tests/ -v
```

## Reference

See [PRODUCT.md](PRODUCT.md) for the full technical specification and [AGENTS.md](AGENTS.md) for data-handling rules and development constraints.
