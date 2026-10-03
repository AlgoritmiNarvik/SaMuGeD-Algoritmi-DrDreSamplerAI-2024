from copy import deepcopy

import pytest

from scripts.analyze_top_phrases import artist_key, chart_rows, keep_best, motif_eligible, normalize, rank_key, verify_occurrences


def phrase(**changes):
    row = dict(kind="melodic", note_count=8, pitches=[60, 62, 64, 65] * 2,
               duration_beats=4, program=0, part_name="Lead", occurrence_count=2,
               recurrence_score=.8, source_path="A/Song.mid", phrase_id="a")
    row.update(changes)
    return row


@pytest.mark.parametrize("changes", [dict(kind="percussion"), dict(note_count=7),
    dict(pitches=[60, 62, 64] * 3), dict(duration_beats=3.9), dict(program=32),
    dict(program=39), dict(part_name="ACOU BASS"), dict(part_name="DRUMS"),
    dict(part_name="TR808 Beat Box")])
def test_structural_filter_excludes_explicit_low_diversity_or_bass_cases(changes):
    assert not motif_eligible(phrase(**changes))


def test_structural_filter_boundaries_and_labels():
    assert motif_eligible(phrase())
    assert motif_eligible(phrase(program=40, part_name="Background keyboards"))


def test_arrangements_choose_one_observed_maximum_never_add_support():
    rows = {}
    keep_best(rows, "same-song", phrase(occurrence_count=7))
    keep_best(rows, "same-song", phrase(occurrence_count=5, phrase_id="b"))
    keep_best(rows, "same-song", phrase(occurrence_count=9, phrase_id="c"))
    assert len(rows) == 1
    assert rows["same-song"]["occurrence_count"] == 9
    assert rows["same-song"]["phrase_id"] == "c"


def test_frequency_precedes_detector_score_and_ties_are_stable():
    rows = [phrase(occurrence_count=8, recurrence_score=1, phrase_id="z"),
            phrase(occurrence_count=9, recurrence_score=.1, phrase_id="b"),
            phrase(occurrence_count=9, recurrence_score=.1, phrase_id="a")]
    assert [row["phrase_id"] for row in sorted(rows, key=rank_key)] == ["a", "b", "z"]


def test_chart_parser_keeps_recording_and_artist_pair_without_guessing(tmp_path):
    path = tmp_path / "chart.html"
    path.write_text("<table><tr>" + "".join(f"<th>{x}</th>" for x in ["POS", "TITLE", "ARTIST", "YEAR", "PEAK"]) + "</tr><tr><td>1</td><td>Careless Whisper</td><td>George Michael</td><td>1984</td><td>1</td></tr></table>")
    row = chart_rows(path)[0]
    assert row["chart_rank"] == 1
    assert (artist_key(row["chart_artist"]), normalize(row["chart_title"])) == (artist_key("Michael_George"), normalize("Careless_Whisper"))
    assert artist_key("George Michael") != artist_key("Wham!")
    assert normalize("Careless Whisper Live") != normalize("Careless Whisper")


def test_occurrence_verifier_counts_prototype_once_and_allows_touching_spans():
    row = dict(occurrence_count=2, start_tick=0, end_tick=10,
               occurrences=[dict(start_tick=0, end_tick=10), dict(start_tick=10, end_tick=20)])
    verify_occurrences(row)
    for bad in [dict(occurrence_count=3), dict(start_tick=1),
                dict(occurrences=[dict(start_tick=0, end_tick=10), dict(start_tick=9, end_tick=20)])]:
        invalid = deepcopy(row)
        invalid.update(bad)
        with pytest.raises(ValueError):
            verify_occurrences(invalid)
