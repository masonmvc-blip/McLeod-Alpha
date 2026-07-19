# Historical Replay Report - REPLAY-41A45FF2B5F8BE02A50E

## Replay Summary
- Snapshot count: 3
- Replay content hash: df8971cd94701c0ae1bd2c1d57a1c5e8dc3f3f6fa740aaa2dc916b2c71015308
- Decision stability: 0.000000
- Recommendation changes: 2
- Portfolio turnover: 0.046667
- Replacement quality: 0.700000
- Confidence calibration: 0.755467
- Max drawdown: 0.010000

## Timeline
- 2026-01-01 | S-001 | decision | PASS | fe013c2fb337
- 2026-01-01 | S-001 | performance | PASS | aec2f634bde1
- 2026-01-01 | S-001 | portfolio | PASS | e96b2c00b6b8
- 2026-01-01 | S-001 | thesis | PASS | c2d5fdb8ef93
- 2026-01-02 | S-002 | decision | PASS | e127d593ac13
- 2026-01-02 | S-002 | performance | PASS | 4a3e2b2b0411
- 2026-01-02 | S-002 | portfolio | PASS | 7bfaea5cfdd3
- 2026-01-02 | S-002 | thesis | PASS | 736faf7063ae
- 2026-01-03 | S-003 | decision | PASS | d698d8dbe8b9
- 2026-01-03 | S-003 | performance | PASS | ebe2c3c82092
- 2026-01-03 | S-003 | portfolio | PASS | 94446725c3ea
- 2026-01-03 | S-003 | thesis | PASS | 636f22646bbb

## Decision Timeline
- 2026-01-01 | recommendation=HOLD | confidence=0.7557
- 2026-01-02 | recommendation=BUY | confidence=0.7564
- 2026-01-03 | recommendation=TRIM | confidence=0.7543

## Portfolio Timeline
- 2026-01-01 | turnover=0.02 | cash_weight=0.1
- 2026-01-02 | turnover=0.06 | cash_weight=0.1
- 2026-01-03 | turnover=0.06 | cash_weight=0.1

## Thesis Timeline
- 2026-01-01 | health_score=65.1 | status=ACTIVE
- 2026-01-02 | health_score=65.2 | status=ACTIVE
- 2026-01-03 | health_score=64.9 | status=ACTIVE

## Performance Timeline
- 2026-01-01 | alpha=0.01 | replacement_quality=0.7
- 2026-01-02 | alpha=0.02 | replacement_quality=0.7
- 2026-01-03 | alpha=-0.01 | replacement_quality=0.7

## Failures
- None

## Successes
- No lookahead leakage detected.
- Replay completed with deterministic stage hashes.
- Replay metrics generated and serialized deterministically.
