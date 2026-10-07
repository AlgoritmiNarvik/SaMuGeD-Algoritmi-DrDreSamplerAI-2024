"""Parquet schema shared by every public phrase configuration.

The published Lakh configurations and the corpus expansion configurations use exactly this schema, so a
consumer can concatenate them without casting. Changing it changes the public dataset contract.
"""
from __future__ import annotations

PHRASE_TEXT = ("phrase_id", "source_id", "source_path", "source_sha256", "artist", "title", "kind",
               "family_id", "split", "split_group", "part_name", "occurrences_json", "matcher_flags_json")
PHRASE_INT = ("start_tick", "end_tick", "ticks_per_beat", "note_count", "occurrence_count", "program")
PHRASE_FLOAT = ("duration_beats", "recurrence_score")
PHRASE_FLOAT_LIST = ("onsets_beats", "durations_beats")
PHRASE_INT_LIST = ("pitches", "velocities")


def phrase_schema():
    """Return the pyarrow schema of one public phrase row, including the exported MIDI bytes."""
    import pyarrow as pa
    fields = [pa.field(k, pa.string()) for k in PHRASE_TEXT]
    fields += [pa.field(k, pa.int64()) for k in PHRASE_INT]
    fields += [pa.field(k, pa.float64()) for k in PHRASE_FLOAT]
    fields += [pa.field(k, pa.list_(pa.float64())) for k in PHRASE_FLOAT_LIST]
    fields += [pa.field(k, pa.list_(pa.int64())) for k in PHRASE_INT_LIST]
    fields += [pa.field("midi_bytes", pa.binary()), pa.field("midi_sha256", pa.string())]
    return pa.schema(fields)
