# Primary sources for recurring symbolic phrase research

## Scope and claim boundary

This note supports a local experiment that discovers repeated symbolic melodic phrase candidates in MIDI. It does not support calling those candidates hooks, catchy phrases or earworms. Repetition is an observable property of a score representation. A hook is a perceptually salient or memorable passage and involuntary musical imagery (INMI) is a listener's spontaneous mental experience. Those outcomes need separate human evidence.

The strongest defensible paper claim at this stage is: *the system detects and ranks recurring symbolic phrase candidates under stated pitch, timing and overlap invariances*. Any claim about musical salience, memorability or INMI must wait for a human study.

## Lakh MIDI Clean identity and caveats

The [official Lakh MIDI Dataset page](https://colinraffel.com/projects/lmd/) describes LMD as MIDI files scraped from publicly available internet sources and deduplicated by MD5. It reports 176,581 files in LMD-full and 45,129 in LMD-matched. It defines the **Clean MIDI subset** more narrowly than its name suggests: files whose filenames indicate artist and title, with acknowledged inaccuracies. The page does not state an exact Clean subset file count or publish a snapshot checksum.

The local checkout contains 17,232 paths ending in `.mid` on 2026-10-03. Two are under the hidden artist directory `.38 Special`, so `rg --files` reports 17,230 unless hidden paths are included. This is a local inventory, not proof that the directory is identical to the original archive at byte level. A recent primary study used an LMD-clean snapshot of 17,184 files and treated 10,355 as duplicates according to artist and song name metadata ([Choi et al., 2025](https://arxiv.org/abs/2509.16662)). Report the manifest hash and parser success count for every experiment instead of asserting a universal Clean count.

There are two further count conflicts to preserve in the paper's data statement. Raffel's official project page says 176,581 LMD-full files, while [Raffel's thesis](https://colinraffel.com/publications/thesis.pdf) and Choi et al. say 178,561. Use the count for the actual local manifest and identify the source and snapshot. Do not silently reconcile these published numbers.

The official page applies CC BY 4.0 to the distributed dataset and asks users to cite the page and thesis. It also says Raffel did not transcribe the files and that MIDI copyright meta events are inconsistent, which makes attribution for each file infeasible. The collection licence therefore does not by itself establish permission to redistribute each underlying composition or arrangement. Keep the corpus and extracted phrases local. Publish aggregate measurements, code and derived metadata that cannot reconstruct the music only until a rights review approves any musical examples.

The word *Clean* must not be interpreted as validated notation, unique musical works, correct artist labels or copyright clearance. Choi et al. distinguish hard duplicates (nearly identical arrangements with changes such as tempo, offset, track order or small note edits) from soft duplicates (different arrangements preserving core musical content). They show why file hashes and random file splits are insufficient for leakage control.

## Algorithm evidence

### Point set and compression methods

[Meredith (2013)](https://vbn.aau.dk/en/publications/cosiatec-and-siateccompress-pattern-discovery-by-geometric-compre/) describes SIATEC based geometric compression variants. SIATEC yields maximal translatable patterns and their translational equivalence classes. COSIATEC repeatedly selects a high scoring class and removes covered points. SIATECCompress runs SIATEC once and selects classes that cover the input. Compression ratio and compactness are selection criteria, which makes these useful baselines for controlling the very large set of exact transposition invariant repeats.

[Meredith (2015)](https://doi.org/10.1080/09298215.2015.1045003) evaluates COSIATEC, SIATECCompress and Forth's algorithm on tune family classification, repeated themes and sections and fugue subject entries. The algorithms return compact point set patterns with occurrence vectors, but their relative performance varies by task. This argues against treating a single discovery algorithm or score as a general definition of musical importance. In the common two dimensional representation, notes use onset and pitch. Translation naturally handles a later occurrence and pitch transposition, but it does not by itself handle tempo scaling, ornamentation, deleted notes or the choice of melody voice.

[Lartillot (2014)](https://archives.ismir.net/ismir2014/paper/000308.pdf) presents the method commonly associated with PatMinr. It mines closed, heterogeneous patterns across multiple melodic and rhythmic dimensions and models cyclic repetition to suppress redundant prefixes, suffixes and repeated loop variants. Its reported demonstration is on one JKU Patterns Development Database piece, so it is a useful contrasting baseline rather than broad evidence of effectiveness on popular multitrack MIDI.

[Ren et al. (2020)](https://arxiv.org/abs/2010.12325) show that pattern discovery algorithms disagree substantially with human annotations and with each other. Rhythmic features contributed most to the reported differences between algorithm outputs and human annotations and among algorithms. Their controlled synthetic method plants known patterns into random material, providing direct support for a two part evaluation: controlled planted motifs for diagnostic validity and a separate human annotated real music corpus for ecological validity.

### MIREX task and annotations

The [MIREX Discovery of Repeated Themes and Sections specification](https://music-ir.org/mirex/wiki/2014%3ADiscovery_of_Repeated_Themes_%26_Sections) defines a symbolic output occurrence as onset and MIDI note pairs. It provides symbolic and audio tasks crossed with monophonic and polyphonic versions. The JKU Patterns Development Database annotations draw motifs and themes from published musicological sources and repeated sections from score markings, with some added annotations. The task explicitly notes that no ground truth is perfect.

MIREX separates whether a system establishes that a pattern exists from whether it retrieves all occurrences. Relevant measures include establishment precision, recall and F1, occurrence precision, recall and F1, three layer measures and runtime. The annotation set can contain overlapping and nested patterns. SaMuGeD should borrow the metric separation and point level matching but should not present a small classical annotation set as representative of Lakh popular song arrangements.

## Recommended local protocol

### Corpus manifest and split control

1. Freeze a manifest containing relative path, byte size, cryptographic file hash, parser status and extraction configuration. Record both raw path count and successfully parsed file count.
2. Canonicalise the artist directory and title stem only as a provisional work identifier. Preserve numbered variants such as `.1` as members of the same candidate group, then audit a sample because Choi et al. found metadata errors and distinct names for identical content.
3. Detect exact file duplicates first, then near duplicates using symbolic fingerprints or retrieval. Group hard and soft duplicates before splitting. Split by canonical work group and artist, not by MIDI file, so arrangements of the same song and conventions associated with one artist cannot cross train, validation or test sets.
4. Keep a frozen evaluation set that is never used to tune thresholds, seed lengths, phrase lengths or ranking weights.

### Melody and timing representation

1. Treat the current onset skyline per instrumental part as a deterministic baseline. A skyline can promote accompaniment chord tops, ornaments or countermelodies and can discard a true lower voice. Compare it with at least two alternatives: all eligible parts searched independently and a documented melody track heuristic using track names, monophony, pitch register, note density and continuity. Do not use a track name such as `melody` as unquestioned ground truth.
2. Preserve full polyphonic note events for an audit path. MIDI tracks, channels and General MIDI programs are not guaranteed to be one musical voice, and program changes can occur within a track.
3. Convert ticks to exact rational beat positions before matching. Preserve meter changes and pickups. Compare quantisation resolutions in an ablation rather than rounding permanently at ingest.
4. Keep separate representations for absolute pitch, pitch intervals, onset intervals and note duration. Transposition invariant pitch intervals are suitable for candidate generation. Verify candidates with rhythm and duration so common scales and arpeggios do not dominate solely through pitch recurrence.
5. Test tempo invariance explicitly. Translation based point sets cover onset and pitch shifts, not proportional rhythmic scaling. If rhythmic scaling is allowed, limit ratios and report results separately from exact beat pattern matches.

### Percussion boundary

These melody recommendations should not be reused unchanged for the separate drum pattern dataset. Preserve simultaneous kit hits, use General MIDI percussion identities or documented drum families and do not apply skyline reduction or melodic pitch transposition. Compare exact and timing tolerant hit patterns in meter aware one, two and four bar windows. Apply nonoverlap when counting independent occurrences and write percussion outputs to a separate schema and dataset so melodic and drum scores keep distinct meanings.

### Candidate generation, overlap and ranking

1. Use the bounded seeded window matcher as a reproducible candidate generator, then measure its blind spots across seed lengths, phrase lengths, offsets and mutation types. Seeding can miss a valid phrase when the seed itself is ornamented or deleted.
2. Require minimum note count and beat span. Collapse equivalent extensions and subpatterns with a stated rule inspired by closed pattern or compression methods. Report how many candidates each stage removes.
3. Keep all candidate occurrences before overlap filtering. Apply nonoverlap when counting independent repetitions and when building a compact dataset for users. Also retain a diagnostic view with overlaps and nested phrases because MIREX's human annotations permit both. Nonoverlap is a selection policy, not a fact about musical structure.
4. Rank with structural evidence only, for example verified occurrence count, span, note count, compactness, rhythmic agreement and voice continuity. Label the score `recurrence_score` or `phrase_score`. Do not name it `hook_score`, `catchiness` or `memorability`.
5. Include hard negatives matched on phrase length, note density and register. Common scales, arpeggios, repeated accompaniment figures, percussion ostinati and duplicated files are necessary adversarial cases.

### Controlled planted motif evaluation

Generate local symbolic carriers with known nonoverlapping insertion coordinates and deterministic seeds. Vary one factor at a time: exact repeat, transposition, onset shift, global rhythmic scaling, local timing noise, insertion or deletion of one note, ornamentation, accompaniment density, part assignment and phrase boundary position. Include carriers with no planted motif to measure false discoveries.

For each condition report precision, recall and F1 at candidate level, the same measures at occurrence level, boundary or point set overlap, false positives per piece, ranking position and runtime. Report results by condition and phrase length. An aggregate score alone can conceal that a method only solves exact repeats.

### Human real corpus evaluation

Draw a preregistered sample from the real corpus that is disjoint by work group, stratified by recurrence score, genre proxy, polyphony and phrase length. Have at least two musically trained annotators review blinded notation or piano roll plus audio renderings. For each candidate collect separate judgements for:

- whether the occurrences are the same musical phrase;
- boundary quality;
- melody versus accompaniment role;
- perceptual salience;
- confidence and reason for rejection.

Report independent ratings, interrater agreement and an adjudicated label. Do not tune on the adjudicated test set. If the study later asks about hooks, add a separate listener recognition or recall task with counterbalanced exposure. If it asks about INMI, use an INMI specific experience sampling design rather than asking annotators to infer earworms from notation.

## Hooks and involuntary musical imagery

[Burgoyne et al. (2013)](https://www.dare.uva.nl/id/96aaa66c-15e1-416b-a307-c55bcb364f2b) define the hook study around recognition and recall of song segments. Their pilot found significant differences in recall time across segments and found that participants were not reliable judges of their own recall performance. This supports measured listener behaviour rather than researcher inspection as the validation route for hooks.

[Byron and Fowles (2015)](https://doi.org/10.1177/0305735613511506) exposed 36 participants to previously unfamiliar songs two or six times and then used three days of probe caught experience sampling. More exposure and greater recency increased reported INMI. This manipulated repetition **of exposure to a song**, not the number of repeated phrases inside the composition. It cannot validate a recurrence score as an earworm score.

[Jakubowski et al. (2017)](https://doi.org/10.1037/aca0000090) compared tunes reported as INMI by 3,000 survey participants and examined song popularity and melodic features. The result supports an account with several factors involving exposure and musical properties. It does not establish that symbolic recurrence within a song is sufficient for INMI.

These studies permit a careful hypothesis for later work: recurring phrases may provide candidate material for a human hook or INMI study. They do not permit the conclusion that frequently recurring symbolic phrases are hooks or earworms.

## Primary reference set

1. Raffel, C. [The Lakh MIDI Dataset v0.1](https://colinraffel.com/projects/lmd/), official dataset page.
2. Choi, E., Kim, H., Ryu, J., Nam, J. and Jeong, D. (2025). [On the de-duplication of the Lakh MIDI dataset](https://arxiv.org/abs/2509.16662).
3. Meredith, D. (2013). [COSIATEC and SIATECCompress: Pattern discovery by geometric compression](https://vbn.aau.dk/en/publications/cosiatec-and-siateccompress-pattern-discovery-by-geometric-compre/).
4. Meredith, D. (2015). [Music analysis and point-set compression](https://doi.org/10.1080/09298215.2015.1045003).
5. Lartillot, O. (2014). [In-depth motivic analysis based on multiparametric closed pattern and cyclic sequence mining](https://archives.ismir.net/ismir2014/paper/000308.pdf).
6. Ren, I., Volk, A., Swierstra, W. and Veltkamp, R. C. (2020). [A computational evaluation of musical pattern discovery algorithms](https://arxiv.org/abs/2010.12325).
7. Collins, T. et al. [MIREX Discovery of Repeated Themes and Sections specification](https://music-ir.org/mirex/wiki/2014%3ADiscovery_of_Repeated_Themes_%26_Sections).
8. Burgoyne, J. A., Bountouridis, D., van Balen, J. M. H. and Honing, H. (2013). [Hooked: A game for discovering what makes music catchy](https://www.dare.uva.nl/id/96aaa66c-15e1-416b-a307-c55bcb364f2b).
9. Byron, T. P. and Fowles, L. C. (2015). [Repetition and recency increases involuntary musical imagery of previously unfamiliar songs](https://doi.org/10.1177/0305735613511506).
10. Jakubowski, K., Finkel, S., Stewart, L. and Müllensiefen, D. (2017). [Dissecting an earworm: Melodic features and song popularity predict involuntary musical imagery](https://doi.org/10.1037/aca0000090).
11. Raffel, C. (2016). [Learning-Based Methods for Comparing Sequences, with Applications to Audio-to-MIDI Alignment and Matching](https://colinraffel.com/publications/thesis.pdf). PhD thesis, Columbia University. The Lakh publisher requests this citation alongside its dataset page.
12. Shih, Y.-J., Wu, S.-L., Zalkow, F., Müller, M. and Yang, Y.-H. (2022). [Theme Transformer: Symbolic Music Generation with Theme-Conditioned Transformer](https://arxiv.org/abs/2111.04093v2). IEEE Transactions on Multimedia.
13. Wang, Z., Chen, K., Jiang, J., Zhang, Y., Xu, M., Dai, S., Bin, G. and Xia, G. (2020). [POP909: A Pop-song Dataset for Music Arrangement Generation](https://github.com/music-x-lab/POP909-Dataset). Proceedings of ISMIR.
14. Collins, T. (2013). [JKU Patterns Development Database](https://tomcollinsresearch.net/research/data/mirex/). August 2013 no-audio distribution, used only for the stated development diagnostic.

## External metric implementation check

The local JKU adapter uses [mir_eval's pattern metrics](https://mir-eval.readthedocs.io/latest/api/pattern.html), based on [Raffel et al. (2014)](https://colinraffel.com/publications/ismir2014mir_eval.pdf). The official no-audio JKU archive provides seven example output files and a MATLAB metric table. All 17 comparable metric columns reproduce within 0.00001 after calling occurrence thresholds explicitly.

In installed mir_eval 0.8.2, the evaluation wrapper supplies `thresh` while `occurrence_FPR` accepts `thres`. The wrapper therefore labels one set of threshold 0.75 values as threshold 0.5. The adapter overrides both occurrence calls explicitly and records this correction. Original v01 threshold 0.5 artifacts are retained as invalid evidence. The preferred corrected run is `research_local/jku_reference_v03`, which also freezes the local import closure; v02 remains the earlier corrected run.

## External popular music annotations

The [Theme Transformer theme retrieval study](https://atosystem.github.io/ThemeTransformer/themeRetrieval.html) provides three human annotations for six POP909 songs. The annotators could choose boundaries away from bar lines and identify different themes in the same song. The authors report variable agreement and mixed strengths across retrieval methods. This is useful external evidence, but six songs cannot establish performance across Lakh.

The [official POP909 repository](https://github.com/music-x-lab/POP909-Dataset) identifies separate `MELODY`, `BRIDGE` and `PIANO` tracks. Our input audit compared the six official melody tracks with the annotation files before evaluation. The human files share exact note universes with each other, but their timing differs from the original POP909 files. The local diagnostic therefore uses the common annotation domain, strips annotation track identity before detection and scores exact source notes. It does not reproduce the authors' beat-domain F1. See [input checks](theme_annotation_inputs.md) and [results](theme_evaluation.md).
