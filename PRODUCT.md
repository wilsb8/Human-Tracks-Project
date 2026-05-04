# Digital Provenance & Metadata Loopback Tool

## Purpose
A Python CLI tool that produces a verifiable Proof-of-Work manifest distinguishing professional musicianship from pure AI-prompted content. It does this by mechanically linking an AI-generated audio seed to a DAW session audit and signing the result with a C2PA content credential.

## Scope
Strictly mechanical provenance. No subjective, biographical, or aesthetic data enters the manifest. The tool answers one question: **what was the machine-verifiable chain of events between the AI seed and the signed master?**

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐
│ Suno Audio   │────▶│ Seed Extract  │────▶│  Loopback    │────▶│ C2PA Sign  │
│ (.mp3/.wav)  │     │  Module       │     │  Engine      │     │  Module    │
└─────────────┘     └──────────────┘     └──────┬───────┘     └────────────┘
                                                 │
┌─────────────┐     ┌──────────────┐             │
│ Logic Pro    │────▶│ DAW Audit    │─────────────┘
│ (.logicx)    │     │  Module      │
└─────────────┘     └──────────────┘
```

Four modules, one pipeline:

1. **Seed Extractor** — reads a Suno audio file and extracts provenance fields.
2. **DAW Auditor** — reads a Logic Pro 11 `.logicx` bundle and classifies tracks.
3. **Loopback Engine** — marries the seed identity to the session audit.
4. **C2PA Signer** — embeds the loopback result into a signed C2PA manifest on the final master.

---

## Module Specifications

### 1. Seed Extractor (`seed_extractor.py`)

**Input:** Path to a Suno-exported audio file (MP3 or WAV).

**Process:**
- MP3: Parse ID3v2 frames via `mutagen`. Extract all available generation metadata from standard and custom frames (TXXX, COMM, TSSE, TENC, TOFN).
- WAV: Parse RIFF INFO chunks and any embedded ID3 data. Read `ISFT`, `ICMT`, `ICRD`, `INAM` fields.
- Compute a deterministic `seed_id` as: `SHA-256(raw_file_bytes)[0:16]` — this is the canonical identifier when no explicit Suno generation ID is present in metadata.
- Extract `origin_timestamp`: prefer embedded date fields (TDRC, ICRD); fall back to filesystem creation time.

**Output schema:**
```json
{
  "seed_id": "string (hex, 16 chars)",
  "origin_timestamp": "ISO-8601 string",
  "source_format": "mp3 | wav",
  "source_file_hash": "SHA-256 hex digest of full file",
  "metadata_fields": {
    "key": "value"
  }
}
```

**Constraint:** No field in `metadata_fields` may contain subjective content (e.g., lyrics, descriptions). If present, strip them before output. Allowed: tool name, encoder, software version, date, numeric IDs.

---

### 2. DAW Auditor (`daw_auditor.py`)

**Input:** Path to a `.logicx` bundle.

**Process:**
- Validate bundle structure: confirm `Alternatives/000/MetaData.plist` and `Alternatives/000/ProjectData` exist.
- Parse `MetaData.plist` (Apple plist) for: tempo, key signature, time signature, track count, sample rate, Logic Pro version.
- Parse `ProjectData` binary for track classification:
  - Scan for reversed FourCC markers: `karT` (Track), `gRuA` (AudioRegion), `qeSM` (MIDISequence), `tSnI` (Instrument).
  - Count audio region markers (`gRuA`) — these indicate recorded or imported audio.
  - Count MIDI sequence markers (`qeSM`) — these indicate software instrument / MIDI data.
- Classify tracks:
  - **Human-Led**: Tracks with audio regions linked to recorded audio files (files in `Media/` that were NOT the original seed import). Evidence: `gRuA` markers with associated audio file paths that differ from the seed source.
  - **Seed**: Tracks containing audio that matches the seed file (by filename pattern or hash comparison against seed extractor output).
  - **Programmed**: Tracks with MIDI/instrument data only (no audio recording activity).

**Output schema:**
```json
{
  "project_file": "string (basename)",
  "logic_version": "string",
  "session_metadata": {
    "tempo_bpm": "float",
    "key_signature": "string",
    "time_signature": "string",
    "sample_rate": "int"
  },
  "track_summary": {
    "total_tracks": "int",
    "human_led_count": "int",
    "seed_count": "int",
    "programmed_count": "int"
  },
  "tracks": [
    {
      "index": "int",
      "classification": "human_led | seed | programmed",
      "has_audio_regions": "bool",
      "audio_region_count": "int"
    }
  ]
}
```

**Constraint:** Track names, plugin names, and any user-typed labels are excluded from the output. Only structural/mechanical data is emitted.

---

### 3. Loopback Engine (`loopback_engine.py`)

**Input:** Seed extractor output + DAW auditor output.

**Process:**
- Validate that at least one track is classified as `seed` — if zero, abort with error (no provenance chain to establish).
- Validate that at least one track is classified as `human_led` — if zero, emit a warning (the session contains no evidence of human recording activity).
- Compute `loopback_id`: `SHA-256(seed_id + project_file + total_tracks + human_led_count)`.
- Assemble the provenance record.

**Output schema (the Provenance Record):**
```json
{
  "loopback_id": "string (hex, 16 chars)",
  "seed": {
    "seed_id": "string",
    "origin_timestamp": "ISO-8601",
    "source_file_hash": "string"
  },
  "session": {
    "project_file": "string",
    "tempo_bpm": "float",
    "key_signature": "string",
    "time_signature": "string",
    "sample_rate": "int",
    "total_tracks": "int",
    "human_led_count": "int",
    "seed_count": "int",
    "programmed_count": "int"
  },
  "provenance_timestamp": "ISO-8601 (time of loopback execution)"
}
```

---

### 4. C2PA Signer (`c2pa_signer.py`)

**Input:** Path to the final master audio file + Provenance Record JSON.

**Process:**
- Build a C2PA manifest definition embedding the Provenance Record as a custom assertion under the label `com.provenance.music.loopback`.
- Include a `c2pa.actions.v2` assertion documenting the action chain: `c2pa.created` with `digitalSourceType` of `http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia`.
- Add the seed audio file as an ingredient (parent) to establish the content lineage.
- Sign with a provided X.509 certificate and private key (paths passed via CLI args or env vars).
- Write the signed master to the output path.

**Output:** A new audio file with an embedded C2PA manifest containing the full provenance record.

**Constraint:** The manifest must NOT contain any assertion with subjective claims about quality, originality, or authorship intent. It records only mechanical facts.

---

## CLI Interface

```
provenance-tool seed-extract <suno_audio_file>
provenance-tool daw-audit <logicx_bundle>
provenance-tool loopback --seed <seed_json> --session <session_json>
provenance-tool sign --master <audio_file> --provenance <provenance_json> \
                     --cert <cert.pem> --key <key.pem> --output <signed_file>
provenance-tool run --seed-audio <suno_file> --logicx <bundle> \
                    --master <audio_file> --cert <cert.pem> --key <key.pem> \
                    --output <signed_file>
```

`run` executes the full pipeline in one invocation.

---

## Dependencies

- Python >= 3.10
- `mutagen` — audio metadata parsing (ID3, RIFF)
- `c2pa-python` — C2PA manifest creation and signing
- Standard library: `plistlib`, `struct`, `hashlib`, `json`, `pathlib`, `datetime`

---

## Verification

A signed master can be verified by any C2PA-compliant reader:
```
c2patool signed_master.wav
```
The output will include the `com.provenance.music.loopback` assertion containing the full provenance record.
