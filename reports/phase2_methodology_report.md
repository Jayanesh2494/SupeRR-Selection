# SupeRR Selector Season 2 — Phase 2 Pressure Analysis

## Scope and reproducibility

This phase builds a chase-context pressure classification, compares each player with their own non-pressure chase baseline, and generates the top-10 batter and bowler leaderboards from the supplied data. Run `python src/pressure_analysis.py` from the project root to regenerate the CSVs and this report. Source CSVs are read-only inputs.

The player pool includes competitions whose format is `T20I` and competitions named exactly `IPL YYYY`. Other `T20` competitions are excluded to match the challenge scope. Main second innings are used; first-innings, super-over, abandoned, no-result, and matches without an observed winner are not used in rankings.

## Pressure definition

Pressure is measured only in a live second-innings chase. At the start of each delivery, the pipeline calculates runs required, legal balls remaining, wickets already lost, and required run rate. The default innings budget is 120 legal balls; the supplied `second_inn_revised_overs` values are treated as legal-ball limits because all observed non-null values are positive multiples of six (30–114).

The chase target is `revised_target` when supplied; otherwise it is first-innings team runs plus one. First-innings team runs are calculated as `runs + extras1_runs + extras_2_runs` per delivery. Matches labelled D/L or DLS without an explicit revised target are excluded. Wide and `Overstep` deliveries do not consume a legal ball; all other observed extras types are treated as legal, since the files do not provide a separate legal-ball flag.

The explicit or derived target was checked against the observed winner and second-innings total: **808 of 808 eligible matches agreed**. Rows after the chase target was already reached or the innings ball quota was exhausted are excluded from pressure-state modeling and counted in diagnostics; source records are retained.

Required-run-rate percentile is calculated within each format (IPL or T20I). The batting-pressure index is **0.60 × required-rate percentile + 0.25 × wickets lost / 10 + 0.15 × innings elapsed fraction**. The bowling-pressure index is **0.50 × (1 − required-rate percentile) + 0.30 × (1 − wickets lost / 10) + 0.20 × innings elapsed fraction**. The top quartile of each index within each format is labelled pressure. The separate indices reflect high chase demand for batters and a late, viable chase threat for defending bowlers. Delivery-level threshold values and counts are recorded in the report diagnostics.

## Performance comparison and eligibility

Only batter-striker events and bowler-assigned events in second innings are measured. Batter strike rate is batter runs per batter-faced ball × 100; wides are not balls faced, while no-balls are. Batter ranking uses the pressure-minus-baseline strike-rate change, shrunk toward zero by `pressure balls / (pressure balls + 60)`. The pressure baseline consists of the same player's non-pressure chase deliveries in the same format.

Bowler runs conceded are batter runs plus recorded extras, excluding byes, legbyes, and penalty extras. Economy is conceded runs per legal ball × 6. The supplied `Overstep` label is treated as a no-ball and is excluded from legal-ball counts. Credited wickets include Caught, Bowled, LBW, Stump, and Hit Wicket; run-outs and other non-bowler dismissals are excluded. Each format-specific economy improvement (baseline economy minus pressure economy) and wicket-rate improvement (pressure minus baseline credited wickets per 24 legal balls) is shrunk by the same exposure formula. If a player appears in both formats, their format-specific changes are averaged weighted by pressure balls, so each comparison uses their own baseline in that format.

Eligibility requires at least 60 pressure balls, 120 baseline balls, and 3 pressure matches with a usable same-format baseline. Batter rank is descending reliability-adjusted strike-rate change. Bowler rank is descending average of the population z-scores for the two shrunk improvements (equal weights). These scores compare players in this eligible cohort; a positive change means better performance than that player's baseline. The `consistent match share` is calculated over pressure matches with at least 6 role-specific balls: the share where the player's pressure strike rate is at least their same-format baseline (batters) or pressure economy is no higher than baseline (bowlers).

Top-10 uncertainty intervals are 95% percentile bootstrap intervals from 500 resamples of the player's pressure matches, with a fixed seed; the baseline is held fixed. Batter intervals show strike-rate change, and bowler intervals show economy improvement. They are descriptive and do not account for uncertainty in the baseline or pressure thresholds.

## Top 10 batters

| Rank | Player | Adjusted SR change | Pressure SR | Baseline SR | Pressure balls | Pressure matches | Consistent match share | 95% CI low | 95% CI high |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | David Miller | 49.10 | 181.07 | 116.40 | 375.00 | 29 | 0.82 | 39.81 | 87.79 |
| 2 | Rinku Singh | 46.70 | 190.40 | 129.31 | 198.00 | 15 | 0.77 | 27.90 | 93.87 |
| 3 | Dhruv Jurel | 43.28 | 195.14 | 133.38 | 144.00 | 12 | 1.00 | 44.43 | 76.25 |
| 4 | Dasun Shanaka | 43.10 | 171.74 | 111.05 | 184.00 | 17 | 0.93 | 35.70 | 85.82 |
| 5 | Tristan Stubbs | 40.02 | 175.56 | 118.91 | 266.00 | 19 | 0.77 | 22.72 | 89.88 |
| 6 | Iftikhar Ahmed | 38.77 | 180.95 | 105.26 | 63.00 | 6 | 1.00 | 10.53 | 119.10 |
| 7 | Ayush Badoni | 37.29 | 167.97 | 113.20 | 128.00 | 11 | 1.00 | 26.43 | 82.28 |
| 8 | Moeen Ali | 36.92 | 166.43 | 98.69 | 143.00 | 12 | 1.00 | 47.19 | 79.75 |
| 9 | Namboori Tilak Varma | 36.81 | 175.50 | 126.26 | 351.00 | 23 | 0.87 | 26.45 | 69.32 |
| 10 | Sherfane Rutherford | 36.14 | 176.61 | 122.71 | 248.00 | 17 | 0.83 | 28.37 | 79.44 |

## Top 10 bowlers

| Rank | Player | Bowling score (z) | Pressure economy | Baseline economy | Economy improvement | Wicket improvement / 24 balls | Pressure balls | Pressure matches | Consistent match share | 95% CI low econ | 95% CI high econ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Vyshak Kumar | 2.42 | 7.70 | 9.73 | 2.03 | 2.21 | 60.00 | 5 | 0.75 | -2.11 | 3.85 |
| 2 | Sam Curran | 2.00 | 6.45 | 10.70 | 4.25 | 0.32 | 133.00 | 16 | 0.82 | 2.65 | 5.20 |
| 3 | Craig Young | 1.67 | 8.38 | 10.08 | 1.70 | 1.16 | 68.00 | 9 | 0.86 | 0.20 | 4.02 |
| 4 | Rahul Chahar | 1.61 | 7.23 | 9.04 | 1.81 | 0.67 | 117.00 | 10 | 0.89 | 0.39 | 3.21 |
| 5 | Deepak Chahar | 1.51 | 8.38 | 8.91 | 0.53 | 1.57 | 63.00 | 9 | 0.67 | -1.96 | 3.39 |
| 6 | Vaibhav Arora | 1.32 | 9.27 | 10.40 | 1.13 | 0.74 | 99.00 | 11 | 0.75 | -1.09 | 2.86 |
| 7 | Prince Yadav | 1.29 | 7.67 | 10.34 | 2.67 | 0.03 | 108.00 | 11 | 0.67 | 1.36 | 3.90 |
| 8 | Axar Patel | 1.28 | 6.12 | 8.17 | 2.05 | 0.00 | 149.00 | 13 | 0.82 | 0.31 | 3.61 |
| 9 | Washington Sundar | 1.09 | 8.12 | 9.70 | 1.57 | 0.25 | 130.00 | 10 | 0.89 | -0.70 | 3.06 |
| 10 | Haris Rauf | 1.02 | 8.62 | 9.02 | 0.41 | 0.65 | 133.00 | 13 | 0.62 | -1.31 | 2.27 |

## Cohort and data diagnostics

- Eligible batter cohort: **56**; eligible bowler cohort: **107**.
- Requested top-10 returned: **10 batters** and **10 bowlers**. If fewer than 10 meet the pre-set eligibility thresholds, the lists remain shorter rather than lowering the bar after seeing results.
- The full eligible tables are saved separately as CSVs for auditability.

```json
{
  "source_match_rows": 883,
  "selected_competitions": [
    {
      "comp_id": 3395,
      "comp_name": "South Africa in New Zealand T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3405,
      "comp_name": "Afghanistan v Sri Lanka T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3465,
      "comp_name": "India in Zimbabwe T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3568,
      "comp_name": "Bangladesh in Zimbabwe T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3482,
      "comp_name": "Australia in Bangladesh T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3464,
      "comp_name": "Sri Lanka in West Indies T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3765,
      "comp_name": "Sri Lanka in Pakistan T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3739,
      "comp_name": "India in Japan T20I Match 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3787,
      "comp_name": "Afghanistan v Zimbabwe T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3713,
      "comp_name": "Afghanistan vs India in India T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3690,
      "comp_name": "India in New Zealand T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3473,
      "comp_name": "United Arab Emirates in Nepal T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 1358,
      "comp_name": "IPL 2022",
      "match_format": "T20"
    },
    {
      "comp_id": 1715,
      "comp_name": "IPL 2023",
      "match_format": "T20"
    },
    {
      "comp_id": 2193,
      "comp_name": "IPL 2024",
      "match_format": "T20"
    },
    {
      "comp_id": 2725,
      "comp_name": "IPL 2025",
      "match_format": "T20"
    },
    {
      "comp_id": 3298,
      "comp_name": "IPL 2026",
      "match_format": "T20"
    },
    {
      "comp_id": 1611,
      "comp_name": "England in Australia T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1331,
      "comp_name": "England in West Indies T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1551,
      "comp_name": "Asia Cup T20 Qualifiers 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1531,
      "comp_name": "South Africa vs Ireland T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1523,
      "comp_name": "Bangladesh in Zimbabwe T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1452,
      "comp_name": "Bangladesh in West Indies T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1517,
      "comp_name": "South Africa in England T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1458,
      "comp_name": "Afghanistan in Zimbabwe T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1537,
      "comp_name": "New Zealand in West Indies T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1494,
      "comp_name": "India in England T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1345,
      "comp_name": "Sri Lanka in Australia T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1533,
      "comp_name": "Mens Twenty20 Asia Cup 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1335,
      "comp_name": "West Indies in India T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1603,
      "comp_name": "West Indies in Australia T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1474,
      "comp_name": "India in Ireland T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1534,
      "comp_name": "New Zealand in Netherlands T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1439,
      "comp_name": "South Africa in India T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1601,
      "comp_name": "Bangladesh in United Arab Emirates T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1435,
      "comp_name": "Australia in Sri Lanka T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1499,
      "comp_name": "India in West Indies T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1512,
      "comp_name": "New Zealand in Ireland T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1595,
      "comp_name": "England in Pakistan T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1543,
      "comp_name": "Afghanistan in Ireland T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1584,
      "comp_name": "Australia in India T20I Series 2022",
      "match_format": "T20I"
    },
    {
      "comp_id": 1646,
      "comp_name": "India in New Zealand T20I Series 2022/23",
      "match_format": "T20I"
    },
    {
      "comp_id": 1599,
      "comp_name": "South Africa in India T20I Series 2022/23",
      "match_format": "T20I"
    },
    {
      "comp_id": 1608,
      "comp_name": "New Zealand T20I Tri Series 2022/23",
      "match_format": "T20I"
    },
    {
      "comp_id": 1698,
      "comp_name": "Sri Lanka in India T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 2047,
      "comp_name": "India in South Africa T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1719,
      "comp_name": "Sri Lanka in New Zealand T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 2058,
      "comp_name": "Bangladesh in New Zealand T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1709,
      "comp_name": "Ireland in Zimbabwe T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1792,
      "comp_name": "Afghanistan v Pakistan T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1742,
      "comp_name": "England in Bangladesh T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1769,
      "comp_name": "Ireland in Bangladesh T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1718,
      "comp_name": "West Indies in South Africa T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1799,
      "comp_name": "New Zealand in Pakistan T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1999,
      "comp_name": "New Zealand in England T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 2000,
      "comp_name": "Australia in South Africa T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 2046,
      "comp_name": "Australia in India T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1998,
      "comp_name": "India in Ireland T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 2048,
      "comp_name": "England in West Indies T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1700,
      "comp_name": "New Zealand in India T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1885,
      "comp_name": "Afghanistan in Bangladesh T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1997,
      "comp_name": "New Zealand in United Arab Emirates T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 1913,
      "comp_name": "India in West Indies T20I Series 2023",
      "match_format": "T20I"
    },
    {
      "comp_id": 2188,
      "comp_name": "Ireland in Zimbabwe T20I Series 2023/24",
      "match_format": "T20I"
    },
    {
      "comp_id": 2722,
      "comp_name": "Pakistan in Zimbabwe T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2059,
      "comp_name": "Afghanistan in India T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2716,
      "comp_name": "New Zealand in Sri Lanka T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2512,
      "comp_name": "Bangladesh in India T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2267,
      "comp_name": "Afghanistan in Sri Lanka T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2229,
      "comp_name": "Zimbabwe in Sri Lanka T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2753,
      "comp_name": "Afghanistan in Zimbabwe T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2561,
      "comp_name": "Australia in Scotland T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2692,
      "comp_name": "West Indies in Sri Lanka T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2542,
      "comp_name": "India in Sri Lanka T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2305,
      "comp_name": "Sri Lanka in Bangladesh T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2398,
      "comp_name": "Netherlands Tri-Nation T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2605,
      "comp_name": "Netherlands Tri-Nation T20I Series [Aug 2024] 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2060,
      "comp_name": "Pakistan in New Zealand T20I series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2453,
      "comp_name": "South Africa in West Indies T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2395,
      "comp_name": "Pakistan in Ireland T20I series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2387,
      "comp_name": "Pakistan in Australia T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2457,
      "comp_name": "Bangladesh in West Indies T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2548,
      "comp_name": "Australia in England T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2354,
      "comp_name": "Pakistan in England T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2350,
      "comp_name": "New Zealand in Pakistan T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2371,
      "comp_name": "Zimbabwe in Bangladesh T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2062,
      "comp_name": "Australia in New Zealand T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2269,
      "comp_name": "Afghanistan v Ireland T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2372,
      "comp_name": "India in Zimbabwe T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2455,
      "comp_name": "England in West Indies T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2061,
      "comp_name": "West Indies in Australia T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2452,
      "comp_name": "South Africa in West Indies T20I Series [May 2024] 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2442,
      "comp_name": "Pakistan in South Africa T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2718,
      "comp_name": "India in South Africa T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2562,
      "comp_name": "Ireland v South Africa T20I Series 2024",
      "match_format": "T20I"
    },
    {
      "comp_id": 2755,
      "comp_name": "Sri Lanka in New Zealand T20I Series 2024/25",
      "match_format": "T20I"
    },
    {
      "comp_id": 3074,
      "comp_name": "Pakistan in Bangladesh T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3197,
      "comp_name": "Australia in New Zealand T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3241,
      "comp_name": "West Indies in Bangladesh T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3282,
      "comp_name": "West Indies in New Zealand T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3190,
      "comp_name": "Nepal v West Indies T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2801,
      "comp_name": "Ireland in Zimbabwe T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2626,
      "comp_name": "West Indies in England T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3162,
      "comp_name": "Sri Lanka in Zimbabwe T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3163,
      "comp_name": "Netherlands in Bangladesh T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3254,
      "comp_name": "Afghanistan in Zimbabwe T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2874,
      "comp_name": "Australia in West Indies T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2793,
      "comp_name": "Pakistan in New Zealand T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3020,
      "comp_name": "Bangladesh in Sri Lanka T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3133,
      "comp_name": "Asia Cup 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2912,
      "comp_name": "South Africa in Australia T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3251,
      "comp_name": "Ireland in Bangladesh T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3223,
      "comp_name": "South Africa in Pakistan T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2975,
      "comp_name": "Bangladesh in United Arab Emirates T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2873,
      "comp_name": "West Indies in Ireland T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2513,
      "comp_name": "England in India T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2940,
      "comp_name": "India in Bangladesh T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3226,
      "comp_name": "England in New Zealand T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2921,
      "comp_name": "South Africa in India T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2973,
      "comp_name": "Bangladesh in Pakistan T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3159,
      "comp_name": "United Arab Emirates T20I Tri-Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2628,
      "comp_name": "South Africa in England T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2875,
      "comp_name": "Pakistan in West Indies T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3174,
      "comp_name": "England in Ireland T20I series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3288,
      "comp_name": "Pakistan T20I Tri-Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3228,
      "comp_name": "Afghanistan v Bangladesh T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 2915,
      "comp_name": "India in Australia T20I Series 2025",
      "match_format": "T20I"
    },
    {
      "comp_id": 3358,
      "comp_name": "Australia in Pakistan T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3450,
      "comp_name": "West Indies in India T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3331,
      "comp_name": "Afghanistan v West Indies T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3317,
      "comp_name": "Pakistan in Sri Lanka T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3329,
      "comp_name": "New Zealand in India T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3126,
      "comp_name": "India in England T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3313,
      "comp_name": "Ireland in United Arab Emirates T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3128,
      "comp_name": "Sri Lanka in England T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3446,
      "comp_name": "India in Ireland T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 2906,
      "comp_name": "West Indies in South Africa T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3334,
      "comp_name": "England in Sri Lanka T20I Series 2026",
      "match_format": "T20I"
    },
    {
      "comp_id": 3433,
      "comp_name": "New Zealand in Bangladesh T20I Series 2026",
      "match_format": "T20I"
    }
  ],
  "selected_competition_match_rows": 853,
  "eligible_chase_matches": 808,
  "excluded_matches_by_reason": {
    "missing_first_innings": 16,
    "missing_second_innings": 22,
    "missing_winner": 3,
    "abandoned_or_no_result": 0,
    "missing_target": 0,
    "revised_target_missing_for_dls": 4
  },
  "chase_delivery_rows_before_state_filter": 91508,
  "chase_delivery_rows_excluded_after_target_or_quota": 55,
  "chase_delivery_rows_after_target": 12,
  "matches_with_delivery_rows_after_target": 1,
  "after_target_examples": [
    {
      "match_id": 48610,
      "innings_ball_num": 82,
      "runs_before": 115,
      "target": 115.0,
      "balls_remaining": 12.0
    },
    {
      "match_id": 48610,
      "innings_ball_num": 83,
      "runs_before": 115,
      "target": 115.0,
      "balls_remaining": 11.0
    },
    {
      "match_id": 48610,
      "innings_ball_num": 84,
      "runs_before": 116,
      "target": 115.0,
      "balls_remaining": 10.0
    },
    {
      "match_id": 48610,
      "innings_ball_num": 85,
      "runs_before": 120,
      "target": 115.0,
      "balls_remaining": 9.0
    },
    {
      "match_id": 48610,
      "innings_ball_num": 86,
      "runs_before": 120,
      "target": 115.0,
      "balls_remaining": 8.0
    },
    {
      "match_id": 48610,
      "innings_ball_num": 87,
      "runs_before": 120,
      "target": 115.0,
      "balls_remaining": 7.0
    },
    {
      "match_id": 48610,
      "innings_ball_num": 88,
      "runs_before": 120,
      "target": 115.0,
      "balls_remaining": 6.0
    },
    {
      "match_id": 48610,
      "innings_ball_num": 89,
      "runs_before": 120,
      "target": 115.0,
      "balls_remaining": 5.0
    },
    {
      "match_id": 48610,
      "innings_ball_num": 90,
      "runs_before": 122,
      "target": 115.0,
      "balls_remaining": 4.0
    },
    {
      "match_id": 48610,
      "innings_ball_num": 91,
      "runs_before": 123,
      "target": 115.0,
      "balls_remaining": 3.0
    }
  ],
  "chase_delivery_rows_after_innings_quota": 43,
  "matches_with_delivery_rows_after_innings_quota": 33,
  "after_innings_quota_examples": [
    {
      "match_id": 14098,
      "innings_ball_num": 125,
      "legal_balls_bowled": 120,
      "innings_balls": 120.0,
      "extras_type": NaN
    },
    {
      "match_id": 14102,
      "innings_ball_num": 130,
      "legal_balls_bowled": 120,
      "innings_balls": 120.0,
      "extras_type": NaN
    },
    {
      "match_id": 14115,
      "innings_ball_num": 129,
      "legal_balls_bowled": 120,
      "innings_balls": 120.0,
      "extras_type": NaN
    },
    {
      "match_id": 14127,
      "innings_ball_num": 128,
      "legal_balls_bowled": 120,
      "innings_balls": 120.0,
      "extras_type": NaN
    },
    {
      "match_id": 14159,
      "innings_ball_num": 129,
      "legal_balls_bowled": 120,
      "innings_balls": 120.0,
      "extras_type": NaN
    },
    {
      "match_id": 14159,
      "innings_ball_num": 130,
      "legal_balls_bowled": 121,
      "innings_balls": 120.0,
      "extras_type": NaN
    },
    {
      "match_id": 15796,
      "innings_ball_num": 131,
      "legal_balls_bowled": 120,
      "innings_balls": 120.0,
      "extras_type": "byes"
    },
    {
      "match_id": 15796,
      "innings_ball_num": 132,
      "legal_balls_bowled": 121,
      "innings_balls": 120.0,
      "extras_type": NaN
    },
    {
      "match_id": 16424,
      "innings_ball_num": 129,
      "legal_balls_bowled": 120,
      "innings_balls": 120.0,
      "extras_type": NaN
    },
    {
      "match_id": 17555,
      "innings_ball_num": 124,
      "legal_balls_bowled": 120,
      "innings_balls": 120.0,
      "extras_type": NaN
    }
  ],
  "chase_delivery_rows_used": 91453,
  "target_and_winner_consistency": {
    "matches_checked": 808,
    "consistent_matches": 808,
    "inconsistent_matches": 0,
    "inconsistent_examples": []
  },
  "score_definition": "team runs per delivery = runs + extras1_runs + extras_2_runs",
  "revised_second_innings_limits_are_six_ball_multiples": true,
  "pressure_classification": {
    "batting_under_pressure": {
      "T20": {
        "pressure_rows": 10489,
        "eligible_rows": 41953,
        "cutoff": 0.5981963149238434
      },
      "T20I": {
        "pressure_rows": 12375,
        "eligible_rows": 49500,
        "cutoff": 0.6047594696969697
      }
    },
    "bowling_under_pressure": {
      "T20": {
        "pressure_rows": 10491,
        "eligible_rows": 41953,
        "cutoff": 0.7031201185453564
      },
      "T20I": {
        "pressure_rows": 12375,
        "eligible_rows": 49500,
        "cutoff": 0.6943396464646465
      }
    }
  }
}
```

## Limitations

- This definition is chase-only. It does not label first-innings situations, batter-vs-bowler matchups, required-rate trajectory, match win probability, pitch conditions, or opponent strength.
- Pressure labels are relative to the observed cohort's top quartile in each format, not a universal cricket threshold. The index coefficients and 75th-percentile cutoff are modeling choices, not official rules.
- Innings termination and legal-ball semantics are inferred from the CSVs. Only `wide` and `Overstep` are explicitly treated as illegal deliveries; two rows have extras without an extras type and remain included under the documented default.
- Names are sourced from the competition-team-player mapping. If one player ID has aliases, the most frequent mapped name is displayed; source IDs remain the analytical key.
- Batter strike rate does not reward not-out survival, and bowler scores weight economy and credited wickets equally after standardization. The minimum exposure and shrinkage reduce, but do not remove, small-sample and selection effects.
- Bootstrap intervals resample pressure matches but hold the baseline and pressure cutoff fixed. They should not be read as proof of causality or as a complete uncertainty estimate.
- A player's top-10 rank is conditional on the supplied data, chosen pressure definition, eligibility thresholds, and scoring formula; it is not a forecast of future performance.
