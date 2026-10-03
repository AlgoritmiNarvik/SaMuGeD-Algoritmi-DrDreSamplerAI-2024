"""Build a self-contained offline HTML packet for human phrase review."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import html
import json
import math
from pathlib import Path
from typing import Iterable

from samuged.drums import drum_part
from samuged.midi import MidiSong, Note, load_midi
from samuged.phrases import skyline


PACKET_VERSION = "samuged-review-v3"
DEFAULT_SEED = "samuged-review-v1"
KINDS = ("melodic", "percussion")
SAMPLE_CONSTRAINT_FIELDS = ("source_id", "split_group", "family_id")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path} line {line_number}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path} line {line_number} must contain a JSON object")
        rows.append(row)
    return rows


def _required_text(row: dict, key: str, context: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} requires a nonempty {key}")
    return value


def _identity_value(row: dict, key: str, fallback: str) -> str:
    """Return a manifest identity field, falling back for small fixtures."""

    value = row.get(key)
    if isinstance(value, str) and value:
        return value
    return fallback


def _sampling_keys(row: dict) -> dict[str, str]:
    source_id = _required_text(row, "source_id", "phrase row")
    return {
        "source_id": source_id,
        "split_group": _identity_value(row, "split_group", source_id),
        "family_id": _identity_value(
            row, "family_id", _identity_value(row, "canonical_family_id", source_id)
        ),
    }


def sample_rows(rows: Iterable[dict], count: int, seed: str = DEFAULT_SEED) -> list[dict]:
    """Select a deterministic kind-balanced sample with provenance separation.

    A selected candidate consumes its source, original split group and canonical
    phrase family. Minimal fixtures may omit the latter two fields, in which
    case source_id is used as a stable fallback.
    """

    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 500:
        raise ValueError("count must be an integer between 1 and 500")
    if not isinstance(seed, str) or not seed:
        raise ValueError("seed must be a nonempty string")

    by_kind: dict[str, list[dict]] = {kind: [] for kind in KINDS}
    source_kinds: dict[str, set[str]] = {}
    seen_phrase_ids: set[str] = set()
    for row in rows:
        if row.get("kind") not in by_kind:
            continue
        keys = _sampling_keys(row)
        source_id = keys["source_id"]
        phrase_id = _required_text(row, "phrase_id", f"phrase row {source_id}")
        if phrase_id in seen_phrase_ids:
            raise ValueError(f"duplicate phrase_id {phrase_id}")
        seen_phrase_ids.add(phrase_id)
        by_kind[row["kind"]].append(row)
        source_kinds.setdefault(source_id, set()).add(row["kind"])

    def rank(row: dict) -> tuple[str, str]:
        keys = _sampling_keys(row)
        material = "\0".join(
            (seed, row["kind"], keys["source_id"], keys["split_group"],
             keys["family_id"], row["phrase_id"])
        )
        return sha256(material.encode("utf-8")).hexdigest(), row["phrase_id"]

    for kind in KINDS:
        # Prefer kind-exclusive sources so a melodic choice does not consume a
        # scarce percussion source, or vice versa.
        by_kind[kind].sort(
            key=lambda row: (len(source_kinds[row["source_id"]]) > 1, *rank(row))
        )

    cursors = {kind: 0 for kind in KINDS}
    used_constraints: dict[str, set[str]] = {
        field: set() for field in SAMPLE_CONSTRAINT_FIELDS
    }
    selected: list[dict] = []

    def take(kind: str) -> dict | None:
        rows_for_kind = by_kind[kind]
        while cursors[kind] < len(rows_for_kind):
            row = rows_for_kind[cursors[kind]]
            cursors[kind] += 1
            keys = _sampling_keys(row)
            if all(keys[field] not in used_constraints[field] for field in SAMPLE_CONSTRAINT_FIELDS):
                return row
        return None

    for index in range(count):
        preferred = KINDS[index % len(KINDS)]
        row = take(preferred)
        if row is None:
            row = take(KINDS[1 - KINDS.index(preferred)])
        if row is None:
            break
        selected.append(row)
        keys = _sampling_keys(row)
        for field in SAMPLE_CONSTRAINT_FIELDS:
            used_constraints[field].add(keys[field])
    return selected


def _source_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("source_path must be a nonempty string")
    candidate = (root / relative).resolve(strict=True)
    if not candidate.is_relative_to(root):
        raise ValueError(f"source_path escapes the source corpus: {relative!r}")
    if not candidate.is_file():
        raise ValueError(f"source_path is not a file: {relative!r}")
    return candidate


def _note_stream(song: MidiSong, row: dict, merge_beats: float = 1 / 24) -> list[Note]:
    if row["kind"] == "percussion":
        return drum_part(song).notes
    part_index = row.get("part_index")
    matches = [part for part in song.parts if part.index == part_index]
    if len(matches) != 1 or matches[0].is_drum:
        raise ValueError(
            f"phrase {row['phrase_id']} references an unavailable melodic part"
        )
    return skyline(matches[0], song.ticks_per_beat, merge_beats)


def _integer(value: object, field: str, phrase_id: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"phrase {phrase_id} has invalid {field}")
    return value


def _seconds_between(song: MidiSong, start: int, end: int) -> float:
    """Integrate the actual source tempo map over a tick interval."""
    tempo, cursor, seconds = 500_000, start, 0.0
    for tick, value in song.tempos:
        if tick <= start:
            tempo = value
        elif tick < end:
            seconds += (tick-cursor)*tempo/(song.ticks_per_beat*1_000_000)
            cursor, tempo = tick, value
        else:
            break
    return seconds + (end-cursor)*tempo/(song.ticks_per_beat*1_000_000)


def _snippet(
    stream: list[Note], start: int, end: int, song: MidiSong, label: str,
    phrase_id: str, note_index: int | None = None, note_count: int | None = None,
) -> dict:
    if end <= start:
        raise ValueError(f"phrase {phrase_id} has a nonpositive {label} interval")
    if note_index is None:
        selected = [note for note in stream if start <= note.start < end]
    else:
        selected = stream[note_index:note_index+note_count]
        if (
            len(selected) != note_count
            or not selected
            or any(not start <= note.start < end for note in selected)
            or min(note.start for note in selected) != start
            or max(note.end for note in selected) != end
        ):
            raise ValueError(f"phrase {phrase_id} has invalid {label} note coordinates")
    if not selected:
        raise ValueError(f"phrase {phrase_id} has no source notes in {label}")
    return {
        "label": label,
        "start_tick": start,
        "end_tick": end,
        "duration_beats": (end - start) / song.ticks_per_beat,
        "duration_seconds": _seconds_between(song, start, end),
        "notes": [
            {
                "pitch": note.pitch,
                "onset_beats": (note.start - start) / song.ticks_per_beat,
                "duration_beats": (min(note.end, end) - note.start) / song.ticks_per_beat,
                "onset_seconds": _seconds_between(song, start, note.start),
                "duration_seconds": _seconds_between(song, note.start, min(note.end, end)),
                "velocity": note.velocity,
            }
            for note in selected
        ],
    }


def _review_candidate(
    row: dict,
    source_record: dict,
    source_root: Path,
    review_id: str,
    song_cache: dict[str, MidiSong],
) -> dict:
    phrase_id = row["phrase_id"]
    source_id = row["source_id"]
    record_hash = _required_text(source_record, "source_sha256", f"source {source_id}")
    row_hash = _required_text(row, "source_sha256", f"phrase {phrase_id}")
    if record_hash != row_hash:
        raise ValueError(f"phrase {phrase_id} and source manifest hashes disagree")
    relative = _required_text(source_record, "source_path", f"source {source_id}")
    if row.get("source_path") != relative:
        raise ValueError(f"phrase {phrase_id} and source manifest paths disagree")
    phrase_split_group = row.get("split_group")
    source_split_group = source_record.get("split_group")
    if (
        isinstance(phrase_split_group, str)
        and phrase_split_group
        and isinstance(source_split_group, str)
        and source_split_group
        and phrase_split_group != source_split_group
    ):
        raise ValueError(f"phrase {phrase_id} and source manifest split groups disagree")
    split_group = _identity_value(
        row,
        "split_group",
        _identity_value(source_record, "split_group", source_id),
    )
    family_id = _identity_value(
        row,
        "family_id",
        _identity_value(row, "canonical_family_id", source_id),
    )
    path = _source_path(source_root, relative)
    actual_hash = _file_sha256(path)
    if actual_hash != record_hash:
        raise ValueError(f"source hash mismatch for {relative!r}")

    declared_repairs = source_record.get("metadata_repairs")
    recovery_opt_in = "metadata_repairs" in source_record
    if recovery_opt_in and not isinstance(declared_repairs, list):
        raise ValueError(f"source {source_id} has invalid metadata_repairs")
    song = song_cache.get(source_id)
    if song is None:
        song = (
            load_midi(path, recover_invalid_keys=True)
            if recovery_opt_in
            else load_midi(path)
        )
        actual_repairs = getattr(song, "metadata_repairs", [])
        if actual_repairs != (declared_repairs if recovery_opt_in else []):
            raise ValueError(f"source {source_id} metadata repair receipt mismatch")
        song_cache[source_id] = song
    elif getattr(song, "metadata_repairs", []) != (declared_repairs if recovery_opt_in else []):
        raise ValueError(f"source {source_id} metadata repair receipt mismatch")
    stream = _note_stream(song, row, source_record.get("config", {}).get("onset_merge_beats", 1 / 24))
    start = _integer(row.get("start_tick"), "start_tick", phrase_id)
    end = _integer(row.get("end_tick"), "end_tick", phrase_id)
    occurrences = row.get("occurrences")
    if not isinstance(occurrences, list) or len(occurrences) < 2:
        raise ValueError(f"phrase {phrase_id} requires at least two occurrences")

    melodic = row["kind"] == "melodic"
    count = _integer(row.get("note_count"), "note_count", phrase_id) if melodic else None
    note_index = _integer(row.get("prototype_note_index"), "prototype_note_index", phrase_id) if melodic else None
    snippets = [_snippet(stream, start, end, song, "Prototype", phrase_id, note_index, count)]
    shown_intervals = {(start, end)}
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            raise ValueError(f"phrase {phrase_id} has an invalid occurrence")
        occurrence_start = _integer(
            occurrence.get("start_tick"), "occurrence start_tick", phrase_id
        )
        occurrence_end = _integer(
            occurrence.get("end_tick"), "occurrence end_tick", phrase_id
        )
        interval = (occurrence_start, occurrence_end)
        if interval in shown_intervals:
            continue
        snippets.append(
            _snippet(
                stream,
                occurrence_start,
                occurrence_end,
                song,
                f"Other occurrence {len(snippets)}",
                phrase_id,
                _integer(occurrence.get("note_index"), "occurrence note_index", phrase_id) if melodic else None,
                _integer(occurrence.get("note_count", count), "occurrence note_count", phrase_id) if melodic else None,
            )
        )
        shown_intervals.add(interval)
        if len(snippets) == 3:
            break
    if len(snippets) < 2:
        raise ValueError(f"phrase {phrase_id} requires a distinct other occurrence")

    score = row.get("recurrence_score")
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
    ):
        score = None
    return {
        "review_id": review_id,
        "candidate_id": phrase_id,
        "kind": row["kind"],
        "source_id": source_id,
        "source_sha256": record_hash,
        "source_path": relative,
        "split_group": split_group,
        "family_id": family_id,
        "metadata_repairs": list(getattr(song, "metadata_repairs", [])),
        "recurrence_score": score,
        "snippets": snippets,
    }


def script_safe_json(value: object) -> str:
    """Serialize JSON that cannot terminate a script raw-text element."""

    text = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:light;--ink:#18202b;--muted:#596579;--line:#cad2dd;--paper:#f4f6f8;--card:#fff;--blue:#2f65a7;--orange:#b85c28;--green:#25735a}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:28px 20px 80px}h1{margin:0 0 8px;font-size:28px}h2{font-size:20px}.notice{padding:12px 14px;border-left:4px solid var(--orange);background:#fff7ef}.toolbar{display:flex;gap:10px;position:sticky;top:0;background:rgba(244,246,248,.96);padding:12px 0;z-index:2}.card{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:18px;margin:18px 0;box-shadow:0 2px 7px #18202b10}.badge{display:inline-block;padding:2px 8px;border-radius:999px;background:#e7edf6;color:#294b76;margin-left:8px}.snippets{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}.snippet{border:1px solid var(--line);padding:10px;border-radius:7px}.roll{width:100%;height:150px;background:#f8fafc;border:1px solid #dde3eb}.controls,.ratings{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}button{border:1px solid #9aa7b8;border-radius:5px;background:white;padding:7px 11px;cursor:pointer}button.primary{background:var(--blue);color:white;border-color:var(--blue)}fieldset{border:1px solid var(--line);border-radius:6px;margin:12px 0;padding:9px 12px}legend{font-weight:650}label{margin-right:12px;white-space:nowrap}textarea{width:100%;min-height:64px;border:1px solid #9aa7b8;border-radius:5px;padding:7px}.reveal{margin-top:10px;padding:9px;background:#f2f5f8;overflow-wrap:anywhere}.hidden{display:none}.muted{color:var(--muted);font-size:13px}.pitch-label{font-size:9px;fill:#4f5b6c}.grid{stroke:#dfe5ec;stroke-width:1}.note-melodic{fill:var(--blue)}.note-percussion{fill:var(--orange)}
</style>
</head>
<body><main>
<h1>SaMuGeD recurring phrase review</h1>
<p class="notice"><strong>Listening disclosure.</strong> Playback is a simple browser synthesis of symbolic MIDI notes. It is not source audio and does not reproduce the original instruments, production or mix. Timing follows the source MIDI tempo map.</p>
<p>Review each blind ID from the piano rolls and synthesized snippets. “Same phrase” asks about musical recurrence only. It does not ask whether a phrase is memorable or an earworm. This file makes no network requests. Ratings are downloaded only to your computer.</p>
<div class="toolbar"><label>Annotator ID <input id="annotator-id" type="text" autocomplete="off" placeholder="for example A1"></label><button id="stop-all">Stop playback</button><button class="primary" id="export">Export ratings JSON</button><span id="status" class="muted" role="status" aria-live="polite"></span></div>
<details id="export-fallback" hidden><summary>View exported JSON if your browser blocks the download</summary><textarea id="ratings-json" aria-label="Exported ratings JSON" readonly></textarea></details>
<section id="cards"></section>
</main>
<script id="review-data" type="application/json">__PACKET_JSON__</script>
<script>
'use strict';
const packet=JSON.parse(document.getElementById('review-data').textContent);
const cards=document.getElementById('cards');
const NS='http://www.w3.org/2000/svg';
let audioContext=null;
let activeNodes=[];
let stopTimer=null;
let playbackToken=0;

function element(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node}
function stopPlayback(message){playbackToken++;if(stopTimer!==null){clearTimeout(stopTimer);stopTimer=null}for(const node of activeNodes){try{node.stop()}catch(_error){}try{node.disconnect()}catch(_error){}}activeNodes=[];if(typeof message==='string')document.getElementById('status').textContent=message}
document.getElementById('stop-all').addEventListener('click',()=>stopPlayback('Playback stopped.'));

function pianoRoll(svg,snippet,kind){
  const notes=snippet.notes;const width=640,height=150,pad=34;svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
  const pitches=[...new Set(notes.map(note=>note.pitch))].sort((a,b)=>b-a);const low=Math.min(...pitches),high=Math.max(...pitches);const lanes=kind==='percussion'?pitches.length:Math.max(1,high-low+1);
  const beatStep=Math.max(1,Math.ceil(snippet.duration_beats/32));for(let beat=0;beat<=Math.ceil(snippet.duration_beats);beat+=beatStep){const line=document.createElementNS(NS,'line');const x=pad+(width-pad-4)*beat/snippet.duration_beats;line.setAttribute('x1',x);line.setAttribute('x2',x);line.setAttribute('y1','0');line.setAttribute('y2',height);line.setAttribute('class','grid');svg.append(line)}
  for(const pitch of pitches){const lane=kind==='percussion'?pitches.indexOf(pitch):high-pitch;const text=document.createElementNS(NS,'text');text.setAttribute('x','2');text.setAttribute('y',5+(lane+.7)*(height-8)/lanes);text.setAttribute('class','pitch-label');text.textContent=String(pitch);svg.append(text)}
  for(const note of notes){const rect=document.createElementNS(NS,'rect');const lane=kind==='percussion'?pitches.indexOf(note.pitch):high-note.pitch;const x=pad+(width-pad-4)*note.onset_beats/snippet.duration_beats;const y=4+lane*(height-8)/lanes;const w=Math.max(2,(width-pad-4)*Math.min(note.duration_beats,snippet.duration_beats-note.onset_beats)/snippet.duration_beats);rect.setAttribute('x',x);rect.setAttribute('y',y);rect.setAttribute('width',w);rect.setAttribute('height',Math.max(2,(height-8)/lanes-1));rect.setAttribute('class',kind==='percussion'?'note-percussion':'note-melodic');svg.append(rect)}
}

async function playSnippet(snippet,kind,reviewId){
  stopPlayback();const token=playbackToken;document.getElementById('status').textContent='Starting playback…';audioContext=audioContext||new AudioContext();await audioContext.resume();if(token!==playbackToken)return;const base=audioContext.currentTime+.04;let latest=snippet.duration_seconds;
  document.getElementById('status').textContent=`Playing ${reviewId}: ${snippet.label}.`;
  for(const note of snippet.notes){const when=base+note.onset_seconds;const duration=Math.max(.035,note.duration_seconds);latest=Math.max(latest,note.onset_seconds+duration);
    const gain=audioContext.createGain();gain.gain.setValueAtTime(Math.min(.14,.025+note.velocity/1100),when);gain.gain.exponentialRampToValueAtTime(.0001,when+duration);gain.connect(audioContext.destination);
    if(kind==='percussion'){const frames=Math.max(1,Math.floor(audioContext.sampleRate*Math.min(.12,duration)));const buffer=audioContext.createBuffer(1,frames,audioContext.sampleRate);const channel=buffer.getChannelData(0);for(let i=0;i<frames;i++)channel[i]=(Math.random()*2-1)*(1-i/frames);const source=audioContext.createBufferSource();const filter=audioContext.createBiquadFilter();filter.type='bandpass';filter.frequency.value=100+note.pitch*18;source.buffer=buffer;source.connect(filter);filter.connect(gain);source.start(when);source.stop(when+duration);activeNodes.push(source,gain,filter)}
    else{const oscillator=audioContext.createOscillator();oscillator.type='sine';oscillator.frequency.value=440*Math.pow(2,(note.pitch-69)/12);oscillator.connect(gain);oscillator.start(when);oscillator.stop(when+duration);activeNodes.push(oscillator,gain)}
  }
  stopTimer=setTimeout(()=>stopPlayback('Playback finished.'),(latest+.2)*1000);
}

function radioGroup(card,title,key,values){const field=element('fieldset');field.append(element('legend',title));for(const value of values){const label=element('label');const input=document.createElement('input');input.type='radio';input.name=`${card.dataset.reviewId}-${key}`;input.value=value;label.append(input,document.createTextNode(` ${value}`));field.append(label)}return field}

for(const candidate of packet.candidates){
  const card=element('article',undefined,'card');card.dataset.reviewId=candidate.review_id;card.dataset.candidateId=candidate.candidate_id;
  const heading=element('h2',candidate.review_id);heading.append(element('span',candidate.kind,'badge'));card.append(heading);
  const snippetGrid=element('div',undefined,'snippets');
  for(const snippet of candidate.snippets){const panel=element('section',undefined,'snippet');panel.append(element('strong',snippet.label));const svg=document.createElementNS(NS,'svg');svg.setAttribute('class','roll');svg.setAttribute('role','img');svg.setAttribute('aria-label',`${snippet.label} piano roll`);pianoRoll(svg,snippet,candidate.kind);panel.append(svg);const controls=element('div',undefined,'controls');const play=element('button','Play synthesis');play.type='button';play.addEventListener('click',()=>playSnippet(snippet,candidate.kind,candidate.review_id).catch(()=>stopPlayback('Playback unavailable. Try a browser with Web Audio support.')));controls.append(play);panel.append(controls);snippetGrid.append(panel)}
  card.append(snippetGrid);
  card.append(radioGroup(card,'Same musical phrase?','same_phrase',['yes','no','uncertain']));
  card.append(radioGroup(card,'Boundary quality','boundary',['good','partial','poor']));
  card.append(radioGroup(card,'Musical role','role',['melody','accompaniment','percussion','uncertain']));
  card.append(radioGroup(card,'Perceptual salience','salience',['high','medium','low','uncertain']));
  const notes=element('textarea');notes.setAttribute('aria-label','Free notes');notes.placeholder='Optional notes';notes.dataset.field='notes';card.append(notes);
  const revealButton=element('button','Reveal source and detector score');revealButton.type='button';const reveal=element('div',undefined,'reveal hidden');reveal.append(element('div',`Source: ${candidate.source_path}`),element('div',`Detector score: ${candidate.recurrence_score===null?'unavailable':candidate.recurrence_score}`));revealButton.addEventListener('click',()=>{reveal.classList.toggle('hidden');revealButton.textContent=reveal.classList.contains('hidden')?'Reveal source and detector score':'Hide source and detector score'});card.append(revealButton,reveal);cards.append(card);
}

function checked(card,key){const node=card.querySelector(`input[name="${card.dataset.reviewId}-${key}"]:checked`);return node?node.value:null}
document.getElementById('export').addEventListener('click',()=>{
  stopPlayback();const reviews=[];for(const card of cards.querySelectorAll('.card')){const candidate=packet.candidates.find(item=>item.review_id===card.dataset.reviewId);reviews.push({review_id:candidate.review_id,candidate_id:candidate.candidate_id,kind:candidate.kind,source_id:candidate.source_id,source_sha256:candidate.source_sha256,source_path:candidate.source_path,split_group:candidate.split_group,family_id:candidate.family_id,metadata_repairs:candidate.metadata_repairs,same_phrase:checked(card,'same_phrase'),boundary_quality:checked(card,'boundary'),role:checked(card,'role'),salience:checked(card,'salience'),notes:card.querySelector('[data-field="notes"]').value})}
  const annotatorId=document.getElementById('annotator-id').value.trim()||null;const output={schema_version:packet.schema_version,annotator_id:annotatorId,packet_config:packet.config,reviews};const serialized=JSON.stringify(output,null,2)+'\n';document.getElementById('ratings-json').value=serialized;document.getElementById('export-fallback').hidden=false;const blob=new Blob([serialized],{type:'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=`samuged-ratings-${packet.config.seed_digest.slice(0,10)}.json`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);document.getElementById('status').textContent=`Prepared ${reviews.length} review rows for local download.`;
});
</script>
</body></html>
'''


def build_packet(
    source: Path,
    dataset: Path,
    output: Path,
    *,
    count: int = 40,
    seed: str = DEFAULT_SEED,
) -> dict:
    source = source.resolve(strict=True)
    dataset = dataset.resolve(strict=True)
    if not source.is_dir() or not dataset.is_dir():
        raise ValueError("source and dataset must be directories")
    if output.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("output must use an .html or .htm extension")
    sources_path = dataset / "sources.jsonl"
    phrases_path = dataset / "phrases.jsonl"
    source_rows = _read_jsonl(sources_path)
    phrase_rows = _read_jsonl(phrases_path)
    sources: dict[str, dict] = {}
    for row in source_rows:
        source_id = _required_text(row, "source_id", "source row")
        if source_id in sources:
            raise ValueError(f"duplicate source_id {source_id}")
        sources[source_id] = row

    selected = sample_rows(phrase_rows, count, seed)
    if not selected:
        raise ValueError("phrase manifest contains no melodic or percussion candidates")
    song_cache: dict[str, MidiSong] = {}
    candidates = []
    for index, row in enumerate(selected, 1):
        source_id = row["source_id"]
        if source_id not in sources:
            raise ValueError(f"phrase {row['phrase_id']} references unknown source {source_id}")
        candidates.append(
            _review_candidate(
                row,
                sources[source_id],
                source,
                f"R{index:03d}",
                song_cache,
            )
        )

    packet = {
        "schema_version": PACKET_VERSION,
        "config": {
            "requested_count": count,
            "selected_count": len(candidates),
            "eligible_kind_counts": dict(
                Counter(row["kind"] for row in phrase_rows if row.get("kind") in KINDS)
            ),
            "selected_kind_counts": dict(Counter(row["kind"] for row in selected)),
            "seed": seed,
            "seed_digest": sha256(seed.encode("utf-8")).hexdigest(),
            "selection": "deterministic hash rank, alternating melodic and percussion when available",
            "sampling_constraints": {
                "at_most_one_per": list(SAMPLE_CONSTRAINT_FIELDS),
                "missing_split_group_or_family_fallback": "source_id",
                "kind_balance": "round_robin_preference_with_constraint_aware_fallback",
            },
            "metadata_repair_policy": "strict parsing unless the source manifest carries an exact metadata_repairs receipt",
            "source_manifest_sha256": _file_sha256(sources_path),
            "phrase_manifest_sha256": _file_sha256(phrases_path),
            "excerpt_policy": "source MIDI prototype and up to two other distinct recorded intervals, exact melodic note indices, source tempo map",
        },
        "candidates": candidates,
    }
    rendered = _HTML_TEMPLATE.replace(
        "__TITLE__", html.escape("SaMuGeD recurring phrase review", quote=True)
    ).replace("__PACKET_JSON__", script_safe_json(packet))
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="source MIDI corpus")
    parser.add_argument("--dataset", required=True, type=Path, help="dataset output directory")
    parser.add_argument("--output", required=True, type=Path, help="HTML packet path")
    parser.add_argument("--count", type=int, default=40, help="maximum candidates (default: 40)")
    parser.add_argument("--seed", default=DEFAULT_SEED, help="exact deterministic sampling seed")
    args = parser.parse_args()
    packet = build_packet(
        args.source,
        args.dataset,
        args.output,
        count=args.count,
        seed=args.seed,
    )
    print(
        f"wrote {args.output.resolve()} with {packet['config']['selected_count']} candidates"
    )


if __name__ == "__main__":
    main()
