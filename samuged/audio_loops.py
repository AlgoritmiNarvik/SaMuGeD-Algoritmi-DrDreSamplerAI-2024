"""Deterministic source-derived MIDI and audio loop rendering.

The published phrase MIDI is retained as provenance.  The playable loop is
rebuilt from the referenced source part over a recurrence-derived cycle, so a
detector window that ends before the next recurrence does not truncate the
musical cycle.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.metadata import version as package_version
from io import BytesIO
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Iterable
import wave

import mido
import numpy as np

from .drums import drum_part
from .midi import MidiSong, Note, Part, export_phrase, load_midi


VERSION = "source-audio-loops-v2"
SAMPLE_RATE = 48_000
RENDER_REPETITIONS = 6
STEADY_REPETITION = 3
_DEFAULT_TEMPO = 500_000
_DEFAULT_METER = (4, 4)


@dataclass(frozen=True, slots=True)
class PeriodDecision:
    """A measured cycle period and the evidence used to choose it."""

    period_ticks: int
    period_beats: float
    policy: str
    phrase_duration_ticks: int
    phrase_duration_beats: float
    padding_ticks: int
    nonoverlapping_start_differences_ticks: tuple[int, ...]
    grid_ticks: int
    tolerance_ticks: int
    supporting_difference_count: int
    eligible_difference_count: int
    fallback_meter_numerator: int | None
    fallback_meter_denominator: int | None
    fallback_bar_ticks: float | None
    fallback_assumption: str | None


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_json_bytes(value))


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer at least {minimum}")
    return value


def _occurrence_intervals(row: dict[str, Any]) -> list[tuple[int, int]]:
    phrase_id = row.get("phrase_id", "unknown")
    occurrences = row.get("occurrences")
    if not isinstance(occurrences, list) or not occurrences:
        raise ValueError(f"phrase {phrase_id} has no saved occurrences")
    intervals: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            raise ValueError(f"phrase {phrase_id} has an invalid occurrence")
        start = _integer(occurrence.get("start_tick"), "occurrence start")
        end = _integer(occurrence.get("end_tick"), "occurrence end", minimum=1)
        if end <= start:
            raise ValueError(f"phrase {phrase_id} has an invalid occurrence interval")
        if (start, end) not in seen:
            intervals.append((start, end))
            seen.add((start, end))
    return sorted(intervals)


def _validated_meter(meter: tuple[int, int]) -> tuple[int, int]:
    if not isinstance(meter, tuple) or len(meter) != 2:
        raise ValueError("meter must be a (numerator, denominator) tuple")
    numerator = _integer(meter[0], "meter numerator", minimum=1)
    denominator = _integer(meter[1], "meter denominator", minimum=1)
    if denominator & (denominator - 1):
        raise ValueError("meter denominator must be a power of two")
    return numerator, denominator


def infer_loop_period(
    row: dict[str, Any], meter: tuple[int, int] | None = None
) -> PeriodDecision:
    """Infer a conservative musical cycle from recurring occurrence starts.

    Only adjacent saved occurrences that do not overlap contribute direct
    evidence.  Their start differences are snapped to a quarter-beat grid with
    a small timing tolerance.  A candidate needs at least two supporting
    differences and at least 30 percent of the eligible evidence.  Otherwise
    the phrase window is padded to a whole bar under the supplied start meter,
    or to a whole beat when no meter is supplied.  A fallback is a formatting
    policy for a loop asset, not measured recurrence evidence.
    """

    ppq = _integer(row.get("ticks_per_beat"), "ticks_per_beat", minimum=1)
    start = _integer(row.get("start_tick"), "start_tick")
    end = _integer(row.get("end_tick"), "end_tick", minimum=1)
    if end <= start:
        raise ValueError("phrase interval must have positive duration")
    duration = end - start
    intervals = _occurrence_intervals(row)
    differences = tuple(
        right_start - left_start
        for (left_start, left_end), (right_start, _right_end) in zip(
            intervals, intervals[1:]
        )
        if right_start >= left_end
    )
    grid = max(1, round(ppq / 4))
    tolerance = max(2, round(ppq * 0.04))
    snapped: list[tuple[int, int]] = []
    for difference in differences:
        candidate = max(grid, round(difference / grid) * grid)
        if candidate >= duration and abs(candidate - difference) <= tolerance:
            snapped.append((candidate, abs(candidate - difference)))

    counts = Counter(candidate for candidate, _error in snapped)
    chosen: int | None = None
    support = 0
    if counts:
        ranked = sorted(
            counts,
            key=lambda candidate: (
                -counts[candidate],
                sum(error for value, error in snapped if value == candidate),
                candidate,
            ),
        )
        candidate = ranked[0]
        candidate_support = counts[candidate]
        if candidate_support >= 2 and candidate_support / len(differences) >= 0.30:
            chosen = candidate
            support = candidate_support

    fallback_numerator: int | None = None
    fallback_denominator: int | None = None
    fallback_bar_ticks: float | None = None
    fallback_assumption: str | None = None
    if chosen is None and meter is not None:
        fallback_numerator, fallback_denominator = _validated_meter(meter)
        fallback_bar_ticks = (
            ppq * fallback_numerator * 4 / fallback_denominator
        )
        chosen = math.ceil(duration / fallback_bar_ticks) * fallback_bar_ticks
        chosen = math.ceil(chosen)
        policy = "fallback_pad_phrase_to_whole_bars_at_start_meter"
        fallback_assumption = (
            "uses the meter active at the phrase start for every fallback bar; "
            "later meter changes inside the cycle do not change its boundary; "
            "this is loop formatting, not measured recurrence evidence"
        )
    elif chosen is None:
        chosen = math.ceil(duration / ppq) * ppq
        policy = "fallback_pad_phrase_to_whole_beat_without_meter"
        fallback_assumption = (
            "no source meter was supplied; whole-beat padding is loop formatting, "
            "not measured recurrence evidence"
        )
    else:
        policy = "frequent_nonoverlapping_occurrence_start_difference"
    return PeriodDecision(
        period_ticks=chosen,
        period_beats=chosen / ppq,
        policy=policy,
        phrase_duration_ticks=duration,
        phrase_duration_beats=duration / ppq,
        padding_ticks=chosen - duration,
        nonoverlapping_start_differences_ticks=differences,
        grid_ticks=grid,
        tolerance_ticks=tolerance,
        supporting_difference_count=support,
        eligible_difference_count=len(differences),
        fallback_meter_numerator=fallback_numerator,
        fallback_meter_denominator=fallback_denominator,
        fallback_bar_ticks=fallback_bar_ticks,
        fallback_assumption=fallback_assumption,
    )


def source_cycle_notes(part: Part, start_tick: int, period_ticks: int) -> list[Note]:
    """Return source notes whose onsets fall in the cycle, clamped at its end."""

    end_tick = start_tick + period_ticks
    return [
        Note(
            start=note.start,
            end=min(note.end, end_tick),
            pitch=note.pitch,
            velocity=note.velocity,
        )
        for note in part.notes
        if start_tick <= note.start < end_tick and note.end > note.start
    ]


def seconds_between(song: MidiSong, start_tick: int, end_tick: int) -> float:
    """Integrate the source tempo map over ``[start_tick, end_tick)``."""

    if end_tick <= start_tick:
        raise ValueError("tempo integration interval must have positive duration")
    tempo = _DEFAULT_TEMPO
    cursor = start_tick
    seconds = 0.0
    for tick, value in sorted(song.tempos):
        if tick <= start_tick:
            tempo = value
        elif tick < end_tick:
            seconds += (
                (tick - cursor) * tempo / (song.ticks_per_beat * 1_000_000)
            )
            cursor = tick
            tempo = value
        else:
            break
    seconds += (end_tick - cursor) * tempo / (song.ticks_per_beat * 1_000_000)
    return seconds


def _active_change(
    changes: Iterable[tuple[int, ...]], tick: int, default: tuple[int, ...]
) -> tuple[int, ...]:
    active = default
    for change in sorted(changes):
        if change[0] > tick:
            break
        active = tuple(change[1:])
    return active


def active_meter(song: MidiSong, tick: int) -> tuple[int, int]:
    """Return the validated source meter active at one source tick."""

    tick = _integer(tick, "tick")
    numerator, denominator = _active_change(song.meters, tick, _DEFAULT_METER)
    return _validated_meter((int(numerator), int(denominator)))


def _cycle_metadata(
    song: MidiSong, start_tick: int, period_ticks: int
) -> tuple[list[tuple[int, int]], list[tuple[int, int, int]]]:
    end_tick = start_tick + period_ticks
    tempo = _active_change(song.tempos, start_tick, (_DEFAULT_TEMPO,))[0]
    meter = _active_change(song.meters, start_tick, _DEFAULT_METER)
    tempos = [(0, int(tempo))]
    meters = [(0, int(meter[0]), int(meter[1]))]
    tempos.extend(
        (tick - start_tick, value)
        for tick, value in sorted(song.tempos)
        if start_tick < tick < end_tick
    )
    meters.extend(
        (tick - start_tick, numerator, denominator)
        for tick, numerator, denominator in sorted(song.meters)
        if start_tick < tick < end_tick
    )
    return tempos, meters


def _delta_track(
    events: list[tuple[int, int, int, mido.Message | mido.MetaMessage]],
    end_tick: int,
) -> mido.MidiTrack:
    track = mido.MidiTrack()
    previous = 0
    for tick, _priority, _sequence, message in sorted(events, key=lambda item: item[:3]):
        track.append(message.copy(time=tick - previous))
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=end_tick - previous))
    return track


def write_repeated_midi(
    song: MidiSong,
    part: Part,
    notes: list[Note],
    start_tick: int,
    period_ticks: int,
    repetitions: int,
    path: Path,
) -> None:
    """Schedule a source cycle repeatedly for steady-state audio rendering."""

    repetitions = _integer(repetitions, "repetitions", minimum=2)
    total_ticks = period_ticks * repetitions
    tempos, meters = _cycle_metadata(song, start_tick, period_ticks)
    metadata_events: list[tuple[int, int, int, mido.MetaMessage]] = []
    sequence = 0
    for repetition in range(repetitions):
        offset = repetition * period_ticks
        for tick, tempo in tempos:
            metadata_events.append(
                (offset + tick, 0, sequence, mido.MetaMessage("set_tempo", tempo=tempo))
            )
            sequence += 1
        for tick, numerator, denominator in meters:
            metadata_events.append(
                (
                    offset + tick,
                    1,
                    sequence,
                    mido.MetaMessage(
                        "time_signature",
                        numerator=numerator,
                        denominator=denominator,
                    ),
                )
            )
            sequence += 1

    note_events: list[tuple[int, int, int, mido.Message | mido.MetaMessage]] = []
    sequence = 0
    if part.name:
        note_events.append((0, 0, sequence, mido.MetaMessage("track_name", name=part.name)))
        sequence += 1
    note_events.append(
        (
            0,
            1,
            sequence,
            mido.Message("program_change", channel=part.channel, program=part.program),
        )
    )
    sequence += 1
    for repetition in range(repetitions):
        offset = repetition * period_ticks
        for note in notes:
            relative_start = note.start - start_tick
            relative_end = min(note.end - start_tick, period_ticks)
            note_events.append(
                (
                    offset + relative_start,
                    3,
                    sequence,
                    mido.Message(
                        "note_on",
                        channel=part.channel,
                        note=note.pitch,
                        velocity=note.velocity,
                    ),
                )
            )
            sequence += 1
            note_events.append(
                (
                    offset + relative_end,
                    2,
                    sequence,
                    mido.Message(
                        "note_off", channel=part.channel, note=note.pitch, velocity=0
                    ),
                )
            )
            sequence += 1

    midi = mido.MidiFile(type=1, ticks_per_beat=song.ticks_per_beat)
    midi.tracks.append(_delta_track(metadata_events, total_ticks))
    midi.tracks.append(_delta_track(note_events, total_ticks))
    buffer = BytesIO()
    midi.save(file=buffer)
    path.write_bytes(buffer.getvalue())


def _read_wave(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_rate = handle.getframerate()
        width = handle.getsampwidth()
        frames = handle.getnframes()
        payload = handle.readframes(frames)
    if channels != 2:
        raise ValueError(f"FluidSynth output must be stereo, got {channels} channels")
    if width == 2:
        values = np.frombuffer(payload, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 3:
        packed = np.frombuffer(payload, dtype=np.uint8).reshape(-1, 3)
        integers = (
            packed[:, 0].astype(np.int32)
            | (packed[:, 1].astype(np.int32) << 8)
            | (packed[:, 2].astype(np.int32) << 16)
        )
        integers = np.where(integers & 0x800000, integers - 0x1000000, integers)
        values = integers.astype(np.float64) / 8_388_608.0
    elif width == 4:
        values = np.frombuffer(payload, dtype="<i4").astype(np.float64) / 2_147_483_648.0
    else:
        raise ValueError(f"unsupported rendered WAV sample width: {width}")
    return values.reshape(-1, channels), sample_rate


def write_pcm24_wave(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Write stereo floating-point samples as little-endian 24-bit PCM."""

    if audio.ndim != 2 or audio.shape[1] != 2:
        raise ValueError("audio must have shape (frames, 2)")
    if not np.isfinite(audio).all():
        raise ValueError("audio contains non-finite samples")
    peak = float(np.max(np.abs(audio), initial=0.0))
    if peak > 1.0:
        raise ValueError(f"audio clips before PCM conversion: peak={peak:.8f}")
    integers = np.rint(np.clip(audio, -1.0, 1.0) * 8_388_607).astype("<i4")
    packed = integers.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(3)
        handle.setframerate(sample_rate)
        handle.writeframes(packed)


def process_steady_cycle(
    rendered: np.ndarray,
    rendered_sample_rate: int,
    cycle_seconds: float,
    *,
    steady_repetition: int = STEADY_REPETITION,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Cut one steady repetition, normalize and condition a measurable seam."""

    if rendered_sample_rate != SAMPLE_RATE:
        raise ValueError(
            f"render sample rate is {rendered_sample_rate}, expected {SAMPLE_RATE}"
        )
    expected_frames = round(cycle_seconds * SAMPLE_RATE)
    start_frame = round(steady_repetition * cycle_seconds * SAMPLE_RATE)
    end_frame = start_frame + expected_frames
    if expected_frames <= 0 or end_frame > len(rendered):
        raise ValueError("rendered audio does not contain the requested steady cycle")
    audio = rendered[start_frame:end_frame].astype(np.float64, copy=True)
    input_peak = float(np.max(np.abs(audio), initial=0.0))
    if input_peak <= 1e-8:
        raise ValueError("FluidSynth rendered silence")
    target_peak = 10 ** (-1.0 / 20.0)
    gain = target_peak / input_peak
    audio *= gain

    internal_steps = np.abs(np.diff(audio, axis=0))
    reference_step = float(np.percentile(internal_steps, 95)) if len(internal_steps) else 0.0
    seam_before = float(np.max(np.abs(audio[0] - audio[-1])))
    condition = seam_before > 0.02 and seam_before > 2 * max(reference_step, 1e-6)
    conditioning_frames = 0
    if condition:
        conditioning_frames = min(round(SAMPLE_RATE * 0.005), max(1, len(audio) // 100))
        seam_target = (audio[0] + audio[-1]) / 2
        ramp = np.linspace(1.0, 0.0, conditioning_frames, dtype=np.float64)[:, None]
        audio[:conditioning_frames] += (seam_target - audio[0]) * ramp
        audio[-conditioning_frames:] += (seam_target - audio[-1]) * ramp[::-1]

    conditioned_peak = float(np.max(np.abs(audio), initial=0.0))
    limiter_gain = 1.0
    if conditioned_peak > target_peak:
        limiter_gain = target_peak / conditioned_peak
        audio *= limiter_gain
    seam_after = float(np.max(np.abs(audio[0] - audio[-1])))
    output_peak = float(np.max(np.abs(audio), initial=0.0))
    return audio, {
        "sample_rate_hz": SAMPLE_RATE,
        "channels": 2,
        "sample_format": "PCM signed 24-bit little-endian",
        "frame_count": expected_frames,
        "duration_seconds": expected_frames / SAMPLE_RATE,
        "render_cut_repetition_index": steady_repetition,
        "input_peak": input_peak,
        "normalization_gain": gain,
        "post_conditioning_gain": limiter_gain,
        "output_peak": output_peak,
        "clipped_sample_count": int(np.count_nonzero(np.abs(audio) > 1.0)),
        "edge_discontinuity_before": seam_before,
        "edge_discontinuity_after": seam_after,
        "internal_step_p95": reference_step,
        "edge_conditioning_applied": condition,
        "edge_conditioning_frames_per_side": conditioning_frames,
        "edge_conditioning_policy": (
            "symmetric 5 ms endpoint correction when seam exceeds 0.02 and 2x "
            "the internal 95th-percentile sample step"
        ),
        "tail_policy": (
            "cut a middle cycle from repeated synthesis so prior-cycle release and "
            "reverb are present; no tail gap is appended"
        ),
    }


def _run(command: list[str], label: str) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"{label} failed with exit {completed.returncode}: {detail}")


def _tool_version(executable: Path, argument: str, label: str) -> str:
    completed = subprocess.run(
        [str(executable), argument], capture_output=True, text=True, check=False
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"{label} version check failed with exit {completed.returncode}: {detail}"
        )
    lines = [
        line.strip()
        for line in (completed.stdout + "\n" + completed.stderr).splitlines()
        if line.strip()
    ]
    if not lines:
        raise RuntimeError(f"{label} version check returned no version string")
    return lines[0]


def _renderer_provenance(fluidsynth: Path, ffmpeg: Path) -> dict[str, Any]:
    """Bind a manifest to the renderer code, dependencies and command tools."""

    audio_loops_path = Path(__file__).resolve()
    midi_path = audio_loops_path.with_name("midi.py")
    return {
        "synthesis": {"sample_rate_hz": SAMPLE_RATE, "intermediate_format": "s24", "gain": 0.45},
        "code": {
            "samuged/audio_loops.py": _sha256_file(audio_loops_path),
            "samuged/midi.py": _sha256_file(midi_path),
        },
        "python_dependencies": {
            "numpy": package_version("numpy"),
            "mido": package_version("mido"),
        },
        "tools": {
            "fluidsynth": {
                "path": str(fluidsynth),
                "version": _tool_version(fluidsynth, "--version", "FluidSynth"),
            },
            "ffmpeg": {
                "path": str(ffmpeg),
                "version": _tool_version(ffmpeg, "-version", "FFmpeg"),
            },
        },
    }


def _resolve_source(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("source_path must be a nonempty string")
    resolved_root = root.resolve(strict=True)
    candidate = (resolved_root / relative).resolve(strict=True)
    if not candidate.is_relative_to(resolved_root) or not candidate.is_file():
        raise ValueError(f"source_path escapes or is absent from source root: {relative!r}")
    return candidate


def _load_phrase_rows(dataset: Path) -> tuple[Path, dict[str, dict[str, Any]]]:
    manifest = dataset / "phrases.jsonl" if dataset.is_dir() else dataset
    rows: dict[str, dict[str, Any]] = {}
    with manifest.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            phrase_id = row.get("phrase_id") if isinstance(row, dict) else None
            if not isinstance(phrase_id, str) or not phrase_id or phrase_id in rows:
                raise ValueError(f"invalid or duplicate phrase ID at line {line_number}")
            rows[phrase_id] = row
    return manifest, rows


def load_phrase_ids(path: Path) -> list[str]:
    """Read an ordered ID list or an object containing a ``candidates`` list."""

    value = json.loads(path.read_text(encoding="utf-8"))
    candidates = value.get("candidates") if isinstance(value, dict) else value
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("phrase ID JSON must be a nonempty list or object with candidates")
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        phrase_id = candidate.get("phrase_id") if isinstance(candidate, dict) else candidate
        if not isinstance(phrase_id, str) or not phrase_id:
            raise ValueError("each candidate must be a phrase ID or object with phrase_id")
        if phrase_id in seen:
            raise ValueError(f"duplicate requested phrase ID: {phrase_id}")
        seen.add(phrase_id)
        result.append(phrase_id)
    return result


def _part_for_row(song: MidiSong, row: dict[str, Any]) -> Part:
    if row.get("kind") == "percussion":
        part = drum_part(song)
        if not part.notes:
            raise ValueError(f"phrase {row['phrase_id']} source has no drum notes")
        return part
    part_index = row.get("part_index")
    matches = [part for part in song.parts if part.index == part_index]
    if len(matches) != 1 or matches[0].is_drum:
        raise ValueError(
            f"phrase {row['phrase_id']} references an unavailable melodic part"
        )
    part = matches[0]
    for field, actual in (
        ("channel", part.channel),
        ("program", part.program),
        ("source_track", part.track),
    ):
        if field in row and row[field] != actual:
            raise ValueError(f"phrase {row['phrase_id']} {field} differs from source MIDI")
    return part


def _render_audio(
    repeated_midi: Path,
    soundfont: Path,
    fluidsynth: Path,
    destination: Path,
    cycle_seconds: float,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="samuged-audio-") as temporary:
        raw = Path(temporary) / "rendered.wav"
        _run(
            [
                str(fluidsynth),
                "-niq",
                "-F",
                str(raw),
                "-T",
                "wav",
                "-O",
                "s24",
                "-r",
                str(SAMPLE_RATE),
                "-g",
                "0.45",
                str(soundfont),
                str(repeated_midi),
            ],
            "FluidSynth render",
        )
        rendered, sample_rate = _read_wave(raw)
    loop, details = process_steady_cycle(rendered, sample_rate, cycle_seconds)
    write_pcm24_wave(destination, loop)
    return details


def _optional_audio(
    wav_path: Path,
    *,
    make_mp3: bool,
    make_flac: bool,
    ffmpeg: Path,
) -> list[Path]:
    outputs: list[Path] = []
    if make_mp3:
        target = wav_path.with_suffix(".mp3")
        _run(
            [
                str(ffmpeg), "-v", "error", "-y", "-i", str(wav_path),
                "-map_metadata", "-1", "-codec:a", "libmp3lame", "-q:a", "2", str(target),
            ],
            "MP3 conversion",
        )
        outputs.append(target)
    if make_flac:
        target = wav_path.with_suffix(".flac")
        _run(
            [
                str(ffmpeg), "-v", "error", "-y", "-i", str(wav_path),
                "-map_metadata", "-1", "-codec:a", "flac", str(target),
            ],
            "FLAC conversion",
        )
        outputs.append(target)
    return outputs


def render_audio_loops(
    phrase_ids_path: Path,
    dataset: Path,
    source_root: Path,
    soundfont: Path,
    output: Path,
    *,
    fluidsynth: Path = Path("/opt/homebrew/bin/fluidsynth"),
    ffmpeg: Path = Path("/opt/homebrew/bin/ffmpeg"),
    make_mp3: bool = False,
    make_flac: bool = False,
) -> dict[str, Any]:
    """Render requested loops and return the deterministic root manifest."""

    phrase_ids = load_phrase_ids(phrase_ids_path)
    phrase_manifest, rows = _load_phrase_rows(dataset)
    missing = [phrase_id for phrase_id in phrase_ids if phrase_id not in rows]
    if missing:
        raise ValueError(f"requested phrase IDs are absent from manifest: {missing}")
    for path, label in (
        (soundfont, "soundfont"),
        (fluidsynth, "FluidSynth executable"),
        (ffmpeg, "FFmpeg executable"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} is unavailable: {path}")
    renderer_provenance = _renderer_provenance(fluidsynth, ffmpeg)
    output.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    for phrase_id in phrase_ids:
        row = rows[phrase_id]
        phrase_output = output / phrase_id
        phrase_output.mkdir(parents=True, exist_ok=True)
        for optional_name, requested in (("loop.mp3", make_mp3), ("loop.flac", make_flac)):
            if not requested:
                (phrase_output / optional_name).unlink(missing_ok=True)
        source_path = _resolve_source(source_root, row.get("source_path"))
        source_hash = _sha256_file(source_path)
        if source_hash != row.get("source_sha256"):
            raise ValueError(f"phrase {phrase_id} source SHA-256 mismatch")
        midi_relative = row.get("midi_path")
        if not isinstance(midi_relative, str) or not midi_relative:
            raise ValueError(f"phrase {phrase_id} has no published MIDI path")
        published_midi = phrase_manifest.parent / midi_relative
        if not published_midi.is_file() or _sha256_file(published_midi) != row.get("midi_sha256"):
            raise ValueError(f"phrase {phrase_id} published MIDI SHA-256 mismatch")

        song = load_midi(source_path, recover_invalid_keys=True)
        if song.ticks_per_beat != row.get("ticks_per_beat"):
            raise ValueError(f"phrase {phrase_id} ticks_per_beat differs from source MIDI")
        start_tick = _integer(row.get("start_tick"), "start_tick")
        part = _part_for_row(song, row)
        period = infer_loop_period(row, meter=active_meter(song, start_tick))
        notes = source_cycle_notes(part, start_tick, period.period_ticks)
        if not notes:
            raise ValueError(f"phrase {phrase_id} source cycle contains no notes")

        source_copy = phrase_output / "source.mid"
        shutil.copyfile(published_midi, source_copy)
        loop_midi = phrase_output / "loop.mid"
        export_phrase(
            song,
            part,
            notes,
            start_tick,
            start_tick + period.period_ticks,
            loop_midi,
        )
        with tempfile.TemporaryDirectory(prefix="samuged-midi-") as temporary:
            repeated_midi = Path(temporary) / "repeated.mid"
            write_repeated_midi(
                song,
                part,
                notes,
                start_tick,
                period.period_ticks,
                RENDER_REPETITIONS,
                repeated_midi,
            )
            loop_wav = phrase_output / "loop.wav"
            cycle_seconds = seconds_between(
                song, start_tick, start_tick + period.period_ticks
            )
            audio = _render_audio(
                repeated_midi, soundfont, fluidsynth, loop_wav, cycle_seconds
            )
        optional = _optional_audio(
            loop_wav,
            make_mp3=make_mp3,
            make_flac=make_flac,
            ffmpeg=ffmpeg,
        )

        note_rows = [
            {
                "start_tick": note.start,
                "end_tick": note.end,
                "relative_start_tick": note.start - start_tick,
                "relative_end_tick": note.end - start_tick,
                "pitch": note.pitch,
                "velocity": note.velocity,
            }
            for note in notes
        ]
        metadata = {
            "version": VERSION,
            "phrase_id": phrase_id,
            "kind": row.get("kind"),
            "source_path": row.get("source_path"),
            "source_sha256": source_hash,
            "published_phrase_midi_sha256": row.get("midi_sha256"),
            "source_export_policy": (
                "source.mid is the hash-verified published detector phrase export; "
                "loop.mid is rebuilt separately from source notes over the measured cycle"
            ),
            "recognition_claim": False,
            "recognition_statement": (
                "No claim is made that the phrase is recognized or named by the system."
            ),
            "cycle_start_tick": start_tick,
            "cycle_end_tick": start_tick + period.period_ticks,
            "cycle_seconds": cycle_seconds,
            "period": asdict(period),
            "part": {
                "index": part.index,
                "track": part.track,
                "channel": part.channel,
                "program": part.program,
                "name": part.name,
                "is_drum": part.is_drum,
                "percussion_merge": row.get("kind") == "percussion",
            },
            "source_note_count_used": len(notes),
            "source_notes_used": note_rows,
            "tempo_changes": [
                {"tick": tick, "microseconds_per_beat": tempo}
                for tick, tempo in _cycle_metadata(song, start_tick, period.period_ticks)[0]
            ],
            "meter_changes": [
                {"tick": tick, "numerator": numerator, "denominator": denominator}
                for tick, numerator, denominator in _cycle_metadata(
                    song, start_tick, period.period_ticks
                )[1]
            ],
            "metadata_repairs": song.metadata_repairs,
            "source_loader_warnings": song.warnings,
            "audio": audio,
        }
        metadata_path = phrase_output / "metadata.json"
        _write_json(metadata_path, metadata)
        artifact_paths = [source_copy, loop_midi, loop_wav, *optional, metadata_path]
        artifacts = [
            {
                "path": path.relative_to(output).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
            for path in artifact_paths
        ]
        hashes_path = phrase_output / "hashes.json"
        _write_json(hashes_path, {"phrase_id": phrase_id, "artifacts": artifacts})
        artifacts.append(
            {
                "path": hashes_path.relative_to(output).as_posix(),
                "bytes": hashes_path.stat().st_size,
                "sha256": _sha256_file(hashes_path),
            }
        )
        entries.append(
            {
                "phrase_id": phrase_id,
                "kind": row.get("kind"),
                "source_path": row.get("source_path"),
                "source_sha256": source_hash,
                "published_phrase_midi_sha256": row.get("midi_sha256"),
                "period_beats": period.period_beats,
                "cycle_seconds": cycle_seconds,
                "source_note_count_used": len(notes),
                "artifacts": artifacts,
            }
        )

    manifest = {
        "version": VERSION,
        "phrase_ids": phrase_ids,
        "inputs": {
            "phrase_ids_json": {
                "path": str(phrase_ids_path),
                "sha256": _sha256_file(phrase_ids_path),
            },
            "phrase_manifest": {
                "path": str(phrase_manifest),
                "sha256": _sha256_file(phrase_manifest),
            },
            "soundfont": {"path": str(soundfont), "sha256": _sha256_file(soundfont)},
        },
        "render": {
            "sample_rate_hz": SAMPLE_RATE,
            "repetitions": RENDER_REPETITIONS,
            "steady_repetition_index": STEADY_REPETITION,
            "mp3": make_mp3,
            "flac": make_flac,
        },
        "renderer_provenance": renderer_provenance,
        "entries": entries,
    }
    manifest_path = output / "manifest.json"
    _write_json(manifest_path, manifest)
    receipt_files = [
        artifact
        for entry in entries
        for artifact in entry["artifacts"]
    ] + [
        {
            "path": "manifest.json",
            "bytes": manifest_path.stat().st_size,
            "sha256": _sha256_file(manifest_path),
        }
    ]
    _write_json(
        output / "receipt.json",
        {
            "version": VERSION,
            "file_count": len(receipt_files),
            "files": receipt_files,
        },
    )
    return manifest
