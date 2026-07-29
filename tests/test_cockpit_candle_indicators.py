import csv
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import cockpit
from engine.brain import active_stop_category, indicator_no_entry_reasons
from engine.memory.service import Memory
import pandas as pd
import phase3_monitor


ET = ZoneInfo("America/New_York")


def _write_candles(path):
    rows = [
        {"datetime": "2026-07-20T14:14:00+00:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        {"datetime": "2026-07-20T14:15:00+00:00", "open": 100, "high": 102, "low": 100, "close": 101, "volume": 1100},
        {"datetime": "2026-07-20T14:16:00+00:00", "open": 101, "high": 103, "low": 101, "close": 102, "volume": 1200},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_indicator_snapshot_includes_monitor_published_current_minute(tmp_path):
    history_path = tmp_path / "spy_1min_history.csv"
    _write_candles(history_path)

    during_published_minute = cockpit._compute_candle_indicator_snapshot(
        now_et=datetime(2026, 7, 20, 10, 16, 30, tzinfo=ET),
        history_path=history_path,
    )
    after_current_minute_closes = cockpit._compute_candle_indicator_snapshot(
        now_et=datetime(2026, 7, 20, 10, 17, 1, tzinfo=ET),
        history_path=history_path,
    )

    assert during_published_minute["timestamp"].startswith("2026-07-20T10:16:00")
    assert after_current_minute_closes["timestamp"].startswith("2026-07-20T10:16:00")


def test_indicator_snapshot_uses_strategy_score_for_closed_candles(tmp_path):
    history_path = tmp_path / "spy_1min_history.csv"
    _write_candles(history_path)
    now = datetime(2026, 7, 20, 10, 17, 1, tzinfo=ET)

    snapshot = cockpit._compute_candle_indicator_snapshot(now_et=now, history_path=history_path)
    frame = pd.read_csv(history_path)
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    expected = phase3_monitor.score_closed_candle_frame(frame)

    assert snapshot["call_passed"] == max(0, int(expected["call_score"]))
    assert snapshot["put_passed"] == max(0, int(expected["put_score"]))
    assert snapshot["regime"] == expected["regime"]
    assert snapshot["market_trend"] == expected["market_trend"]


def test_indicator_snapshot_prefers_matching_monitor_decision_audit_scores():
    snapshot = {
        "call_passed": 1,
        "put_passed": 3,
        "regime": "NO_TRADE",
        "market_trend": "BULL_TREND",
    }
    audit_event = {
        "event_type": "entry_evaluation",
        "call_score": 2,
        "put_score": 5,
        "regime": "BEAR_TREND",
        "candle_time": "2026-07-20T14:15:00+00:00",
    }

    merged = cockpit._apply_decision_audit_scores(snapshot, audit_event)

    assert merged["call_passed"] == 2
    assert merged["put_passed"] == 5
    assert merged["regime"] == "BEAR_TREND"
    assert merged["market_trend"] == "BULL_TREND"
    assert merged["timestamp"] == "2026-07-20T10:15:00-04:00"


def test_indicator_snapshot_keeps_calculated_scores_without_complete_audit():
    snapshot = {"call_passed": 1, "put_passed": 3, "regime": "NO_TRADE"}

    assert cockpit._apply_decision_audit_scores(snapshot, {"event_type": "entry_evaluation"}) == snapshot


def test_status_prefers_indicator_snapshot_timestamp_for_candle_freshness():
    source = (cockpit.PROJECT_ROOT / "engine" / "runtime_status.py").read_text(encoding="utf-8")

    assert 'status["last_candle_at"] = indicator_candle_at.astimezone(EASTERN_TZ).isoformat()' in source
    assert 'status["last_candle_posted_at"] = (' in source
    assert 'timedelta(minutes=1)' in source
    assert 'if status.get("last_candle_at"):' in source


def test_banner_uses_candle_posting_timestamp():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "const candlePostedAt = status.last_candle_posted_at || candleAt;" in source
    assert "const candleTimeText = formatTimeAMPM(candlePostedAt);" in source


def test_qualifying_side_shows_matching_closed_candle_no_entry_reason(tmp_path):
    audit_path = tmp_path / "decision_audit_history.jsonl"
    snapshot = {"timestamp": "2026-07-20T10:16:00-04:00"}
    event = {
        "event_type": "entry_evaluation",
        "candle_time": "2026-07-20T14:16:00+00:00",
        "entry_opened": False,
        "regime": "BEAR_TREND",
        "call_score": 5,
        "put_score": 5,
        "entry_decision_reason": "no_entry_signal",
    }
    audit_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

    audit_event = Memory(db_path=tmp_path / "memory.db").load_decision_audit_event(
        audit_path, snapshot["timestamp"]
    )
    reasons = indicator_no_entry_reasons(audit_event)

    assert reasons["CALL"] == "Trend is Neutral or Bear"
    assert reasons["PUT"] == "no entry signal"


def test_active_stop_reason_uses_the_actual_stop_price():
    assert active_stop_category(5.00, stop_price=4.80) == "Stop"
    assert active_stop_category(5.00, stop_price=5.15) == "4% Stop"


def test_today_trades_renders_immutable_entry_checklist_count_before_gate_score():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "indicators = `${formatNumber(indicatorCountRaw)} / ${formatNumber(indicatorTotalRaw)}`;" in source
    assert "const checklistPassed = Math.max(0, Math.min(5, gateRounded));" not in source


def test_today_trades_renders_phase_in_title_case():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "const momentumPhase = String(trade.momentum_phase || '')" in source
    assert ".replaceAll('_', ' ')" in source
    assert ".toLowerCase()" in source
    assert ".map((word) => word.charAt(0).toUpperCase() + word.slice(1))" in source


def test_market_bells_use_independent_visible_dashboard_clock():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "function startMarketBellClock()" in source
    assert "maybePlayMarketSessionBells(null);" in source
    assert "}, 250);" in source
    assert "startMarketBellClock();" in source


def test_current_position_shows_stop_category_and_protective_stop_price():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "stopCategoryEl.textContent = activeStopCategory || 'Active Stop';" in source
    assert "Stop Loss: ${activeStopCategory || 'Active Stop'}" not in source
    assert 'id="currentStopPrice"' in source
    assert "stopPriceEl.textContent" in source
    assert "formatMoney(activeStopPrice)" in source


def test_current_position_uses_in_position_titles_and_live_indicator_deltas():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert 'id="currentPositionTitle">Current Position</h3>' in source
    assert 'id="currentPositionSummary"' in source
    assert '#statusGrid.position-focus-active #currentPositionSummary {' in source
    assert 'gap: 0;' in source
    assert "positionTitleEl.hidden = hasOpenPosition;" in source
    assert ">Stop Price</div>" in source
    assert ">Entry Price</div>" in source
    assert ">Option Price</div>" in source
    assert ">Current P&amp;L</div>" not in source
    assert ">Stop Loss</div>" not in source
    assert 'id="currentStopCategory"' in source
    assert "formatIndicatorDelta(callPassed, entryCallCount)" in source
    assert "formatIndicatorDelta(putPassed, entryPutCount)" in source
    assert '>Call Phase</div>' in source
    assert '>Put Phase</div>' in source
    assert '>Entry Regime</div>' in source
    assert '>Candle Trend</div>' in source
    assert 'id="currentCallPhase"' in source
    assert 'id="currentPutPhase"' in source
    assert 'id="currentMarketTrend"' in source
    assert 'id="currentCandleTrend"' in source
    assert 'callPhaseEl.textContent' in source
    assert 'putPhaseEl.textContent' in source
    assert 'marketTrendEl.textContent' in source
    assert 'candleTrendEl.textContent' in source


def test_open_position_card_uses_one_text_size():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert '#statusGrid.position-focus-active #currentPositionCard .position-summary-main,' in source
    assert '#statusGrid.position-focus-active #currentPositionCard .position-summary-pnl,' in source
    assert '#statusGrid.position-focus-active #currentPositionCard .position-summary-stop,' in source
    assert '#statusGrid.position-focus-active #currentPositionCard .position-stat-label,' in source
    assert '#statusGrid.position-focus-active #currentPositionCard .position-stat-value,' in source
    assert '#statusGrid.position-focus-active #currentPositionCard .position-candle-count {' in source
    assert 'font-size: 15px;' in source


def test_flat_position_hides_current_position_and_uses_three_card_indicator_row():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert '#statusGrid.position-flat {' in source
    assert 'grid-template-columns: repeat(6, minmax(0, 1fr));' in source
    assert '#statusGrid.position-flat #currentPositionCard {' in source
    assert "display: none;" in source
    assert 'id="callIndicatorsCard"' in source
    assert 'id="trendCard"' in source
    assert 'id="trendStatus"' in source
    assert '#trendCard {' in source
    assert 'justify-content: center;' in source
    assert '#trendStatus {' in source
    assert 'width: 100%;' in source
    assert '.trade-entry-banner .banner-title {' in source
    assert 'font-size: 18px;' in source
    assert 'font-size: 17px;' in source
    assert '<h3 id="trendTitle">Trend</h3>' in source
    assert 'id="putIndicatorsCard"' in source
    assert '#statusGrid.position-flat #callIndicatorsCard,' in source
    assert '#statusGrid.position-flat #trendCard,' in source
    assert 'grid-column: span 2;' in source
    assert 'id="wtdPnlCard"' in source
    assert 'id="mtdPnlCard"' in source
    assert 'id="ytdPnlCard"' in source
    assert 'grid-column: span 2;' in source
    assert "statusGrid.classList.toggle('position-flat', !hasOpenPosition);" in source


def test_cockpit_hides_spy_run_telemetry_but_keeps_flat_position_none():
    cockpit_source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")
    monitor_source = (cockpit.PROJECT_ROOT / "phase3_monitor.py").read_text(encoding="utf-8")

    assert "posEl.textContent = 'None';" in cockpit_source
    assert "SPY Run $${runDollars.toFixed(2)}/$${runThreshold.toFixed(2)}" not in cockpit_source
    assert '"spy_run": _directional_spy_run(indicators)' in monitor_source


def test_current_position_has_live_candle_indicator_column():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert 'id="currentPositionStats"' in source
    assert 'grid-template-columns: repeat(4, minmax(0, 1fr))' in source
    assert '.position-stats-grid {' in source
    assert 'text-align: center;' in source
    assert '.status-card {' in source
    assert 'class="position-summary-main" id="currentPosition"' in source
    assert 'id="currentStopPrice"' in source
    assert 'id="currentOptionEntry"' in source
    assert 'id="currentOptionPrice"' in source
    assert 'id="currentCandleIndicators"' in source
    assert '>Latest Candle</div>' not in source
    assert 'id="currentCandleCallCount"' in source
    assert 'id="currentCandlePutCount"' in source
    assert 'id="currentMarketContext"' in source
    assert "${callPassed}/${indicatorTotal}${formatIndicatorDelta(callPassed, entryCallCount)}" in source
    assert "${putPassed}/${indicatorTotal}${formatIndicatorDelta(putPassed, entryPutCount)}" in source


def test_entry_block_reason_is_shown_only_on_the_blocked_indicator_side():
    cockpit_source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")
    runtime_status_source = (cockpit.PROJECT_ROOT / "engine" / "runtime_status.py").read_text(encoding="utf-8")

    assert 'const lastEntryCandidateDirection = String(status.last_entry_candidate_direction || \'\').toUpperCase();' in cockpit_source
    assert "lastEntryCandidateDirection === side && lastEntryBlockReason" in cockpit_source
    assert "> ${blockReason}</span>" not in cockpit_source
    assert ">${blockReason}</span>" in cockpit_source
    assert '"last_entry_candidate_direction": None' in runtime_status_source
    assert '"last_entry_block_reason": None' in runtime_status_source
    assert 'decision_audit.get("candidate_direction")' in runtime_status_source
    assert 'decision_audit.get("entry_block_reason")' in runtime_status_source


def test_qualified_non_entry_reasons_are_not_rendered_below_recent_logs():
    cockpit_source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert 'id="qualifiedEntryBlocks"' not in cockpit_source
    assert 'Qualified Entries Not Taken' not in cockpit_source
    assert 'status.qualified_entry_blocks' not in cockpit_source
    assert "lastEntryCandidateDirection === side && lastEntryBlockReason" in cockpit_source


def test_option_label_includes_strike_for_calls_and_puts():
    assert cockpit._position_label_from_option_symbol("SPY   260720C00755000") == "$755 Call"
    assert cockpit._position_label_from_option_symbol("SPY   260720P00752250") == "$752.25 Put"


def test_qualifying_indicator_cards_show_blocked_reason():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "formatIndicatorCardText(lastEntryBlockReason)" in source
    assert ">${conciseReason}</span>" in source


def test_full_indicator_cards_are_green():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert '.status-card.indicator-qualified {' in source
    assert 'callIndicatorsCard.classList.toggle(\'indicator-qualified\', callPassed >= 5);' in source
    assert 'putIndicatorsCard.classList.toggle(\'indicator-qualified\', putPassed >= 5);' in source


def test_indicator_cards_show_current_trend_without_direction_requirement_copy():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "function formatIndicatorCardText(value)" in source
    assert ".replaceAll('_', ' ')" in source
    assert ".toLowerCase()" in source
    assert ".map(word => `${word.charAt(0).toUpperCase()}${word.slice(1)}`)" in source
    assert "const momentumStage = formatIndicatorCardText(" in source
    assert "formatIndicatorCardText(lastEntryBlockReason)" in source
    assert "const phaseText = momentumStage" in source
    assert "${escapeHtml(momentumStage)}" in source
    assert "callMomentumStrength" not in source
    assert "putMomentumStrength" not in source
    assert "Momentum ${momentumStrength.toFixed(1)}/5" not in source
    assert "const indicatorRegime = String(status.continuation_regime || 'UNKNOWN').toUpperCase();" in source
    assert "const trend = trendMap[trendRaw] || 'NEUTRAL';" in source
    assert "const candleTrend = trendMap[indicatorRegime] || 'NEUTRAL';" in source
    assert "trendText = '🐂 Bull Market 🐂';" in source
    assert "trendText = '🐻 Bear Market 🐻';" in source
    assert "? 'Bull Candles'" in source
    assert "? 'Bear Candles'" in source
    assert "#trendStatus .trend-tone-neutral" in source
    assert "#trendStatus .trend-tone-bearish" in source
    assert "#trendStatus .trend-tone-bullish" in source
    assert 'id="trendStatus"' in source
    assert 'class="${liveCandles.tone}"' in source
    assert "🕯️ ${liveCandles.candleText} 🕯️" in source
    assert "Candle: ${escapeHtml(candleTrendLabel)}" not in source
    assert "formatIndicatorCardText(candleTrendLabel)" in source
    assert "Market Trend:" not in source
    assert "trendWithTimestamp" not in source
    assert "Market Trend: ${trendText}" not in source
    assert "${side} requires ${requiredLabel}" not in source


def test_top_banner_combines_title_price_and_inline_status_meta():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert 'id="tradeEntryBannerPrice"' in source
    assert '<span>SPY Options Trader Cockpit 1.4</span>' in source
    assert 'class="mobile-price-rocket"' in source
    assert 'class="title-rocket"' in source
    assert '.title-rockets .title-rocket {' in source
    assert '.trade-entry-banner .mobile-price-rocket {' in source
    assert 'display: none;' in source
    assert 'display: inline-block;' in source
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr));' in source
    assert 'gap: 8px;' in source
    assert '.trade-entry-banner {\n            display: grid;' in source
    assert 'font-size: 18px;' in source
    assert '.trade-entry-banner .banner-title {\n            color: #333;\n            font-size: inherit;' in source
    assert '.trade-entry-banner .banner-meta {\n            display: flex;' in source
    assert 'font-size: 17px;' in source
    assert 'justify-self: center;' in source
    assert 'text-align: center;' in source
    assert 'display: flex;' in source
    assert '.trade-entry-banner .banner-meta-divider.show {' in source
    assert 'display: inline;' in source
    assert 'white-space: nowrap;' in source
    assert "const tradeEntryBannerPrice = document.getElementById('tradeEntryBannerPrice');" in source
    assert "tradeEntryBannerPrice.innerHTML = priceBannerHtml;" in source
    assert "tradeEntryBannerTitle" not in source
    assert "OPEN FOR BUSINESS" not in source
    assert source.count("const pctSign = spyChangePct > 0 ? '+' : (spyChangePct < 0 ? '-' : '');") == 2
    assert source.count("pctText = `(${pctSign}${pctRaw})`;") == 2


def test_indicator_snapshot_does_not_cap_qualifying_scores(monkeypatch, tmp_path):
    history_path = tmp_path / "spy_1min_history.csv"
    _write_candles(history_path)
    monkeypatch.setattr(
        phase3_monitor,
        "score_closed_candle_frame",
        lambda _candles: {"call_score": 7, "put_score": 6, "regime": "BULL_TREND"},
    )

    snapshot = cockpit._compute_candle_indicator_snapshot(
        now_et=datetime(2026, 7, 20, 10, 17, 1, tzinfo=ET),
        history_path=history_path,
    )

    assert snapshot["call_passed"] == 7
    assert snapshot["put_passed"] == 6
    assert snapshot["total"] == 5


def test_indicator_snapshot_includes_side_specific_momentum():
    source = (cockpit.PROJECT_ROOT / "phase3_monitor.py").read_text(encoding="utf-8")

    assert '"call_momentum": momentum_snapshot("CALL")' in source
    assert '"put_momentum": momentum_snapshot("PUT")' in source


def test_indicator_scores_publish_immediately_after_recent_log_score():
    source = (cockpit.PROJECT_ROOT / "phase3_monitor.py").read_text(encoding="utf-8")

    score_log_index = source.index("log_signal(float(last.close), regime, call_score, put_score)")
    assert source.index("_publish_indicator_scores(", score_log_index) > score_log_index
    assert '"event_phase": "scores_published"' in source


def test_visible_dashboard_requests_fresh_indicator_status_quarter_secondly():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "const STATUS_REFRESH_VISIBLE_INTERVAL_MS = 250;" in source
    assert "const statusUrl = forceRefresh || isDashboardVisible()" in source
    assert "? '/api/status?fresh=1'" in source


def test_trend_box_promotes_entry_regime_and_keeps_live_context():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "const POSITION_CONTEXT_REFRESH_INTERVAL_MS = 250;" in source
    assert "fetch('/api/position-status', { cache: 'no-store' })" in source
    assert "trendTitleEl.textContent = 'Entry Regime';" in source
    assert "'🐂 BULL ENTRY 🐂'" in source
    assert "'🐻 BEAR ENTRY 🐻'" in source
    assert "🕯️ Live: ${liveCandles.candleText}" in source
    assert "Session: ${session.shortText}" in source
    assert "renderTrendBox(status, fastPositionContext);" in source


def test_position_payload_exposes_immutable_entry_regime_context():
    context = cockpit._entry_context_from_position_payload({
        "direction": "CALL",
        "entry_time": "2026-07-29T14:42:05-04:00",
        "feature_payload": {
            "regime": "BULL_TREND",
            "call_score": 7,
            "put_score": 0,
            "momentum_phase": "EARLY_CONTINUATION",
            "captured_at": "2026-07-29T14:42:03-04:00",
        },
    })

    assert context == {
        "entry_regime": "BULL_TREND",
        "entry_direction": "CALL",
        "entry_time": "2026-07-29T14:42:05-04:00",
        "entry_candle_time": "2026-07-29T14:42:03-04:00",
        "entry_call_score": 7,
        "entry_put_score": 0,
        "entry_phase": "EARLY_CONTINUATION",
    }


def test_indicator_performance_refreshes_when_closed_trade_signature_changes():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "lastIndicatorTradeSignature" in source
    assert "lastIndicatorTradeSignature !== closedTradeSignature" in source


def test_indicator_performance_renders_ema_as_an_acronym():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "word.replace(/^ema/i, 'EMA')" in source
    assert "prev: 'Previous'" in source
    assert "ema10: '10 EMA'" in source
    assert "vwap: 'VWAP'" in source
    assert "macd: 'MACD'" in source


def test_indicator_performance_renders_todays_trade_outcomes_and_neutral_case():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "Today's Trades" in source
    assert "todayIndicatorResult" in source
    assert "if (!trades) return '';" in source
    assert 'const winRate = (wins / trades) * 100;' in source
    assert 'indicator-performance-wins' in source
    assert 'indicator-performance-losses' in source
    assert source.count('winRate.toFixed(0)') == 2
    assert 'winRate.toFixed(1)' not in source
    assert "trend === 'NEUTRAL' ? 'Neutral'" in source
    assert ": 'Neutral';" in source
    assert "Netural" not in source


def test_indicator_performance_centers_canonical_present_absent_columns():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert source.count("<span>Present (Canonical)</span>") == 2
    assert source.count("<span>Absent, Same Direction</span>") == 2
    assert source.count("<span>Research Guidance</span>") == 2
    assert "absent_win_rate_pct" in source
    assert "automatic_live_change_allowed" in source
    assert 'return amount < 0 ? `(${formatted})` : formatted;' in source
    assert ".indicator-performance-columns {\n            color: #607083;" in source
    assert "text-align: center;" in source


def test_cash_register_plays_when_a_trade_opens():
    source = (cockpit.PROJECT_ROOT / "cockpit.py").read_text(encoding="utf-8")

    assert "if (hasOpenPosition) {\n                        playCashRegisterNoise();" in source
