# SupeRR Selector Season 2
## Identifying the most reliable IPL and T20I players under pressure

**Round 1 methodology and results submission**
**Prepared:** 18 November 2026
**Candidate / team:** [Add your name or team name before submission]

---

## Executive summary

This submission develops a reproducible, data-driven method for identifying batters and bowlers who perform better in pressure situations than they do in comparable, non-pressure situations. It uses only the six supplied CSV datasets and compares every player with their own baseline, rather than ranking on raw totals or reputation.

Pressure is evaluated at the start of each delivery in the second innings of a live chase. Separate batting and bowling pressure indices combine the format-relative percentile of the required run rate, wickets already lost, and the fraction of the innings already elapsed. The top quartile of each index within its format defines pressure deliveries. Player performance is compared with that same player's non-pressure chase performance in the same format, then combined across formats only after the within-format comparisons.

The final analysis includes **808 eligible matches**, **91,453 modeled chase deliveries**, **56 eligible batters**, and **107 eligible bowlers**. It returns ten players in each category. David Miller leads the batter list; Vyshak Kumar leads the bowler list. Sample-size shrinkage, minimum exposure thresholds, consistency measures, and match-level bootstrap intervals reduce the chance that a small number of good performances dominate the results.

The supplied match outcomes agree with the modeled target in all **808 of 808** eligible matches. The source CSVs were not edited. Data-quality exceptions were retained, documented, and handled only where the analysis rules required exclusions.

### Results at a glance

| Category | Rank 1 | Main rating | Eligible cohort |
|---|---|---:|---:|
| Batter | David Miller | +49.10 adjusted strike-rate points vs baseline | 56 |
| Bowler | Vyshak Kumar | 2.42 composite z-score | 107 |

These are comparative, descriptive ratings for the supplied data and chosen pressure definition. They are not predictions of future performance or causal estimates of pressure's effect.

---

## 1. Challenge objective and scope

The Round 1 brief requests two ordered top-10 lists, one for batters and one for bowlers, and a methodology report explaining the pressure definition, performance ratings, fair comparisons, ranking evidence, reliability, and limitations. The lists below are in submission order and can be entered into the Unstop rank fields.

The analyzed competition pool includes:

- Competitions whose format is **T20I**.
- Competitions whose name matches **IPL YYYY**.

Other competitions labeled T20 are outside the ranking scope. Only main second-innings chases are modeled. First innings, super overs/other innings, abandoned and no-result matches, matches without an observed winner, and matches that lack enough information to determine a target are not ranked.

The supplied snapshot contains **883 match rows**. The resulting analysis uses 808 eligible chases. The method is deliberately limited to chase pressure because the delivery data supports direct calculation of target, runs required, balls remaining, wickets lost, and required run rate in this context.

---

## 2. Data sources and preparation

### 2.1 Supplied datasets

| Dataset | Rows × columns | Role in the analysis |
|---|---:|---|
| `ball_by_ball.csv` | 200,999 × 33 | Delivery runs, extras, innings, batting/bowling participants, wickets, and delivery order |
| `matches.csv` | 883 × 22 | Competition and match IDs, winner, result, revised target/overs, teams, and match context |
| `competitions.csv` | 141 × 4 | Competition name, format, season, and competition ID |
| `teams.csv` | 353 × 3 | Competition-scoped team identifiers and names |
| `playing_eleven.csv` | 28,381 × 9 | Player appearances and participation flags |
| `competition_team_player_mapping.csv` | 6,413 × 6 | Competition/team/player IDs and mapped player names |

The row and column counts above describe the six supplied files at the time of analysis. Phase 1 found **zero exact duplicate rows in each file**. Candidate keys were unique for the delivery sequence, matches, competitions, teams, and competition/team/player mapping. The proposed `(match_id, team_id, player_id)` playing-eleven key was not unique, so it was not treated as a guaranteed key.

### 2.2 Relationship model

The joins are performed on scoped identifiers, not on player or team names alone:

```text
competitions (comp_id)
    ├── matches (comp_id, match_id)
    │      ├── ball_by_ball (match_id)
    │      └── playing_eleven (match_id, team_id, player_id)
    ├── teams (comp_id, team_id)
    └── competition_team_player_mapping (comp_id, team_id, player_id)

matches + competitions -> competition format and season for each match
matches + teams        -> home/away team context
matches + mapping      -> player names in the competition
```

In the source data, every ball-by-ball match ID joins to a match, every match and team/mapping competition ID joins to a competition, and all match home/away team IDs join to the teams table. Data-quality checks found five competition/team pairs in `teams.csv` without a corresponding mapping pair, and one distinct player/team/competition key absent from the mapping table that occurs in five playing-eleven rows. These gaps are reported, not silently repaired. The analysis retains player IDs as the stable identifiers; missing names are not invented.

### 2.3 Delivery calculations

At each delivery, the pipeline uses the observed fields to calculate:

- **Team runs on a delivery** = `runs + extras1_runs + extras_2_runs`.
- **Runs before the delivery** = cumulative team runs in the chase before that delivery.
- **Target** = supplied `revised_target`, when present; otherwise first-innings total plus one.
- **Runs required** = target minus runs before the delivery.
- **Legal balls remaining** = innings ball limit minus legal balls already bowled.
- **Required run rate** = runs required × 6 ÷ legal balls remaining.
- **Wickets lost** = wickets recorded before the delivery.

The default T20 innings limit is 120 legal balls. A supplied `second_inn_revised_overs` value is treated as a legal-ball budget; observed non-null values were positive multiples of six, ranging from 30 to 114. A revised target takes precedence over a target derived from the first innings. D/L or DLS-labeled matches without an explicit revised target are excluded because a reliable target cannot otherwise be reconstructed.

Delivery legality follows the observed extras labels: `wide` and `Overstep` do not consume a legal ball; all other observed extra types are treated as legal. The source has no separate legal-ball indicator, so this is an explicit modeling assumption. A batter is charged a ball faced except on a wide; a no-ball/`Overstep` is counted as a ball faced. Bowler-conceded runs include batter runs and bowler-chargeable extras, excluding byes, legbyes, and penalty extras.

---

## 3. Pressure classification

Pressure is determined before the outcome of the current delivery is added to the state. Required-run-rate percentiles are calculated within each format, keeping the IPL and T20I rate distributions separate. The innings-elapsed fraction is clipped to the interval from zero to one, as is wickets lost divided by ten.

Let:

- \(R\) = the percentile rank of current required run rate within the format;
- \(W\) = wickets already lost divided by ten;
- \(E\) = fraction of the innings' legal-ball budget already elapsed.

The two role-specific indices are:

- **Batting pressure** = 0.60 × R + 0.25 × W + 0.15 × E.
- **Bowling pressure** = 0.50 × (1 − R) + 0.30 × (1 − W) + 0.20 × E.

Deliveries at or above the **75th percentile** of the relevant index within the same format are labeled pressure. A separate index is used for each role: batting pressure emphasizes a demanding chase, while bowling pressure emphasizes a viable chase threat with wickets in hand, especially later in the innings. Consequently, a delivery can be pressure for one role and not the other.

The percentile threshold is cohort-relative, not a universal cricket threshold. It makes the definition explicit and reproducible, while ensuring that the label reflects the supplied IPL and T20I delivery distributions.

### Target and outcome check

The explicit or derived chase target was checked against the second-innings total and observed winner. **All 808 eligible matches agreed with the match outcome** under the implemented check. Rows recorded after the target was already reached or the innings quota was exhausted are excluded from pressure-state modeling; the original rows remain in the source files and are counted in diagnostics.

---

## 4. Player measurements and rating logic

### 4.1 Batters

Only striker events in the modeled second innings are included. Batter strike rate is:

**Strike rate** = 100 × (batter runs ÷ balls faced).

For each batter and format, the pressure strike rate is compared with that same batter's non-pressure chase strike rate in that format. The raw change is pressure strike rate minus baseline strike rate, in strike-rate points.

To moderate small samples, the format-specific change is shrunk toward zero:

**Adjusted change** in format *f* = (Pressure SR − Baseline SR) × *n* ÷ (*n* + 60).

where \(n_f\) is the batter's pressure balls in that format. The player's cross-format score is the pressure-ball-weighted average of the format-specific adjusted changes. This compares a player's pressure behavior with their own baseline within each format before combining results; raw IPL and T20I rates are not treated as directly interchangeable.

The batter list is sorted in descending order of this reliability-adjusted change. Positive scores mean the player scored faster in pressure chase deliveries than in their own non-pressure chase baseline, after shrinkage.

### 4.2 Bowlers

Bowling is measured on legal balls in the modeled second innings. Economy is:

**Economy** = 6 × (bowler-conceded runs ÷ legal balls).

Credited wickets are bowler-attributed dismissals only: **Caught, Bowled, LBW, Stump, and Hit Wicket**. Run-outs and other non-bowler dismissals do not count as bowler wickets. Wicket rate is expressed as credited wickets per 24 legal balls.

For each bowler and format, two improvements are measured:

- **Economy improvement** = baseline economy − pressure economy. Higher is better.
- **Wicket-rate improvement** = pressure wickets per 24 legal balls − baseline wickets per 24 legal balls. Higher is better.

Each format-specific improvement is shrunk toward zero using the same \(n/(n+60)\) exposure factor, where \(n\) is pressure legal balls. The adjusted format-specific changes are then averaged across formats weighted by pressure balls. Each measure is standardized as a population z-score across the eligible bowler cohort, and the two z-scores receive equal weight:

**Bowling score** = [z(adjusted economy improvement) + z(adjusted wicket-rate improvement)] ÷ 2.

The bowler list is sorted in descending order of this composite score. A positive score means the player's combined, standardized improvements are above the eligible-cohort average; it is not an absolute probability or a percentage.

### 4.3 Eligibility and consistency

A player must meet all of the following thresholds to enter the relevant leaderboard:

- At least **60 pressure balls** (batter balls faced for batters; legal balls for bowlers).
- At least **120 non-pressure baseline balls** in formats with usable pressure/baseline comparisons.
- At least **three pressure matches** with a usable same-format baseline.

Thresholds are fixed before ranking; they are not relaxed to fill the top ten. The resulting cohorts contain 56 batters and 107 bowlers.

The **consistent match share** is calculated only in pressure matches with at least six role-specific balls. For batters it is the share of those matches in which match strike rate meets or exceeds the same-format baseline. For bowlers it is the share in which match economy is no higher than the same-format baseline. It is a supporting stability statistic, not an additional ranking weight.

### 4.4 Uncertainty intervals

For the reported top ten, 95% percentile bootstrap intervals are estimated from **500 resamples of pressure matches** using a fixed random seed. The player's baseline is held fixed. Batter intervals cover pressure-minus-baseline strike-rate change; bowler intervals cover baseline-minus-pressure economy. These are descriptive intervals, not intervals for the complete composite rank. They do not include baseline uncertainty, pressure-cutoff uncertainty, model-selection uncertainty, or possible dependence between matches.

---

## 5. Final batter rankings

The adjusted strike-rate change is the ranking score. Pressure and baseline strike rates, exposure, consistency, and match-bootstrap intervals provide context. “Consistent share” is reported as a proportion.

| Rank | Player | ID | Adjusted SR change | Pressure SR | Baseline SR |
|---:|---|---:|---:|---:|---:|
| 1 | David Miller | 1077 | 49.10 | 181.07 | 116.40 |
| 2 | Rinku Singh | 4708 | 46.70 | 190.40 | 129.31 |
| 3 | Dhruv Jurel | 7260 | 43.28 | 195.14 | 133.38 |
| 4 | Dasun Shanaka | 2436 | 43.10 | 171.74 | 111.05 |
| 5 | Tristan Stubbs | 20702 | 40.02 | 175.56 | 118.91 |
| 6 | Iftikhar Ahmed | 3056 | 38.77 | 180.95 | 105.26 |
| 7 | Ayush Badoni | 6460 | 37.29 | 167.97 | 113.20 |
| 8 | Moeen Ali | 1596 | 36.92 | 166.43 | 98.69 |
| 9 | Namboori Tilak Varma | 7897 | 36.81 | 175.50 | 126.26 |
| 10 | Sherfane Rutherford | 6725 | 36.14 | 176.61 | 122.71 |

| Rank | Player | Pressure balls | Pressure matches | Consistent share | 95% CI for SR change |
|---:|---|---:|---:|---:|---:|
| 1 | David Miller | 375 | 29 | 0.82 | 39.81 to 87.79 |
| 2 | Rinku Singh | 198 | 15 | 0.77 | 27.90 to 93.87 |
| 3 | Dhruv Jurel | 144 | 12 | 1.00 | 44.43 to 76.25 |
| 4 | Dasun Shanaka | 184 | 17 | 0.93 | 35.70 to 85.82 |
| 5 | Tristan Stubbs | 266 | 19 | 0.77 | 22.72 to 89.88 |
| 6 | Iftikhar Ahmed | 63 | 6 | 1.00 | 10.53 to 119.10 |
| 7 | Ayush Badoni | 128 | 11 | 1.00 | 26.43 to 82.28 |
| 8 | Moeen Ali | 143 | 12 | 1.00 | 47.19 to 79.75 |
| 9 | Namboori Tilak Varma | 351 | 23 | 0.87 | 26.45 to 69.32 |
| 10 | Sherfane Rutherford | 248 | 17 | 0.83 | 28.37 to 79.44 |

### Batter interpretation

David Miller ranks first because his pressure strike rate is substantially higher than his own non-pressure chase baseline, and the gain persists after the exposure-based shrinkage. His 375 pressure balls across 29 pressure matches provide a larger sample than several other top-ten entries. The table also makes sample differences visible: Iftikhar Ahmed meets the prespecified eligibility bar but has 63 pressure balls in six pressure matches, so his broad bootstrap interval signals greater uncertainty than the point rank alone suggests.

---

## 6. Final bowler rankings

The bowling score is the equal-weight average of the eligible-cohort z-scores for the two shrunk improvements. Economy improvement is baseline economy minus pressure economy; positive values indicate lower economy under pressure. Wicket improvement is the change in credited wickets per 24 legal balls.

| Rank | Player | ID | Bowling score (z) | Pressure econ. | Baseline econ. | Econ. improvement | Wickets / 24-ball improvement |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Vyshak Kumar | 4487 | 2.42 | 7.70 | 9.73 | 2.03 | 2.21 |
| 2 | Sam Curran | 4409 | 2.00 | 6.45 | 10.70 | 4.25 | 0.32 |
| 3 | Craig Young | 3720 | 1.67 | 8.38 | 10.08 | 1.70 | 1.16 |
| 4 | Rahul Chahar | 6161 | 1.61 | 7.23 | 9.04 | 1.81 | 0.67 |
| 5 | Deepak Chahar | 1813 | 1.51 | 8.38 | 8.91 | 0.53 | 1.57 |
| 6 | Vaibhav Arora | 8746 | 1.32 | 9.27 | 10.40 | 1.13 | 0.74 |
| 7 | Prince Yadav | 58246 | 1.29 | 7.67 | 10.34 | 2.67 | 0.03 |
| 8 | Axar Patel | 2876 | 1.28 | 6.12 | 8.17 | 2.05 | 0.00 |
| 9 | Washington Sundar | 4823 | 1.09 | 8.12 | 9.70 | 1.57 | 0.25 |
| 10 | Haris Rauf | 7364 | 1.02 | 8.62 | 9.02 | 0.41 | 0.65 |

| Rank | Player | Pressure balls | Pressure matches | Consistent share | 95% CI for economy improvement |
|---:|---|---:|---:|---:|---:|
| 1 | Vyshak Kumar | 60 | 5 | 0.75 | -2.11 to 3.85 |
| 2 | Sam Curran | 133 | 16 | 0.82 | 2.65 to 5.20 |
| 3 | Craig Young | 68 | 9 | 0.86 | 0.20 to 4.02 |
| 4 | Rahul Chahar | 117 | 10 | 0.89 | 0.39 to 3.21 |
| 5 | Deepak Chahar | 63 | 9 | 0.67 | -1.96 to 3.39 |
| 6 | Vaibhav Arora | 99 | 11 | 0.75 | -1.09 to 2.86 |
| 7 | Prince Yadav | 108 | 11 | 0.67 | 1.36 to 3.90 |
| 8 | Axar Patel | 149 | 13 | 0.82 | 0.31 to 3.61 |
| 9 | Washington Sundar | 130 | 10 | 0.89 | -0.70 to 3.06 |
| 10 | Haris Rauf | 133 | 13 | 0.62 | -1.31 to 2.27 |

### Bowler interpretation

Vyshak Kumar ranks first on the combined standardized improvement measure, with both a lower pressure economy than his own baseline and a strong wicket-rate improvement. His exposure is at the minimum threshold (60 balls over five matches), and his economy-improvement interval spans zero; the rank should therefore be read with appropriate sample-size caution. Sam Curran ranks second with the largest economy improvement in the top ten and a narrower interval that remains above zero, while his wicket-rate improvement is smaller. This illustrates why the rating combines economy and wicket-taking rather than rewarding only one dimension.

---

## 7. Data validation, exceptions, and safeguards

The Phase 1 audit was completed before pressure classification. It checked the six individual schemas, inferred data types, missing values, exact duplicates, candidate keys, foreign-key joins, delivery numbering, innings, extras, wickets, boundaries, and player-name consistency.

| Check | Observation | Treatment |
|---|---|---|
| Ball-by-ball match IDs | No ball-by-ball match IDs failed to join to `matches.csv` | Join validated |
| Matches without delivery data | 16; all are labeled abandoned | Retained in source; not usable as chase analyses |
| Matches missing innings 1 or 2 | 22 across the supplied files | Retained; ineligible when a valid chase state cannot be established |
| Innings numbered 3 or 4 | 38 delivery rows across 6 matches | Not used in second-innings chase rankings; not deleted |
| Delivery numbering | 8,429 rows have `over_ball_num > 6`; candidate delivery-sequence keys have no duplicates | Use `innings_ball_num` ordering for the modeled sequence; do not infer that the over-ball field is invalid |
| Extra metadata | 2 deliveries have nonzero extra runs without a type; 1 has a type but zero numeric extra fields | Runs are summed from numeric fields; legality uses the recorded type and is noted as an assumption |
| Wicket metadata | 1 wicket lacks a dismissed player, identified as `Retire Out`; 12 rows have a dismissed-player ID without the wicket flag | Credited wickets use the dismissal category rules, not player ID presence alone |
| Boundary flags | No four/six overlap and no mismatch between boundary flag and batter runs | Flags retained as supplied |
| Player names | One mapped-name variation for a player ID; no bowler-name mismatches | Player ID remains canonical; names are display labels |
| Teams and players mapping | Five team pairs absent from mapping; one player/team/competition key missing from mapping across five playing-XI rows | Reported, not fabricated or silently joined |
| Candidate keys | Most tested candidate keys are unique; the proposed playing-XI composite is not | Do not assume it is a unique key |
| Chase outcome check | 808 of 808 eligible targets agree with the observed result check | Passed |

The `over_ball_num` values above six are not automatically treated as corruption: their semantics are not documented. The analysis sorts by `innings_ball_num`, which is unique within match and innings in the Phase 1 check. Innings 3/4 may represent super overs, but that interpretation is not provable from the supplied columns; the ranking scope excludes them regardless.

No player names, statistics, outcomes, or missing relationships were fabricated. No source records were deleted or overwritten. Analysis exclusions are explicit and correspond to the defined second-innings chase scope or the inability to construct a valid target/state.

---

## 8. Limitations and interpretation

1. **Chase-only scope.** Pressure in the first innings, defending first-innings totals, tied-match endgames, and other non-chase contexts is not modeled.
2. **Pressure is an operational definition.** The index weights and 75th-percentile cutoff are transparent choices, not a universal psychological measure of pressure. A different reasonable definition could change labels and ranks.
3. **Cohort-relative thresholds.** Required-run-rate percentiles and pressure cutoffs are calculated within the supplied IPL/T20I format cohorts. Future seasons or a changed sample can shift those thresholds.
4. **No opponent or venue adjustment.** Opposition strength, ground, pitch, toss, weather, match phase labels, and win-probability trajectories are not included.
5. **Delivery labels are imperfect.** Legal-ball status is inferred from extras text because a dedicated legal-ball field is absent. Unusual or inconsistently labeled deliveries may affect balls, rates, and state.
6. **Revised innings interpretation.** `second_inn_revised_overs` is interpreted as a legal-ball limit because its observed values are six-ball multiples. This assumption should be confirmed with the data provider.
7. **Baseline and shrinkage choices.** The 60-ball shrinkage constant and 60/120/three-match eligibility thresholds are modeling choices. They improve transparency and comparability but are not uniquely optimal.
8. **Cross-format pooling.** Comparisons are formed within each format and then exposure-weighted; this reduces direct rate-mixing but does not remove all structural differences between IPL and international cricket.
9. **Bowler composite depends on cohort.** Z-scores are relative to the eligible bowler cohort; a score is not directly comparable across a different cohort or season.
10. **Uncertainty is partial.** Bootstrap intervals resample pressure matches while holding baselines and cutoffs fixed. They do not represent uncertainty in rank order or the entire analysis pipeline. Overlapping intervals should not be read as proof that one player is definitively better.
11. **Descriptive, not causal.** Better measured performance in labeled pressure deliveries does not show that pressure caused the performance or guarantee future success.
12. **Data coverage.** Rankings describe only the supplied snapshot and available mapped records. They should not be interpreted as complete career records outside these CSVs.

The interactive dashboard separately presents observed career, season, format, pressure, contribution-share, and match-record summaries. These descriptive profile metrics use the available records and are distinct from the pressure leaderboard eligibility/rating. A team-run contribution share is a share of recorded runs, not a causal measure of wins or a complete measure of a player's value.

---

## 9. Reproducibility and end-to-end procedure

### 9.1 Project contents

The analysis is implemented in:

- `src/data_exploration.py` — loads the six source CSVs, profiles schemas, missingness, duplicate rows, and sample records.
- `src/data_validation.py` — tests candidate keys, joins, and cricket-specific data checks.
- `src/pressure_analysis.py` — builds chase states, classifies role-specific pressure, computes player baselines, ratings, leaderboards, and the methodology report.
- `src/dashboard.py` — assembles the standalone interactive dashboard and refreshes the ranking deliverables.
- `tests/` — validation and analysis regression tests.

### 9.2 Run from the project root

The scripts prefer a `data/` directory containing all six files and also support the supplied files at the project root.

```powershell
python --version
python -m pip install pandas numpy
python src/data_exploration.py
python src/data_validation.py
python src/pressure_analysis.py
python src/dashboard.py
python -m pytest -q
```

The analysis was developed and verified with Python 3.12.9, pandas 2.2.3, and pytest 8.3.5. The same scripts can be run with compatible Python/pandas/numpy versions; the exact environment and input snapshot should be recorded if results are regenerated for submission.

### 9.3 Generated deliverables

The project generates:

- `reports/phase1_report.md` — detailed dataset exploration and quality audit.
- `reports/phase2_methodology_report.md` — analysis methods, diagnostics, and ranked evidence.
- `reports/phase2_batter_top10.csv` and `reports/phase2_bowler_top10.csv` — ordered submission lists with player IDs and supporting statistics.
- `reports/phase2_batter_leaderboard.csv` and `reports/phase2_bowler_leaderboard.csv` — all eligible ranked players.
- `reports/dashboard.html` — offline interactive player and analytics dashboard.
- `reports/competition_submission.md` — this end-to-end methodology and results document.

The pressure-analysis command regenerates the top-ten/full leaderboards and phase-two methodology report. The dashboard command regenerates the standalone dashboard and calls the pressure-analysis pipeline. Source CSVs are read as inputs and are not changed.

### 9.4 Verification completed

- The project test suite passed: **8 tests passed**.
- The target/winner consistency check passed for **808 / 808** eligible matches.
- The standalone dashboard was opened and checked in a browser. Player search and selection, format filtering, season/match records, and player-profile/match-record export actions were exercised.
- The ranked CSVs contain ten distinct entries in each category, with the player IDs shown in the tables above for matching the Unstop selection fields.

---

## 10. Submission checklist

- [ ] Enter the batter names in ranks 1–10 exactly as listed in Section 5.
- [ ] Enter the bowler names in ranks 1–10 exactly as listed in Section 6.
- [ ] Do not repeat a player within either list.
- [ ] Match the displayed player names to the player IDs in this report/CSV if the Unstop dropdown contains similar aliases.
- [ ] Replace the candidate/team placeholder on the cover before uploading.
- [ ] Upload the final document as the methodology report; keep the two top-10 CSVs and full leaderboards as supporting audit files.
- [ ] Optionally include a dashboard screenshot or short walkthrough if desired; the competition brief makes this optional.

---

## Appendix A. Project artifacts

- Methodology report: `reports/phase2_methodology_report.md`
- Data exploration and validation: `reports/phase1_report.md`
- Batter top ten: `reports/phase2_batter_top10.csv`
- Bowler top ten: `reports/phase2_bowler_top10.csv`
- Full eligible batter leaderboard: `reports/phase2_batter_leaderboard.csv`
- Full eligible bowler leaderboard: `reports/phase2_bowler_leaderboard.csv`
- Interactive dashboard: `reports/dashboard.html`

This document is based on the supplied Round 1 problem statement, the six provided CSV files, the implemented Python analysis, its generated outputs, and the completed tests. The full CSVs and reports remain the audit trail for detailed column-level profiles and diagnostics.
