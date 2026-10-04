import pytest
from scripts.curate_demo_cycles import replace_popular
from scripts.build_song_variants import phrase_period


def test_demo_replacement_keeps_slot_but_uses_own_count():
    rows = [dict(phrase_id='old', rank=46, occurrence_count=6)]
    new = dict(phrase_id='new', rank=12, occurrence_count=3, with_drums={'phrase_id':'pair'})
    replace_popular(rows, 'old', new)
    assert rows[0]['rank'] == 46
    assert rows[0]['occurrence_count'] == 3
    rows[0]['with_drums']['phrase_id'] = 'changed'
    assert new['with_drums']['phrase_id'] == 'pair'
    replace_popular(rows, 'old', new)
    assert rows[0]['rank'] == 46


def test_demo_replacement_rejects_ambiguous_slots():
    with pytest.raises(ValueError):
        replace_popular([{'phrase_id':'old'}, {'phrase_id':'new'}], 'old', {'phrase_id':'new'})


def test_extra_cycle_does_not_use_distance_between_repeats():
    row = dict(ticks_per_beat=480, start_tick=0, end_tick=1800,
               occurrences=[dict(start_tick=i*38400, end_tick=i*38400+1800) for i in range(4)])
    decision = phrase_period(row, (4, 4))
    assert decision.period_ticks == 1920
    assert decision.period_ticks >= row['end_tick']
