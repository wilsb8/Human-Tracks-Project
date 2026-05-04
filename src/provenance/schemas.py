"""Typed schemas for all inter-module data contracts."""

from __future__ import annotations

from typing import TypedDict


class SeedResult(TypedDict):
    seed_id: str
    origin_timestamp: str
    source_format: str
    source_file_hash: str
    metadata_fields: dict[str, str]


class SessionMetadata(TypedDict):
    tempo_bpm: float
    key_signature: str
    time_signature: str
    sample_rate: int


class TrackInfo(TypedDict):
    index: int
    classification: str  # "human_led" | "seed" | "programmed"
    has_audio_regions: bool
    audio_region_count: int


class TrackSummary(TypedDict):
    total_tracks: int
    human_led_count: int
    seed_count: int
    programmed_count: int


class SessionResult(TypedDict):
    project_file: str
    logic_version: str
    session_metadata: SessionMetadata
    track_summary: TrackSummary
    tracks: list[TrackInfo]


class SeedSection(TypedDict):
    seed_id: str
    origin_timestamp: str
    source_file_hash: str


class SessionSection(TypedDict):
    project_file: str
    tempo_bpm: float
    key_signature: str
    time_signature: str
    sample_rate: int
    total_tracks: int
    human_led_count: int
    seed_count: int
    programmed_count: int


class ProvenanceRecord(TypedDict):
    loopback_id: str
    seed: SeedSection
    session: SessionSection
    provenance_timestamp: str


class ErrorResult(TypedDict):
    error: str
    module: str
