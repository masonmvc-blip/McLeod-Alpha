# Validation Lab Report - 2026-07-15T00:00:00+00:00

## Executive Summary
Replay points: 6
Hit rate: 66.67%
Alpha vs SPY: -0.03%
Confidence accuracy: 66.67%

## Historical Replay Results
| Date | CIO Return | SPY Return | Equal Weight | Benchmark | Confidence |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-07-10 | 1.20% | 1.00% | 0.90% | 0.80% | 72.0000 |
| 2026-07-11 | 0.60% | 0.40% | 0.50% | 0.40% | 70.0000 |
| 2026-07-12 | -0.80% | -0.60% | -0.70% | -0.60% | 68.0000 |
| 2026-07-13 | -1.40% | -1.00% | -1.10% | -1.00% | 58.0000 |
| 2026-07-14 | 0.90% | 0.80% | 0.70% | 0.80% | 56.0000 |
| 2026-07-15 | 0.40% | 0.50% | 0.50% | 0.40% | 54.0000 |

## Benchmark Comparison
- Alpha vs SPY: -0.03%
- Alpha vs equal weight: 0.02%
- Alpha vs benchmark portfolio: 0.02%
- Sharpe: 2.5492
- Sortino: 7.9373
- Max drawdown: 2.19%
- Turnover: 0.2400
- Average holding period: 3.8500
- Sector attribution:
  - Consumer: 0.90%
  - Energy: -0.67%
  - Semiconductors: 0.90%
  - Technology: 0.25%

## Calibration
- Calibration error: 7.0000
- Confidence accuracy: 66.67%
- Replacement accuracy: 33.33%
- Portfolio allocation quality: 70.0700
- Buckets:
  - 0-20: count=0, avg_conf=0.0000, win_rate=0.0000, error=0.0000
  - 20-40: count=0, avg_conf=0.0000, win_rate=0.0000, error=0.0000
  - 40-60: count=3, avg_conf=56.0000, win_rate=66.6667, error=10.6667
  - 60-80: count=3, avg_conf=70.0000, win_rate=66.6667, error=3.3333
  - 80-100: count=0, avg_conf=0.0000, win_rate=0.0000, error=0.0000

## Drift Analysis
- score_drift: baseline=72.6667 recent=58.3333 delta=-14.3333 significant=true
- confidence_drift: baseline=70.0000 recent=56.0000 delta=-14.0000 significant=true
- recommendation_drift: baseline=1.6667 recent=1.0000 delta=-0.6667 significant=false
- portfolio_drift: baseline=0.3157 recent=0.2829 delta=-0.0329 significant=false
- thesis_drift: baseline=75.0000 recent=59.3333 delta=-15.6667 significant=true

## Failure Cases
- 2026-07-12: CIO return -0.80%
- 2026-07-13: CIO return -1.40%

## Success Cases
- 2026-07-10: CIO return +1.20%
- 2026-07-11: CIO return +0.60%
- 2026-07-14: CIO return +0.90%
- 2026-07-15: CIO return +0.40%

## Recommended Improvements
- Investigate statistically significant drifts across score/confidence/recommendation/portfolio/thesis dimensions.
- Revisit replacement candidate selection quality.
