# Melodic metric arithmetic audit

## Scope

This audit independently recomputes the saved planted interval metrics in three
preferred frozen evaluations:

* `research_local/evaluation_reference_v04`
* `research_local/aligned_frozen_v02`
* `research_local/closed_patterns_v01_replication`

It verifies experiment and completion receipts before reading scores, requires
each score stream to cover its truth labelled receipt cohort exactly and checks
the same artifacts again before completing. The new receipt also binds the core
artifacts and every file in each input experiment's source snapshot.

The audit does not call `samuged.evaluate.temporal_iou`, `_one_to_one_matches`
or `score_case`. Temporal IoU is computed with `fractions.Fraction`. Matching
uses an independent augmenting path algorithm that returns a maximum cardinality
one to one bipartite matching at the inclusive threshold 4/5.

## Results

All 7,000 score rows passed. The audit reconstructed 6,745 candidate decisions
and 14,163 predicted occurrence intervals. It found zero mismatches in candidate
family correctness, recovery rank, candidate TP, FP and FN, occurrence TP, FP
and FN, saved match coordinates or saved IoU values rounded to eight decimal
places.

| Frozen study and score stream | Rows | Candidates | Predicted intervals | Candidate TP | Occurrence TP | Mismatches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Reference, approximate | 1,000 | 1,004 | 2,108 | 647 | 1,355 | 0 |
| Reference, exact | 1,000 | 744 | 1,588 | 358 | 777 | 0 |
| Reference, transposed | 1,000 | 825 | 1,750 | 434 | 929 | 0 |
| Aligned study, aligned | 1,000 | 1,050 | 2,199 | 814 | 1,678 | 0 |
| Aligned study, reference approximate | 1,000 | 1,004 | 2,108 | 647 | 1,355 | 0 |
| Closed replication, aligned closed extension | 500 | 522 | 1,083 | 420 | 880 | 0 |
| Closed replication, aligned original | 500 | 537 | 1,122 | 404 | 834 | 0 |
| Closed replication, indexed closed extension | 500 | 522 | 1,083 | 420 | 880 | 0 |
| Closed replication, indexed original | 500 | 537 | 1,122 | 404 | 834 | 0 |

The real pilot rows in the aligned and closed experiments are not part of this
arithmetic audit because they have no planted truth intervals. Their presence
and hashes remain covered by the verified source experiment receipts.

## Assignment finding

All truth interval sets in the audited cohorts are disjoint. Across all 14,163
predicted intervals, zero predictions had eligible edges to more than one truth
interval at IoU at least 4/5.

This edge structure is a collection of stars centered on truth intervals. A
prediction cannot be reassigned to a different truth. Any greedy algorithm that
accepts eligible unused pairs matches one prediction for every truth vertex
that has at least one eligible prediction, which is the maximum possible
cardinality. The independent matcher therefore confirms that the saved greedy
assignment has the same cardinality for every audited row. Exact saved match
coordinates and IoU values also matched the independent result.

This finding is specific to the frozen cohorts and threshold. Greedy weighted
assignment is still unsafe in the general case. The test suite includes an
overlapping truth graph where the highest IoU greedy choice returns one match
while maximum cardinality matching returns two.

## Relationship to the earlier review

The greedy assignment section in [the earlier evaluation review](evaluation_review.md)
now points to this audit. Its historical experiment results remain unchanged.
This new evidence narrows one metric implementation concern. It does not validate
the musical meaning of the planted truth, phrase boundaries or detector selections.

## Provenance

| Input study | Start receipt SHA256 | Completion receipt SHA256 |
| --- | --- | --- |
| Reference v04 | `547dfed54378c435568f4ffe87427a8a1a67a008bd624d24c3cffead44a69536` | `6e24ec926816aab1c5e726020e12d68117fd40b674687f3381eb36ca9590d350` |
| Aligned frozen v02 | `dfb5f1e958dc68dfa6c9425e6ea18989e5fbde187d7c6c37f53aa153be17c303` | `5396f4a6fdaeb48cb5bda0f8ee0504009dacd3322d8194c8129e8c57baf7ad55` |
| Closed replication | `b87adb7499a2aedc6649e3c60730c7f6aa168ea7ca68b3f72028de677fe1b6df` | `98f46af700384176ae2406e5db360be61e404ea10773e57e99fd84e82e992aed` |

The new audit is frozen in `research_local/melodic_metric_audit_v01`.

* Start receipt SHA256 `f7d133d2be7d975eace2c60979c30abe961e44df7567c503e204cacfb199567e`
* Configuration SHA256 `d15b7a31dd58fa99482bfde9a5de6827db77908548581ed639f3d9e21e0e9c0c`
* Source snapshot SHA256 `8775ef69a708a31fb9c35f21ab938f91b2235d805cb943bf435f43124f42e2cd`
* Input inventory cohort SHA256 `0673c64082cc69f27123e540a29cfec2b22fcf70abc6fad61a97c69a57aac6ef`
* Raw audit SHA256 `d6cd69aeaeea4a010c36054cbadaba52efd4ad3c5e853062b26d0fe7809d2179`
* Aggregate SHA256 `037c8ff6ccd28b717878e9be62abc4d758dfd12a6521087bc0b1b01f9d864acb`

These receipts establish artifact integrity and replay inputs. The audit remains
a metric arithmetic check rather than human musical validation.
