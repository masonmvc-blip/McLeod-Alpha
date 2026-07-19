# CIO Performance Lab Report - 2026-07-20T00:00:00+00:00

## Executive Summary
Closed recommendations: 7
Overall win rate: 71.4%
Directional accuracy: 71.4%
Benchmark alpha: -0.7%
Confidence calibration score: 80.71

## Recommendation Accuracy
| Metric | Value |
| --- | ---: |
| Recommendation precision | 100.0% |
| Recommendation recall | 60.0% |
| Average return | 0.4% |
| Median return | 0.0% |
| Average holding period | 2.00 days |
| Portfolio alpha | 6.0% |
| Buy accuracy | 50.0% |
| Trim accuracy | 100.0% |
| Cash timing accuracy | 100.0% |
| Thesis prediction accuracy | 83.3% |
| Replacement accuracy | 50.0% |

## Confidence Calibration
| Bucket | Count | Avg Return | Benchmark Alpha | Win Rate | Calibration Error |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0-20 | 1 | -3.0% | -4.0% | 0.0% | 10.00 |
| 20-40 | 1 | 0.0% | -1.0% | 100.0% | 70.00 |
| 40-60 | 2 | -3.0% | -5.0% | 50.0% | 0.00 |
| 60-80 | 1 | -5.0% | -3.0% | 100.0% | 30.00 |
| 80-100 | 2 | 8.5% | 6.5% | 100.0% | 12.50 |

## Alpha Attribution
### Best Performing Recommendation Types

| Label | Count | Avg Return | Benchmark Alpha | Win Rate | Avg Hold (days) |
| --- | ---: | ---: | ---: | ---: | ---: |
| hold | 1 | 2.0% | 2.0% | 100.0% | 2.00 |
| buy | 4 | 1.5% | -0.8% | 50.0% | 2.00 |
| cash | 1 | 0.0% | -1.0% | 100.0% | 2.00 |

### Worst Performing Recommendation Types

| Label | Count | Avg Return | Benchmark Alpha | Win Rate | Avg Hold (days) |
| --- | ---: | ---: | ---: | ---: | ---: |
| trim | 1 | -5.0% | -3.0% | 100.0% | 2.00 |
| cash | 1 | 0.0% | -1.0% | 100.0% | 2.00 |
| buy | 4 | 1.5% | -0.8% | 50.0% | 2.00 |

### Best Sectors

| Label | Count | Avg Return | Benchmark Alpha | Win Rate | Avg Hold (days) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Consumer Internet | 1 | 5.0% | 5.0% | 100.0% | 2.00 |
| Semiconductors | 1 | 2.0% | 2.0% | 100.0% | 2.00 |
| Unknown | 1 | 0.0% | -1.0% | 100.0% | 2.00 |

### Worst Sectors

| Label | Count | Avg Return | Benchmark Alpha | Win Rate | Avg Hold (days) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Speculative | 1 | -3.0% | -4.0% | 0.0% | 2.00 |
| Energy | 1 | -5.0% | -3.0% | 100.0% | 2.00 |
| Technology | 2 | 2.0% | -2.0% | 50.0% | 2.00 |

## Failure Analysis
- MSFT buy | confidence 5500.0% | benchmark alpha -12.0% | Buy MSFT
- LOWC buy | confidence 1000.0% | benchmark alpha -4.0% | Buy LOWC

## Success Analysis
- AAPL buy | confidence 9000.0% | benchmark alpha 8.0% | Buy AAPL
- MELI buy | confidence 8500.0% | benchmark alpha 5.0% | Buy MELI
- TSM hold | confidence 4500.0% | benchmark alpha 2.0% | Hold TSM

## Suggested Areas for Improvement
- Weak action type: buy averaged -0.75% benchmark alpha.
- Weak sector: Technology averaged -2.00% benchmark alpha.
- Replacement misses: TSM->LOWC.
- Thesis forecast mismatches: 1 symbols moved against thesis direction.

## Open Questions
- Which recommendation types should be split further by market regime or conviction band?
- Do the weakest sectors remain weak after controlling for confidence and holding period?
- Which thesis deltas should be tracked more explicitly in future briefs?
