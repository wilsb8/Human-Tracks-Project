# Agent Rules — Digital Provenance Tool

## Prime Directive
This tool exists to record **mechanical facts**, not opinions. Every rule below serves that constraint.

---

## 1. Data Rules

### 1.1 Allowed Data
Only the following categories of data may appear in any output (JSON, manifest, log):
- File hashes (SHA-256)
- Timestamps (ISO-8601 only)
- Numeric counts (tracks, regions, sequences)
- Numeric session parameters (tempo, sample rate)
- Musical key and time signature (as structural metadata, not interpretation)
- Software identifiers (encoder name, DAW version — never user-authored text)
- Format identifiers (MIME type, codec name)
- Deterministic IDs derived from the above via hashing

### 1.2 Prohibited Data
The following MUST be stripped, redacted, or never collected:
- Track names, region names, or any user-typed label
- Lyrics, descriptions, comments with prose content
- Artist name, album name, or any biographical field
- Plugin names or preset names (these leak creative intent)
- Cover art or image data
- Any field requiring subjective judgment to populate
- Suno prompt text, style tags, or generation parameters that describe creative intent

### 1.3 Metadata Filtering
When reading ID3/RIFF metadata from a Suno file, apply an allowlist:
- **Allowed ID3 frames:** TSSE, TENC, TDRC, TYER, TDAT, TOFN, TXXX (only if key matches: `encoder`, `software`, `tool`, `version`, `creation_date`)
- **Allowed RIFF chunks:** ISFT, ICRD, IDIT
- **Everything else:** Discard silently. Do not log discarded field names.

---

## 2. Code Rules

### 2.1 Module Boundaries
- Each module (`seed_extractor`, `daw_auditor`, `loopback_engine`, `c2pa_signer`) is a standalone Python module with a single public function as its entry point.
- Modules communicate exclusively via JSON-serializable dicts matching the schemas in `PRODUCT.md`.
- No module may import another module directly. The CLI orchestrator (`cli.py`) is the only integration point.

### 2.2 Error Handling
- All file I/O errors must be caught and converted to structured error dicts: `{"error": "description", "module": "module_name"}`.
- Never silently swallow exceptions. Log the error, return the error dict, and let the CLI decide whether to abort.
- Binary parsing errors in `ProjectData` must not crash the tool. If a FourCC marker is malformed, skip it and continue scanning.

### 2.3 No Network Calls
- No module may make network requests. All data comes from local files.
- The only exception is `c2pa_signer.py` which may optionally contact a Time Stamp Authority (TSA) URL if one is provided. This is the only allowed outbound connection.

### 2.4 Determinism
- Given identical input files, the tool must produce byte-identical JSON output (excluding `provenance_timestamp`).
- Use `json.dumps(obj, sort_keys=True, separators=(',', ':'))` for all canonical JSON serialization.
- Hash computations use raw file bytes, not parsed/re-encoded content.

### 2.5 Type Safety
- All public functions must have full type annotations.
- Use `TypedDict` for the schema types defined in `PRODUCT.md`.
- No `Any` types in public interfaces.

---

## 3. Binary Parsing Rules (ProjectData)

### 3.1 Marker Scanning
- Scan the `ProjectData` binary by sliding a 4-byte window, looking for known reversed FourCC markers.
- Known markers and their meanings:
  - `karT` → Track
  - `gRuA` → AudioRegion
  - `qeSM` → MIDISequence
  - `tSnI` → Instrument
  - `LFUA` → AudioFile reference
- When a marker is found, record its byte offset and count it. Do not attempt to fully parse the chunk payload unless the schema is well-understood.

### 3.2 Track Classification Heuristic
- A track is `seed` if it contains an audio region whose associated audio file hash matches the seed file hash.
- A track is `human_led` if it contains audio regions whose associated files do NOT match the seed hash.
- A track is `programmed` if it contains only MIDI sequences and no audio regions.
- If classification is ambiguous (e.g., a track has both matching and non-matching audio), classify as `human_led` (conservative: assume human involvement).

### 3.3 Plist Parsing
- Use `plistlib.load()` from the standard library. Do not use third-party plist parsers.
- If the plist is in binary format, `plistlib` handles it natively.
- Extract only the fields listed in the DAW Auditor output schema. Ignore all others.

---

## 4. C2PA Rules

### 4.1 Manifest Structure
The C2PA manifest must include exactly these assertions:
1. `c2pa.actions.v2` — with action `c2pa.created` and the `compositeWithTrainedAlgorithmicMedia` digital source type.
2. `com.provenance.music.loopback` — the full Provenance Record JSON as the assertion data.

No other custom assertions are permitted without explicit specification change.

### 4.2 Ingredient Chain
- The seed audio file must be added as a `parentOf` ingredient to the signed master.
- The ingredient must carry its file hash but no metadata beyond format and hash.

### 4.3 Signing
- Default algorithm: ES256.
- Certificate and key paths are required CLI arguments. The tool must never ship with or generate test certificates in production mode.
- If `--ta-url` is provided, request a timestamp from the TSA. Otherwise, omit the timestamp.

---

## 5. Testing Rules

### 5.1 Test Data
- Tests must use synthetic/mock data, not real Suno exports or Logic Pro projects.
- Create minimal valid MP3/WAV files with known metadata for seed extractor tests.
- Create minimal `.logicx` bundle stubs (plist + binary with injected FourCC markers) for DAW auditor tests.

### 5.2 Coverage
- Every public function must have at least one happy-path and one error-path test.
- Binary parsing must be tested with edge cases: truncated files, missing markers, zero-length payloads.

### 5.3 No Mocking of Hashes
- Never mock `hashlib`. Compute real hashes against real (synthetic) test data to ensure determinism guarantees hold.

---

## 6. Git & Commit Rules
- Commit messages must be imperative tense, max 72 chars on the first line.
- Every commit from an AI agent must include: `Co-Authored-By: Oz <oz-agent@warp.dev>`
- No generated or binary test fixtures in the repo. Generate them in test setup.
