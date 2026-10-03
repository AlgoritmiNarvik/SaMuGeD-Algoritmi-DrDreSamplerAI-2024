"""Create a self-contained, offline, blinded paired listening packet.

The packet compares the top ranked candidate of one kind for the same source in
two already audited dataset directories.  It is a convenience listening tool,
not a physical blinding mechanism: the reversible mapping is written beside the
HTML rather than embedded in the rendered controls.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

try:  # Works both as ``python scripts/...`` and as an imported module in tests.
    from scripts.make_review import (
        DEFAULT_SEED,
        KINDS,
        _file_sha256,
        _read_jsonl,
        _review_candidate,
        _required_text,
        _source_path,
        script_safe_json,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI entrypoint.
    from make_review import (  # type: ignore[no-redef]
        DEFAULT_SEED,
        KINDS,
        _file_sha256,
        _read_jsonl,
        _review_candidate,
        _required_text,
        _source_path,
        script_safe_json,
    )

PACKET_VERSION = "samuged-paired-review-v1"
RATINGS_VERSION = "samuged-paired-review-ratings-v1"
PREFERENCES = ("A", "B", "tie", "uncertain")
CODE_PATHS = (
    "scripts/make_paired_review.py",
    "scripts/make_review.py",
    "samuged/__init__.py",
    "samuged/drums.py",
    "samuged/metadata_recovery.py",
    "samuged/midi.py",
    "samuged/phrases.py",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _json_hash(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _hash_if_file(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"missing required artifact: {path}")
    return _file_sha256(path)


def _artifact_hashes(dataset: Path) -> dict[str, str]:
    return {name: _hash_if_file(dataset / name) for name in ("sources.jsonl", "phrases.jsonl", "summary.json", "build_config.json", "audit.json")}


def _code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    return {relative: _hash_if_file(root / relative) for relative in CODE_PATHS}


def _validate_variant(dataset: Path) -> dict:
    dataset = dataset.resolve(strict=True)
    if not dataset.is_dir():
        raise ValueError(f"dataset is not a directory: {dataset}")
    artifacts = _artifact_hashes(dataset)
    audit = _read_json(dataset / "audit.json")
    summary = _read_json(dataset / "summary.json")
    build = _read_json(dataset / "build_config.json")
    if audit.get("passed") is not True or audit.get("failure_count") != 0 or audit.get("failures") != []:
        raise ValueError(f"audit is not a zero-failure pass: {dataset}")
    for key, filename in (("source_manifest_sha256", "sources.jsonl"), ("phrase_manifest_sha256", "phrases.jsonl"), ("summary_sha256", "summary.json"), ("build_config_sha256", "build_config.json")):
        if audit.get(key) != artifacts[filename]:
            raise ValueError(f"audit {key} is stale for {dataset}")
    for key in ("run_key", "source_manifest_sha256", "phrase_manifest_sha256"):
        if audit.get(key) != summary.get(key):
            raise ValueError(f"audit and summary disagree on {key}: {dataset}")
    if audit.get("source_files") != summary.get("source_files"):
        raise ValueError(f"audit and summary disagree on source_files: {dataset}")
    scope = "full" if audit.get("full_source_coverage_required") is True else "pilot"
    try:
        source_rows = _read_jsonl(dataset / "sources.jsonl")
        phrase_rows = _read_jsonl(dataset / "phrases.jsonl")
    except UnicodeError as exc:
        raise ValueError(f"manifest is not valid UTF-8 in {dataset}: {exc}") from exc
    sources: dict[str, dict] = {}
    for row in source_rows:
        source_id = _required_text(row, "source_id", "source row")
        if source_id in sources:
            raise ValueError(f"duplicate source_id {source_id} in {dataset}")
        sources[source_id] = row
    phrases: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for row in phrase_rows:
        phrase_id = _required_text(row, "phrase_id", "phrase row")
        if phrase_id in seen:
            raise ValueError(f"duplicate phrase_id {phrase_id} in {dataset}")
        seen.add(phrase_id)
        source_id = _required_text(row, "source_id", f"phrase {phrase_id}")
        if source_id not in sources:
            raise ValueError(f"phrase {phrase_id} references unknown source {source_id}")
        if row.get("kind") in KINDS:
            phrases.setdefault(source_id, []).append(row)
    if _artifact_hashes(dataset) != artifacts:
        raise ValueError(f"dataset artifacts changed while being read: {dataset}")
    return {
        "path": dataset,
        "scope": scope,
        "audit": audit,
        "summary": summary,
        "build": build,
        "artifacts": artifacts,
        "sources": sources,
        "phrases": phrases,
    }


def _top_row(rows: list[dict], kind: str) -> dict | None:
    eligible = [row for row in rows if row.get("kind") == kind]
    if not eligible:
        return None
    def rank(row: dict) -> tuple[int, float, str]:
        value = row.get("rank_in_file")
        rank_value = value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else 10**9
        score = row.get("recurrence_score")
        score_value = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score) else float("-inf")
        return rank_value, -score_value, str(row.get("phrase_id", ""))
    return min(eligible, key=rank)


def _source_key(seed: str, source: dict) -> str:
    return sha256((seed + "\0" + source["source_id"] + "\0" + source["source_sha256"]).encode()).hexdigest()


def _side_orders(seed: str, selected: list[dict]) -> dict[str, str]:
    desired_a = (len(selected) + 1) // 2
    ranked = sorted(selected, key=lambda pair: sha256((seed + "\0side\0" + pair["source_sha256"]).encode()).hexdigest())
    a_ids = {pair["review_id"] for pair in ranked[:desired_a]}
    return {pair["review_id"]: ("AB" if pair["review_id"] in a_ids else "BA") for pair in selected}


def _candidate_core(candidate: dict) -> dict:
    """Return exactly the candidate evidence rendered to a reviewer."""
    return {key: candidate.get(key) for key in ("kind", "snippets", "tempo_map")}


def _tempo_map(song: Any) -> list[dict[str, int]]:
    return [{"tick": int(tick), "microseconds_per_beat": int(tempo)} for tick, tempo in getattr(song, "tempos", [])]


def _make_html(packet: dict) -> str:
    data = script_safe_json(packet)
    return _HTML.replace("__PACKET__", data)


def validate_ratings(payload: dict, packet: dict) -> dict:
    """Validate an export without assigning or inferring any human ratings."""
    if not isinstance(payload, dict) or payload.get("schema_version") != RATINGS_VERSION:
        raise ValueError("unsupported ratings schema")
    expected_packet_hash = packet.get("packet_sha256")
    body = dict(packet)
    actual_packet_hash = body.pop("packet_sha256", None)
    if actual_packet_hash != expected_packet_hash or _json_hash(body) != expected_packet_hash:
        raise ValueError("packet hash mismatch")
    if payload.get("packet_sha256") != expected_packet_hash:
        raise ValueError("ratings packet hash mismatch")
    annotator_id = payload.get("annotator_id")
    if annotator_id is not None and not isinstance(annotator_id, str):
        raise ValueError("annotator_id must be string or null")
    ratings = payload.get("ratings")
    if not isinstance(ratings, list):
        raise ValueError("ratings must be a list")
    expected = {pair["review_id"]: pair for pair in packet.get("pairs", [])}
    if len(ratings) != len(expected):
        raise ValueError("ratings must contain exactly one row per pair")
    seen: set[str] = set()
    for row in ratings:
        if not isinstance(row, dict):
            raise ValueError("rating row must be an object")
        review_id = row.get("review_id")
        if review_id in seen or review_id not in expected:
            raise ValueError(f"unknown or duplicate review_id: {review_id!r}")
        seen.add(review_id)
        if row.get("preference") is not None and row.get("preference") not in PREFERENCES:
            raise ValueError(f"invalid preference for {review_id}")
        notes = row.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise ValueError(f"notes for {review_id} must be string or null")
        if row.get("candidate_ids") != expected[review_id]["candidate_ids"]:
            raise ValueError(f"candidate binding mismatch for {review_id}")
    if seen != set(expected):
        raise ValueError("ratings are missing pair rows")
    return {"row_count": len(ratings), "rated_count": sum(row.get("preference") is not None for row in ratings)}


def build_packet(source: Path, left_dataset: Path, right_dataset: Path, output: Path, *, count: int = 40, kind: str = "melodic", seed: str = DEFAULT_SEED) -> dict:
    if kind not in KINDS:
        raise ValueError("kind must be melodic or percussion")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 500:
        raise ValueError("count must be an integer between 1 and 500")
    if not isinstance(seed, str) or not seed:
        raise ValueError("seed must be a nonempty string")
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("source must be a directory")
    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("output must be a new or empty directory")
    left_variant = _validate_variant(left_dataset)
    right_variant = _validate_variant(right_dataset)
    common = []
    for source_id in sorted(set(left_variant["sources"]) & set(right_variant["sources"])):
        ls, rs = left_variant["sources"][source_id], right_variant["sources"][source_id]
        if ls.get("source_sha256") != rs.get("source_sha256") or ls.get("source_path") != rs.get("source_path"):
            raise ValueError(f"source identity mismatch for {source_id}")
        if ls.get("split_group") != rs.get("split_group"):
            raise ValueError(f"split_group mismatch for {source_id}")
        if ls.get("metadata_repairs", []) != rs.get("metadata_repairs", []):
            raise ValueError(f"metadata repair mismatch for {source_id}")
        lr, rr = _top_row(left_variant["phrases"].get(source_id, []), kind), _top_row(right_variant["phrases"].get(source_id, []), kind)
        if lr is not None and rr is not None:
            common.append((source_id, ls, rs, lr, rr))
    common.sort(key=lambda item: _source_key(seed, item[1]))
    chosen: list[tuple] = []
    used_groups: set[str] = set()
    for item in common:
        group = item[1].get("split_group") or item[0]
        if group in used_groups:
            continue
        chosen.append(item)
        used_groups.add(group)
        if len(chosen) == count:
            break
    if not chosen:
        raise ValueError(f"no common {kind} source candidates")
    if len(chosen) < count:
        raise ValueError(f"only {len(chosen)} common sources satisfy the requested {count}")
    song_cache: dict[str, Any] = {}
    pair_data: list[dict] = []
    mapping: list[dict] = []
    for index, (source_id, ls, rs, lr, rr) in enumerate(chosen, 1):
        review_id = f"P{index:03d}"
        lc = _review_candidate(lr, ls, source, review_id + "-L", song_cache)
        rc = _review_candidate(rr, rs, source, review_id + "-R", song_cache)
        lc["tempo_map"] = _tempo_map(song_cache[source_id])
        rc["tempo_map"] = _tempo_map(song_cache[source_id])
        pair_data.append({"review_id": review_id, "source_sha256": ls["source_sha256"], "left": lc, "right": rc})
        mapping.append({"review_id": review_id, "source_id": source_id, "source_path": ls["source_path"], "source_sha256": ls["source_sha256"], "split_group": ls.get("split_group") or source_id, "left_candidate_id": lr["phrase_id"], "right_candidate_id": rr["phrase_id"], "metadata_repairs": ls.get("metadata_repairs", []), "identical": _json_hash(_candidate_core(lc)) == _json_hash(_candidate_core(rc))})
    orders = _side_orders(seed, pair_data)
    pairs: list[dict] = []
    for item, map_row in zip(pair_data, mapping):
        left_candidate, right_candidate = item["left"], item["right"]
        if orders[item["review_id"]] == "AB":
            alternatives = {"A": left_candidate, "B": right_candidate}
            candidate_ids = {"A": left_candidate["candidate_id"], "B": right_candidate["candidate_id"]}
        else:
            alternatives = {"A": right_candidate, "B": left_candidate}
            candidate_ids = {"A": right_candidate["candidate_id"], "B": left_candidate["candidate_id"]}
        view = {}
        for side, candidate in alternatives.items():
            view[side] = {"snippets": candidate["snippets"], "tempo_map": candidate["tempo_map"], "kind": kind}
        pairs.append({"review_id": item["review_id"], "alternatives": view, "candidate_ids": candidate_ids})
        map_row["side_order"] = orders[item["review_id"]]
    body = {
        "schema_version": PACKET_VERSION,
        "config": {"requested_count": count, "selected_count": len(pairs), "kind": kind, "seed": seed, "scope": {"left": left_variant["scope"], "right": right_variant["scope"]}, "selection": "common source IDs, seeded source hash order, one top-ranked candidate per source and kind, one source per split_group", "top_one_ranking": "lowest rank_in_file, then highest recurrence_score, then phrase_id", "identical_pair_count": sum(row["identical"] for row in mapping), "identical_pair_definition": "byte-equivalent rendered kind, source-derived snippets and tempo map", "source_context": "not included; no safe context excerpt helper was available", "playback_synthesis": "source-tempo oscillator for melody; deterministic pitch-filtered noise approximation for percussion"},
        "pairs": pairs,
        "packet_sha256": "",
    }
    body_for_hash = dict(body)
    body_for_hash.pop("packet_sha256")
    packet_hash = _json_hash(body_for_hash)
    body["packet_sha256"] = packet_hash
    mapping_doc = {"schema_version": PACKET_VERSION, "packet_sha256": packet_hash, "pairs": mapping}
    for variant in (left_variant, right_variant):
        if _artifact_hashes(variant["path"]) != variant["artifacts"]:
            raise ValueError(f"dataset artifacts changed while building packet: {variant['path']}")
    selected_sources = []
    for row in mapping:
        path = _source_path(source, row["source_path"])
        if _file_sha256(path) != row["source_sha256"]:
            raise ValueError(f"source changed while building packet: {row['source_path']}")
        selected_sources.append({"source_id": row["source_id"], "source_path": row["source_path"], "source_sha256": row["source_sha256"], "source_bytes": path.stat().st_size, "metadata_repairs": row["metadata_repairs"]})
    code_hashes = _code_hashes()
    input_manifest = {"schema_version": PACKET_VERSION, "packet_sha256": packet_hash, "script_sha256": code_hashes["scripts/make_paired_review.py"], "code_sha256": code_hashes, "source_root": str(source), "variants": {"left": {"dataset": str(left_variant["path"]), "scope": left_variant["scope"], "algorithm": left_variant["build"].get("algorithm"), "artifacts": left_variant["artifacts"]}, "right": {"dataset": str(right_variant["path"]), "scope": right_variant["scope"], "algorithm": right_variant["build"].get("algorithm"), "artifacts": right_variant["artifacts"]}}, "selected_sources": selected_sources}
    output.mkdir(parents=True, exist_ok=True)
    (output / "review.html").write_text(_make_html(body), encoding="utf-8")
    (output / "blind_mapping.json").write_bytes(_canonical(mapping_doc) + b"\n")
    (output / "input_manifest.json").write_bytes(_canonical(input_manifest) + b"\n")
    receipt = {"schema_version": PACKET_VERSION, "ratings_schema_version": RATINGS_VERSION, "status": "complete", "packet_sha256": packet_hash, "config": body["config"], "artifacts": {name: _file_sha256(output / name) for name in ("review.html", "blind_mapping.json", "input_manifest.json")}}
    (output / "packet_receipt.json").write_bytes(_canonical(receipt) + b"\n")
    return {"packet": body, "mapping": mapping_doc, "input_manifest": input_manifest, "receipt": receipt}


_HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Paired listening review</title><style>
:root{color-scheme:light;--ink:#17212b;--muted:#5d6a78;--line:#c7d0da;--paper:#f3f6f8;--card:#fff;--blue:#2d659e;--orange:#bb5a2b}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:24px 18px 70px}h1{margin:0 0 6px}h2{font-size:19px}.notice{background:#fff8ee;border-left:4px solid var(--orange);padding:10px 13px}.toolbar{position:sticky;top:0;z-index:2;background:#f3f6f8ee;padding:10px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:15px;margin:16px 0}.alts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.alt{border:1px solid var(--line);border-radius:7px;padding:10px}.snippet{border-top:1px solid #e2e7ed;padding-top:8px;margin-top:8px}.roll{width:100%;height:140px;background:#fafcfd;border:1px solid #dce3ea}.controls{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}button{border:1px solid #8998a8;border-radius:5px;background:white;padding:7px 11px;cursor:pointer}button.primary{background:var(--blue);color:white;border-color:var(--blue)}fieldset{border:1px solid var(--line);border-radius:6px;padding:8px 11px;margin:12px 0}label{margin-right:12px;white-space:nowrap}textarea{width:100%;min-height:55px;padding:7px;border:1px solid #8998a8;border-radius:5px}.muted{color:var(--muted);font-size:13px}.grid{stroke:#e2e7ed;stroke-width:1}.note{fill:var(--blue)}.pitch-label{font-size:9px;fill:#4f5b6c}
</style></head><body><main><h1>Paired listening review</h1><p class="notice"><strong>Listening disclosure.</strong> A and B are anonymous alternatives from two dataset variants. Playback is browser synthesis of symbolic MIDI notes, not source audio. Timing uses each source MIDI tempo map. Percussion uses a deterministic pitch-filtered noise approximation, not General MIDI kit samples. This is a reversible software blind, not physical blinding.</p><p>Listen to both alternatives for each pair. Use one preference, or leave it blank. Blank preferences and notes remain null in the exported JSON.</p><div class="toolbar"><label>Annotator ID <input id="annotator-id" type="text" autocomplete="off" aria-label="Annotator ID"></label><button id="stop" type="button">Stop playback</button><button id="export" class="primary" type="button">Export ratings JSON</button><span id="status" class="muted" role="status" aria-live="polite"></span></div><section id="cards"></section><details id="fallback" hidden><summary>View export</summary><textarea id="export-text" readonly aria-label="Exported ratings JSON"></textarea></details></main><script id="paired-data" type="application/json">__PACKET__</script><script>
'use strict';const packet=JSON.parse(document.getElementById('paired-data').textContent),cards=document.getElementById('cards'),NS='http://www.w3.org/2000/svg';let ctx=null,nodes=[],timer=null,token=0;function el(t,s,c){const x=document.createElement(t);if(s!==undefined)x.textContent=s;if(c)x.className=c;return x}function stop(msg){token++;if(timer!==null)clearTimeout(timer);timer=null;for(const n of nodes){try{n.stop()}catch(_e){}try{n.disconnect()}catch(_e){}}nodes=[];if(msg)document.getElementById('status').textContent=msg}document.getElementById('stop').onclick=()=>stop('Playback stopped.');
function roll(svg,s,kind){const w=620,h=135,p=30,ps=[...new Set(s.notes.map(n=>n.pitch))].sort((a,b)=>b-a),hi=Math.max(...ps),lanes=kind==='percussion'?Math.max(1,ps.length):Math.max(1,hi-Math.min(...ps)+1);svg.setAttribute('viewBox',`0 0 ${w} ${h}`);for(let b=0;b<=Math.ceil(s.duration_beats);b+=Math.max(1,Math.ceil(s.duration_beats/32))){const l=document.createElementNS(NS,'line');const x=p+(w-p-3)*b/s.duration_beats;l.setAttribute('x1',x);l.setAttribute('x2',x);l.setAttribute('y1',0);l.setAttribute('y2',h);l.setAttribute('class','grid');svg.append(l)}if(kind==='percussion'){for(const pitch of ps){const label=document.createElementNS(NS,'text'),lane=ps.indexOf(pitch);label.setAttribute('x','2');label.setAttribute('y',5+(lane+.7)*(h-8)/lanes);label.setAttribute('class','pitch-label');label.textContent=String(pitch);svg.append(label)}}for(const n of s.notes){const r=document.createElementNS(NS,'rect'),lane=kind==='percussion'?ps.indexOf(n.pitch):hi-n.pitch;r.setAttribute('x',p+(w-p-3)*n.onset_beats/s.duration_beats);r.setAttribute('y',3+lane*(h-7)/lanes);r.setAttribute('width',Math.max(2,(w-p-3)*Math.min(n.duration_beats,s.duration_beats-n.onset_beats)/s.duration_beats));r.setAttribute('height',Math.max(2,(h-7)/lanes-1));r.setAttribute('class','note');svg.append(r)}}
function noiseSample(pitch,index){let x=(Math.imul(pitch+1,0x9e3779b1)^Math.imul(index+1,0x85ebca6b))>>>0;x^=x>>>16;x=Math.imul(x,0x7feb352d);x^=x>>>15;x=Math.imul(x,0x846ca68b);x^=x>>>16;return((x>>>0)/4294967295)*2-1}function drumFrequency(pitch){if(pitch<=36)return 90+(pitch-35)*18;if(pitch===38||pitch===40)return 1750+(pitch-38)*225;if([42,44,46].includes(pitch))return 5200+(pitch-42)*350;if([49,51,52,55,57,59].includes(pitch))return 6800+(pitch-49)*120;if([41,43,45,47,48,50].includes(pitch))return 230+(pitch-41)*42;return 700+pitch*28}
async function play(s,id,kind){stop();const t=token;ctx=ctx||new AudioContext();await ctx.resume();if(t!==token)return;const base=ctx.currentTime+.04;let latest=s.duration_seconds;document.getElementById('status').textContent=`Playing ${id}.`;for(const n of s.notes){const when=base+n.onset_seconds,d=Math.max(.035,n.duration_seconds),g=ctx.createGain();g.gain.setValueAtTime(Math.min(.14,.025+n.velocity/1100),when);g.gain.exponentialRampToValueAtTime(.0001,when+d);g.connect(ctx.destination);if(kind==='percussion'){const frames=Math.max(1,Math.floor(ctx.sampleRate*Math.min(.12,d))),buffer=ctx.createBuffer(1,frames,ctx.sampleRate),data=buffer.getChannelData(0),filter=ctx.createBiquadFilter();for(let i=0;i<frames;i++)data[i]=noiseSample(n.pitch,i)*(1-i/frames);filter.type='bandpass';filter.frequency.value=Math.min(ctx.sampleRate*.4,drumFrequency(n.pitch));filter.Q.value=.8;const o=ctx.createBufferSource();o.buffer=buffer;o.connect(filter);filter.connect(g);o.start(when);o.stop(when+d);nodes.push(o,g,filter)}else{const o=ctx.createOscillator();o.frequency.value=440*Math.pow(2,(n.pitch-69)/12);o.connect(g);o.start(when);o.stop(when+d);nodes.push(o,g)}latest=Math.max(latest,n.onset_seconds+d)}timer=setTimeout(()=>stop('Playback finished.'),(latest+.2)*1000)}
for(const pair of packet.pairs){const card=el('article',undefined,'card');card.dataset.id=pair.review_id;card.append(el('h2',pair.review_id));const alts=el('div',undefined,'alts');for(const side of ['A','B']){const alt=el('section',undefined,'alt'),kind=pair.alternatives[side].kind;alt.append(el('h3',side));for(const s of pair.alternatives[side].snippets){const sn=el('div',undefined,'snippet');sn.append(el('strong',s.label));const svg=document.createElementNS(NS,'svg');svg.setAttribute('class','roll');svg.setAttribute('role','img');svg.setAttribute('aria-label',`${side} ${s.label} piano roll`);roll(svg,s,kind);sn.append(svg);const b=el('button','Play');b.type='button';b.onclick=()=>play(s,pair.review_id,kind).catch(()=>stop('Playback unavailable.'));const controls=el('div',undefined,'controls');controls.append(b);sn.append(controls);alt.append(sn)}alts.append(alt)}card.append(alts);const field=el('fieldset');field.append(el('legend','Preference'));for(const v of ['A','B','tie','uncertain']){const l=el('label');const i=document.createElement('input');i.type='radio';i.name=`pref-${pair.review_id}`;i.value=v;l.append(i,document.createTextNode(` ${v}`));field.append(l)}card.append(field);const notes=document.createElement('textarea');notes.placeholder='Optional notes';notes.setAttribute('aria-label',`${pair.review_id} notes`);notes.dataset.notes='1';card.append(notes);cards.append(card)}
function checked(card){const x=card.querySelector(`input[name="pref-${card.dataset.id}"]:checked`);return x?x.value:null}document.getElementById('export').onclick=()=>{stop();const ratings=[...cards.children].map(card=>({review_id:card.dataset.id,preference:checked(card),notes:card.querySelector('[data-notes]').value.trim()||null,candidate_ids:packet.pairs.find(p=>p.review_id===card.dataset.id).candidate_ids}));const out={schema_version:'samuged-paired-review-ratings-v1',annotator_id:document.getElementById('annotator-id').value.trim()||null,packet_sha256:packet.packet_sha256,ratings};const text=JSON.stringify(out,null,2)+'\n';document.getElementById('export-text').value=text;document.getElementById('fallback').hidden=false;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type:'application/json'}));a.download='paired-ratings.json';document.body.append(a);a.click();a.remove();document.getElementById('status').textContent=`Prepared ${ratings.length} rows.`};
</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left-dataset", required=True, type=Path)
    parser.add_argument("--right-dataset", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--kind", choices=KINDS, default="melodic")
    parser.add_argument("--seed", default=DEFAULT_SEED)
    args = parser.parse_args()
    result = build_packet(args.source, args.left_dataset, args.right_dataset, args.output, count=args.count, kind=args.kind, seed=args.seed)
    print(f"wrote {args.output.resolve()} with {result['packet']['config']['selected_count']} pairs")


if __name__ == "__main__":
    main()
