# Top 50 recurrence analytics

The top 50 analytics are algorithmic recurrence annotations. They do not use listener ratings and do not infer perceptual earworm labels. The archived browser atlas contains five 50-row CSV views, copied MIDI excerpts and a machine-readable input/output receipt. Its browser audio is a symbolic MIDI synthesis preview, not an original recording.

The public dataset is [SaMuGeD recurring phrases](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases), and the rendered loop demo is the [SaMuGeD earworm loops Space](https://huggingface.co/spaces/AlmazErmilov/samuged-earworm-loops). Both are public.

The primary release is `closed_v01` with 95,077 phrases, including 50,566 melodic and 44,511 percussion phrases. `reference_v04` contains 94,950 phrases, including 50,439 melodic and 44,511 percussion phrases. Neither release includes listener labels.

## Views and ranking

- [Melodic motifs](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/resolve/main/analytics/top50_motifs.csv): the most repeated saved candidates after the explicit structural filter.
- [Popular songs](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/resolve/main/analytics/top50_popular.csv): the same ranking restricted to exactly matched UK million-selling singles.
- [Raw melodic recurrence](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/resolve/main/analytics/top50_raw.csv): no structural filter, retaining simple ostinati and accompaniment.
- [Shared families](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/resolve/main/analytics/top50_families.csv): saved melodic family signatures ranked by distinct normalized catalog identities.
- [Percussion](https://huggingface.co/datasets/AlmazErmilov/samuged-recurring-phrases/resolve/main/analytics/top50_drums.csv): separate drum patterns ranked by nonoverlapping occurrences.

The source is the audited `aligned_closed` corpus, containing 50,566 melodic and 44,511 percussion rows across 17,232 input paths. Its saved candidate selection and source reconstruction have already passed the checks documented in [DELIVERY.md](DELIVERY.md). Rankings operate over these saved outputs, up to three selected candidates per kind and MIDI, rather than every possible musical fragment.

Occurrence count includes the prototype once and only nonoverlapping spans. Order is descending occurrence count, duration in quarter-note beats, note count and saved recurrence score. Source path and phrase ID resolve ties deterministically. One normalized artist/title `song_key` appears in each within-song view. Multiple arrangements contribute their maximum observed candidate, never a sum of repetitions. Normalized path names are not independently verified composition identities, so differently named remixes, takes or artist aliases can remain separate.

The structural motif filter requires at least eight notes, four distinct pitches and four quarter-note beats. General MIDI bass programs 32 through 39 and parts labelled bass, basse, bajo, drum, drums, percussion or beat box are excluded. This removes many simple or explicitly labelled accompaniment cases without claiming that every remaining part is a lead melody. The raw view makes the effect inspectable. The filter retains 27,693 candidates under 7,903 normalized catalog identities.

## Popularity evidence

The popularity cohort uses [Official Charts' UK million-selling singles](https://www.officialcharts.com/chart-news/the-best-selling-singles-of-all-time-on-the-official-uk-chart__21298/), based on physical sales and downloads. The locally retained HTML snapshot contains 180 chart rows and its exact bytes are bound in the receipt. This is historical UK sales eligibility, not current streaming or worldwide listener popularity.

Matching uses equal normalized title and equal sorted artist tokens, ignoring only the artist token `the`. Punctuation, accents, underscores and token order normalize deterministically. There is no fuzzy matching, collaboration guessing, manual artist alias expansion or double-A-side splitting. This conservative rule finds 68 chart entries with saved melodic candidates and 56 with structurally eligible candidates. The popular view ranks the first 50 of those 56 by within-MIDI recurrence, with the separate chart sales rank included. The UI uses the chart's artist spelling while retaining the original path labels in JSON and CSV.

## Results

The melodic motif leaders are Bob Marley, `Exodus` with 93 occurrences; AC/DC, `Thunderstruck` with 59; and James Brown, the path-labelled `Sex Machine Get Up I Feel Like Being A` with 58. These are the actual extracted parts, which need not be a song's familiar vocal hook.

The popular cohort begins with Spice Girls, `2 Become 1` with 23 occurrences; Goo Goo Dolls, `Iris` with 18; George Michael, `Careless Whisper` with 16; New Order, `Blue Monday` with 15; and Eiffel 65, `Blue (Da Ba Dee)` with 15. These numbers characterize saved MIDI arrangements, not the original recording or listeners' memory.

The raw leader has 100 occurrences and only three distinct pitches. The most repeated eligible motif has 93. The percussion leader has 201 one-bar occurrences. Shared melodic families reach four normalized catalog identities in this snapshot, but title variants and artist aliases can explain some of those memberships. No cross-song copying or global earworm popularity claim follows from a shared signature.

## Checks and use

All five views contain 50 positions. Across them there are 236 unique listening candidates from 208 source MIDI files. For every displayed candidate the builder checks occurrence-count equality, positive spans, nonoverlap, prototype inclusion, source byte identity, source-note coordinates of the prototype and up to two alternate snippets, and copied MIDI export hashes. The full manifest hashes must equal the audited dataset's summary hashes. The receipt additionally binds the helper code, chart snapshot, dataset audit, schemas, build configuration and every generated output. JSON and all five CSV files were checked for matching ordered IDs; all 244 output hashes matched after generation. The new ranking and existing review/Unicode tests pass 26 cases.

A separate read-only reconstruction from the full phrase manifest reproduced all five ordered rankings. The final root check verifies all 13 input hashes and 244 output hashes and confirms that the final UI corrections did not change any ranking or source-derived snippet. The archived offline ZIP at `research_local/top50_v01/samuged_top50_analytics.zip` contains 245 files, is 668,686 bytes and passes ZIP integrity checking. Its SHA256 is `d9333aab1d78f5ead5eb386eca1ecc76bda7826faf145244dbe3c584a20bb6b2`. Final receipt SHA256 is `420df0affac7e9d5dd9abfc19358c4e2c244804e238c25e5ec782fcf4d0f45a6`. The archived root verification at `research_local/top50_v01/final_root_verification.json` records this boundary. These exact values are retained as historical evidence from the archived Russian snapshot.

The archived browser interface supports search, all five views, a note plot, a recurrence timeline, source disclosure, CSV and MIDI downloads, prototype playback and alternate occurrences. Timing integrates the actual source MIDI tempo map. Its audio is a symbolic browser synthesis preview, not an original recording or a General MIDI soundfont. Forty rendered source cycles loop continuously in the linked Space. A separate song-level evidence view supports familiar-hook selection. Search-limit and candidate-truncation warnings remain visible on relevant results. The timeline runs from tick zero to the final saved occurrence, not necessarily the song's end.

Open `http://127.0.0.1:8877/index.html` while the local preview runs. The HTML also opens directly as a self-contained file. To restart its preview:

```bash
source .venv/bin/activate
python -m http.server 8877 --bind 127.0.0.1 \
  --directory research_local/top50_v01/final
```

To rebuild into a new directory using the retained chart snapshot:

```bash
source .venv/bin/activate
python -m scripts.analyze_top_phrases \
  --dataset research_local/lakh_aligned_closed_v01 \
  --source 'datasets/Lakh MIDI Clean' \
  --chart-html research_local/top50_v01/official_charts.html \
  --output research_local/top50_v01/reproduction
```

The public release includes the algorithmic recurrence tables and source-derived evidence described above. External evaluation data such as POP909, Theme and JKU are not distributed. Their results and citations can be described separately. The hosted files and public player have been verified.
