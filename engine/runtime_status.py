"""Runtime status aggregation isolated from Cockpit presentation routes."""

from __future__ import annotations

from types import FunctionType
from typing import Any, MutableMapping


def parse_bot_status(runtime_globals: MutableMapping[str, Any]) -> dict[str, Any]:
    """Build a runtime status snapshot using Cockpit-provided live dependencies.

    The implementation is rebound to the caller's globals so existing runtime
    helpers, caches, and test monkeypatches remain the single source of truth.
    """
    builder = FunctionType(
        _build_runtime_status.__code__,
        runtime_globals,
        name="_build_runtime_status",
        argdefs=_build_runtime_status.__defaults__,
        closure=_build_runtime_status.__closure__,
    )
    return builder()


def _build_runtime_status():
    """Parse bot status from logs and position file"""
    active_log = _resolve_active_bot_log_file()
    candle_indicator_snapshot = _compute_candle_indicator_snapshot()

    def calculate_broker_period_pnl() -> tuple[float, float, float, float]:
        """Compute realized Today/WTD/MTD/YTD P&L, reconciling with completed local trades."""
        global _BROKER_PNL_CACHE

        from zoneinfo import ZoneInfo

        def _safe_amount(value, fallback=0.0):
            try:
                return round(float(value), 2)
            except (TypeError, ValueError):
                return round(float(fallback), 2)

        def _prefer_external(candidate, baseline, has_scoped_transactions):
            """Use Schwab totals only when its response contains matching transaction legs."""
            if candidate is None or not has_scoped_transactions:
                return _safe_amount(baseline, 0.0), False
            return _safe_amount(candidate, 0.0), True

        def _api_period_net_after(start_dt, end_dt, symbol_scope, asset_scope):
            from decimal import Decimal

            resp = client.get_transactions(
                account_hash,
                start_date=start_dt,
                end_date=end_dt,
                transaction_types=["TRADE", "RECEIVE_AND_DELIVER"],
            )
            resp.raise_for_status()
            transactions = resp.json() or []

            period_today = Decimal("0")
            period_wtd = Decimal("0")
            period_mtd = Decimal("0")
            period_ytd = Decimal("0")
            has_today_transactions = False
            has_wtd_transactions = False
            has_mtd_transactions = False
            has_ytd_transactions = False

            def _tx_timestamp(tx):
                for key in ("transactionDate", "tradeDate", "time"):
                    raw = tx.get(key)
                    if not raw:
                        continue
                    try:
                        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
                    except Exception:
                        try:
                            return datetime.strptime(str(raw), "%Y-%m-%dT%H:%M:%S%z").astimezone(ZoneInfo("America/New_York"))
                        except Exception:
                            continue
                return None

            def _to_float(value):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            def _parse_cash_amount(tx):
                from decimal import Decimal, InvalidOperation

                for value in ((tx or {}).get("netAmount"), (tx or {}).get("amount")):
                    try:
                        return Decimal(str(value))
                    except (InvalidOperation, TypeError, ValueError):
                        continue
                return None

            for tx in transactions:
                tx_ts = _tx_timestamp(tx)
                tx_type = str(tx.get("type") or "").upper()
                if tx_type and tx_type != "TRADE":
                    continue

                transfer_items = tx.get("transferItems") or []
                in_scope = False
                for item in transfer_items:
                    item = item or {}
                    inst = item.get("instrument") or {}
                    asset_type = str(inst.get("assetType") or "").upper()
                    if asset_scope and asset_type != asset_scope:
                        continue
                    symbol = str(inst.get("symbol") or "").upper()
                    underlying = str(inst.get("underlyingSymbol") or "").upper()
                    if symbol_scope and (symbol_scope not in symbol and symbol_scope != underlying):
                        continue
                    in_scope = True
                    break
                if not in_scope:
                    continue

                amount = _parse_cash_amount(tx)
                if amount is None:
                    continue

                period_ytd += amount
                has_ytd_transactions = True
                if tx_ts is not None and tx_ts >= week_start_dt:
                    period_wtd += amount
                    has_wtd_transactions = True
                if tx_ts is not None and tx_ts >= month_start_dt:
                    period_mtd += amount
                    has_mtd_transactions = True
                if tx_ts is not None and tx_ts >= day_start_dt:
                    period_today += amount
                    has_today_transactions = True

            return (
                float(period_today),
                float(period_wtd),
                float(period_mtd),
                float(period_ytd),
                has_today_transactions,
                has_wtd_transactions,
                has_mtd_transactions,
                has_ytd_transactions,
            )

        def _closed_trade_signature():
            try:
                summary = get_memory().load_trade_log_status_summary(
                    PROJECT_ROOT / "data" / "mcleod_alpha.db"
                )
                return str((summary or {}).get("closed_trade_signature") or "0:none")
            except Exception:
                return "unknown"

        now_et = datetime.now(ZoneInfo("America/New_York"))
        today_date = now_et.date()
        today_key = today_date.isoformat()
        now_ts = time.time()
        closed_trade_signature = _closed_trade_signature()
        trade_posted_since_cache = (
            _BROKER_PNL_CACHE.get("as_of_date") == today_key
            and _BROKER_PNL_CACHE.get("closed_trade_signature") != closed_trade_signature
        )

        if (
            _BROKER_PNL_CACHE.get("as_of_date") == today_key
            and not trade_posted_since_cache
            and (now_ts - float(_BROKER_PNL_CACHE.get("timestamp", 0.0))) < max(1.0, BROKER_PNL_REFRESH_SECONDS)
        ):
            return (
                float(_BROKER_PNL_CACHE.get("today", 0.0)),
                float(_BROKER_PNL_CACHE.get("wtd", 0.0)),
                float(_BROKER_PNL_CACHE.get("mtd", 0.0)),
                float(_BROKER_PNL_CACHE.get("ytd", 0.0)),
            )

        year_start_dt = now_et.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_dt = now_et.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        day_start_dt = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start_date, week_end_date = _monday_to_sunday_week_bounds(today_date)
        week_start_dt = day_start_dt.replace(
            year=week_start_date.year,
            month=week_start_date.month,
            day=week_start_date.day,
        )

        if (
            _BROKER_PNL_CACHE.get("as_of_date") == today_key
            and _BROKER_PNL_CACHE.get("closed_trade_signature") == closed_trade_signature
            and (now_ts - float(_BROKER_PNL_CACHE.get("timestamp", 0.0))) < MTD_PNL_CACHE_SECONDS
        ):
            return (
                float(_BROKER_PNL_CACHE.get("today", 0.0)),
                float(_BROKER_PNL_CACHE.get("wtd", 0.0)),
                float(_BROKER_PNL_CACHE.get("mtd", 0.0)),
                float(_BROKER_PNL_CACHE.get("ytd", 0.0)),
            )

        # Baseline from local completed trades so dashboard always reflects actual filled exits.
        local_today = _realized_spy_option_pnl_for_period(today_key, today_key)
        local_wtd_end = min(today_date, week_end_date)
        local_wtd = _realized_spy_option_pnl_for_period(
            week_start_date.isoformat(),
            local_wtd_end.isoformat(),
        )
        local_mtd = _realized_spy_option_pnl_for_period(month_start_dt.date().isoformat(), today_key)
        local_ytd = _realized_spy_option_pnl_for_period(year_start_dt.date().isoformat(), today_key)

        today_total = _safe_amount(local_today, 0.0)
        wtd_total = _safe_amount(local_wtd, 0.0)
        mtd_total = _safe_amount(local_mtd, 0.0)
        ytd_total = _safe_amount(local_ytd, 0.0)
        today_source = "trade_log_realized"
        wtd_source = "trade_log_realized"
        mtd_source = "trade_log_realized"
        ytd_source = "trade_log_realized"

        # A newly posted exit is immediately reflected from its persisted trade
        # record. Schwab transaction history remains authoritative after it catches up.
        if not trade_posted_since_cache:
            try:
                from schwab.auth import easy_client

                account_hash = os.getenv("SCHWAB_ACCOUNT_HASH")
                app_key = os.getenv("SCHWAB_APP_KEY")
                app_secret = os.getenv("SCHWAB_APP_SECRET")
                callback = os.getenv("SCHWAB_CALLBACK_URL")
                if all([account_hash, app_key, app_secret, callback]):
                    client = easy_client(
                        api_key=app_key,
                        app_secret=app_secret,
                        callback_url=callback,
                        token_path=_resolve_schwab_token_path(),
                        enforce_enums=False,
                    )

                    pnl_scope_symbol = str(os.getenv("BROKER_PNL_SCOPE_SYMBOL", "SPY")).strip().upper()
                    pnl_scope_asset = str(os.getenv("BROKER_PNL_SCOPE_ASSET", "OPTION")).strip().upper()
                    (
                        ext_today,
                        ext_wtd,
                        ext_mtd,
                        ext_ytd,
                        has_today_transactions,
                        has_wtd_transactions,
                        has_mtd_transactions,
                        has_ytd_transactions,
                    ) = _api_period_net_after(
                        year_start_dt,
                        now_et,
                        pnl_scope_symbol,
                        pnl_scope_asset,
                    )

                    source_parts = ["asset", pnl_scope_asset or "ALL"]
                    if pnl_scope_symbol:
                        source_parts.extend(["symbol", pnl_scope_symbol])
                    source_suffix = "_" + "_".join(source_parts)
                    ext_today_source = f"schwab_transactions_net{source_suffix}"
                    ext_wtd_source = f"schwab_transactions_net{source_suffix}"
                    ext_mtd_source = f"schwab_transactions_net{source_suffix}"
                    ext_ytd_source = f"schwab_transactions_net{source_suffix}"

                    today_total, used_ext_today = _prefer_external(ext_today, today_total, has_today_transactions)
                    wtd_total, used_ext_wtd = _prefer_external(ext_wtd, wtd_total, has_wtd_transactions)
                    mtd_total, used_ext_mtd = _prefer_external(ext_mtd, mtd_total, has_mtd_transactions)
                    ytd_total, used_ext_ytd = _prefer_external(ext_ytd, ytd_total, has_ytd_transactions)

                    if used_ext_today:
                        today_source = ext_today_source
                    if used_ext_wtd:
                        wtd_source = ext_wtd_source
                    if used_ext_mtd:
                        mtd_source = ext_mtd_source
                    if used_ext_ytd:
                        ytd_source = ext_ytd_source
            except Exception as exc:
                print(f"Broker P&L refresh unavailable: {exc}")

        _BROKER_PNL_CACHE = {
            "timestamp": now_ts,
            "today": today_total,
            "wtd": wtd_total,
            "mtd": mtd_total,
            "ytd": ytd_total,
            "as_of_date": today_key,
            "today_source": today_source,
            "wtd_source": wtd_source,
            "mtd_source": mtd_source,
            "ytd_source": ytd_source,
            "closed_trade_signature": closed_trade_signature,
        }

        if _BROKER_PNL_CACHE.get("last_preflight_date") != today_key:
            print(
                "BROKER PNL PREFLIGHT "
                f"| date={today_key} "
                f"| ptd={today_total:.2f} ({today_source}) "
                f"| wtd={wtd_total:.2f} ({wtd_source}) "
                f"| mtd={mtd_total:.2f} ({mtd_source}) "
                f"| ytd={ytd_total:.2f} ({ytd_source})"
            )
            _BROKER_PNL_CACHE["last_preflight_date"] = today_key

        return today_total, wtd_total, mtd_total, ytd_total

    todays_pnl, week_to_date_pnl, month_to_date_pnl, year_to_date_pnl = calculate_broker_period_pnl()
    now_et = datetime.now(EASTERN_TZ)
    nyse_today = now_et.date()
    nyse_is_trading_day = _is_nyse_trading_day(nyse_today)

    repo_path_ok, current_repo, expected_repo = _runtime_repo_path_allows_start()

    status = {
        "status_schema_version": "2026-07-18.1",
        "bot_running": is_bot_running(),
        "bot_running_effective": False,
        "bot_stale": None,
        "last_heartbeat_at": None,
        "heartbeat_age_seconds": None,
        "heartbeat_ok": None,
        "mode": "UNKNOWN",
        "account_verified": False,
        "account_number": "33310903",
        "account_nickname": AccountManager.get_display_name("33310903"),
        "broker_reconciliation": "UNKNOWN",
        "current_position": None,
        "current_position_side": None,
        "current_trade_pnl_dollars": None,
        "current_trade_pnl_pct": None,
        "current_trade_option_entry": None,
        "current_trade_mark": None,
        "active_stop_category": None,
        "active_protective_stop_price": None,
        "has_open_position": False,
        "protective_stop_status": None,
        "pending_orders": 0,
        "live_trade_count": 0,
        "todays_pnl": todays_pnl,
        "week_to_date_pnl": week_to_date_pnl,
        "month_to_date_pnl": month_to_date_pnl,
        "year_to_date_pnl": year_to_date_pnl,
        "broker_pnl_source": _BROKER_PNL_CACHE.get("today_source") or "schwab_transactions",
        "broker_pnl_as_of_date": _BROKER_PNL_CACHE.get("as_of_date"),
        "broker_pnl_preflight_date": _BROKER_PNL_CACHE.get("last_preflight_date"),
        "continuation_call_passed": 0,
        "continuation_put_passed": 0,
        "continuation_indicators_total": 5,
        "continuation_last_test_at": None,
        "continuation_regime": "UNKNOWN",
        "call_momentum_strength": None,
        "call_momentum_stage": None,
        "put_momentum_strength": None,
        "put_momentum_stage": None,
        "entry_paused": False,
        "last_decision": None,
        "last_decision_reason": None,
        "last_no_trade_call_reason": None,
        "last_no_trade_put_reason": None,
        "latest_rejection_reason": None,
        "trade_entry_enabled": False,
        "trade_entry_state": "DISABLED",
        "trade_entry_reason": "Bot is not running",
        "trade_entry_reason_code": "NOT_RUNNING",
        "trade_entry_reason_short": "Bot is not running",
        "decision_contract": {},
        "trend": "UNKNOWN",
        "market_trend": "UNKNOWN",
        "last_candle_at": None,
        "candle_age_seconds": None,
        "spy_price": None,
        "spy_change": None,
        "spy_change_pct": None,
        "spy_quote_state": "UNAVAILABLE",
        "server_time_et": now_et.isoformat(),
        "nyse_is_trading_day": nyse_is_trading_day,
        "nyse_close_time_et": _nyse_regular_close_time_for_date(nyse_today) if nyse_is_trading_day else None,
        "bot_check_at": None,
        "bot_check_age_seconds": None,
        "log_age_seconds": None,
        "log_stale": None,
        "last_error": None,
        "last_update": datetime.now().isoformat(),
        "broker_pnl_source_file": None,
        "trade_log_email_armed": False,
        "trade_log_email_last_sent_date": None,
        "trade_log_schema_ok": False,
        "preopen_dry_run_status": "NOT_RUN",
        "preopen_dry_run_message": None,
        "ops_readiness": {},
        "internet_quality": {},
        "internet_quality_history": {},
        "network_primary_interface": None,
        "network_primary_port": None,
        "config_validation": {},
        "config_snapshot": {},
        "runtime_alert_active": False,
        "runtime_alert_message": None,
        "runtime_alert_severity": None,
        "runtime_alert_updated_at": None,
        "network_summary": None,
        "on_ethernet": None,
        "wifi_power": None,
        "internet_market_warning": False,
        "internet_market_warning_message": None,
        "problem_messages": [],
        "problem_summary": None,
        "parity_state": "UNKNOWN",
        "parity_summary": None,
        "parity_issues": [],
        "parity_baseline_path": str(PARITY_BASELINE_FILE),
        "parity_enforce_on_start": _env_flag("PARITY_ENFORCE_ON_START", default=True),
        "parity_block_start": False,
        "runtime_fingerprint": {},
        "cockpit_public_url": COCKPIT_PUBLIC_URL,
        "runtime_repo_basename": current_repo,
        "canonical_repo_basename": expected_repo,
        "runtime_repo_path_ok": bool(repo_path_ok),
        "enforce_canonical_repo_path": bool(ENFORCE_CANONICAL_REPO_PATH),
        "bell_broadcast_id": int(_BELL_BROADCAST.get("id") or 0),
        "bell_broadcast_kind": str(_BELL_BROADCAST.get("kind") or "open"),
        "bell_broadcast_at": _BELL_BROADCAST.get("triggered_at"),
        "bell_broadcast_source": _BELL_BROADCAST.get("source"),
    }

    if candle_indicator_snapshot:
        status["continuation_call_passed"] = int(candle_indicator_snapshot.get("call_passed") or 0)
        status["continuation_put_passed"] = int(candle_indicator_snapshot.get("put_passed") or 0)
        status["continuation_indicators_total"] = int(candle_indicator_snapshot.get("total") or 5)
        call_momentum = candle_indicator_snapshot.get("call_momentum") or {}
        put_momentum = candle_indicator_snapshot.get("put_momentum") or {}
        status["call_momentum_strength"] = call_momentum.get("strength")
        status["call_momentum_stage"] = call_momentum.get("stage")
        status["put_momentum_strength"] = put_momentum.get("strength")
        status["put_momentum_stage"] = put_momentum.get("stage")

    try:
        status["entry_paused"] = bool((get_memory().load_setting(ENTRY_PAUSE_FILE, {}) or {}).get("paused"))
    except Exception:
        status["entry_paused"] = False
        status["continuation_last_test_at"] = candle_indicator_snapshot.get("timestamp")
        status["continuation_regime"] = str(candle_indicator_snapshot.get("regime") or "UNKNOWN")

    try:
        parity = _parity_status_snapshot()
        status["parity_state"] = str(parity.get("state") or "UNKNOWN")
        status["parity_summary"] = parity.get("summary")
        status["parity_issues"] = list(parity.get("issues") or [])
        status["parity_baseline_path"] = str(parity.get("baseline_path") or PARITY_BASELINE_FILE)
        status["runtime_fingerprint"] = dict(parity.get("runtime_fingerprint") or {})
        status["parity_block_start"] = bool(
            status.get("parity_enforce_on_start")
            and str(status.get("parity_state") or "UNKNOWN").upper() != "MATCH"
        )
    except Exception:
        pass

    try:
        status["internet_quality"] = _get_internet_quality_snapshot()
    except Exception as e:
        status["internet_quality"] = {
            "quality": "UNKNOWN",
            "summary": f"Probe error: {e}",
            "avg_latency_ms": None,
            "max_latency_ms": None,
            "ok_count": 0,
            "target_count": len(INTERNET_QUALITY_TARGETS),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "targets": [],
        }
    try:
        status["internet_quality_history"] = _summarize_internet_quality_history(
            _load_recent_internet_quality_samples()
        )
    except Exception:
        status["internet_quality_history"] = {}

    try:
        network = _get_primary_network_status()
        status["network_primary_interface"] = network.get("primary_interface")
        status["network_primary_port"] = network.get("primary_port")
        status["network_summary"] = network.get("summary")
        status["on_ethernet"] = bool(network.get("on_ethernet"))
        status["wifi_power"] = network.get("wifi_power")
    except Exception:
        pass

    # SPY banner pricing now comes only from the dedicated background tracker.
    try:
        _ensure_spy_tracker_running()
        tracker = _spy_tracker_snapshot()
        status["spy_quote_refresh_seconds_current"] = round(float(SPY_TRACKER_REFRESH_SECONDS), 2)
        status["spy_price"] = tracker.get("price")
        status["spy_change"] = tracker.get("change")
        status["spy_change_pct"] = tracker.get("change_pct")
        status["spy_quote_stale"] = bool(tracker.get("stale"))
        status["spy_quote_age_seconds"] = tracker.get("quote_age_seconds")
        status["spy_quote_as_of"] = tracker.get("quote_as_of")
        status["spy_quote_state"] = str(tracker.get("state") or "UNAVAILABLE")
    except Exception:
        status["spy_quote_refresh_seconds_current"] = round(float(SPY_TRACKER_REFRESH_SECONDS), 2)
        status["spy_quote_stale"] = True
        status["spy_quote_state"] = "UNAVAILABLE"

    _apply_spy_close_baseline(status)

    if active_log.exists():
        try:
            mtime = active_log.stat().st_mtime
            age = max(0.0, time.time() - mtime)
            status["last_heartbeat_at"] = datetime.fromtimestamp(mtime).isoformat()
            status["heartbeat_age_seconds"] = round(age, 1)
            status["bot_check_at"] = status["last_heartbeat_at"]
            status["bot_check_age_seconds"] = status["heartbeat_age_seconds"]
            status["log_age_seconds"] = status["heartbeat_age_seconds"]
            status["log_stale"] = bool(age > HEARTBEAT_BANNER_STOP_SECONDS)
            if status["bot_running"]:
                status["heartbeat_ok"] = age <= HEARTBEAT_STALE_SECONDS
            status["bot_stale"] = bool(age > HEARTBEAT_BANNER_STOP_SECONDS)
            status["bot_running_effective"] = bool(status["bot_running"] and age <= HEARTBEAT_BANNER_STOP_SECONDS)
        except Exception:
            pass
    else:
        status["bot_stale"] = bool(status["bot_running"])
        status["bot_running_effective"] = False
    
    # Try to load current position from disk
    try:
        position_file = PROJECT_ROOT / "data" / "open_position.json"
        if position_file.exists():
            with open(position_file, 'r') as f:
                pos_data = json.load(f)
                status["current_position_side"] = str(pos_data.get("direction") or "").upper() or None
                status["current_position"] = _position_label_from_option_symbol(
                    pos_data.get("option_symbol"),
                    fallback_direction=pos_data.get("direction"),
                )
                status["has_open_position"] = True

                option_symbol = str(pos_data.get("option_symbol") or "").strip()
                try:
                    option_entry = float(pos_data.get("option_entry") or 0.0)
                except (TypeError, ValueError):
                    option_entry = 0.0
                try:
                    quantity = abs(float(pos_data.get("quantity") or 0.0))
                except (TypeError, ValueError):
                    quantity = 0.0
                try:
                    option_stop = float(pos_data.get("option_stop") or 0.0)
                except (TypeError, ValueError):
                    option_stop = 0.0

                if option_entry > 0:
                    status["current_trade_option_entry"] = round(option_entry, 3)

                status["protective_stop_status"] = str(pos_data.get("protective_stop_status") or "").strip() or None
                status["active_stop_category"] = active_stop_category(option_entry, stop_price=option_stop)
                status["active_protective_stop_price"] = _active_broker_protective_stop_price(
                    option_symbol,
                    pos_data.get("protective_stop_order_id"),
                )

                if option_symbol and option_entry > 0 and quantity > 0:
                    try:
                        client = _get_broker_client()
                        resp = client.get_quote(option_symbol)
                        resp.raise_for_status()
                        payload = resp.json() or {}
                        symbol_blob = payload.get(option_symbol) or next(iter(payload.values()), {})
                        quote = symbol_blob.get("quote") or {}

                        def _to_float(value):
                            try:
                                return float(value)
                            except (TypeError, ValueError):
                                return None

                        current_mark = None
                        for candidate in (
                            quote.get("mark"),
                            quote.get("lastPrice"),
                            quote.get("bidPrice"),
                            quote.get("askPrice"),
                        ):
                            current_mark = _to_float(candidate)
                            if current_mark is not None and current_mark > 0:
                                break

                        if current_mark is not None and current_mark > 0:
                            pnl_dollars = (current_mark - option_entry) * quantity * OPTION_CONTRACT_MULTIPLIER
                            pnl_pct = ((current_mark - option_entry) / option_entry) * 100.0
                            status["current_trade_mark"] = round(current_mark, 3)
                            status["current_trade_pnl_dollars"] = round(pnl_dollars, 2)
                            status["current_trade_pnl_pct"] = round(pnl_pct, 1)
                            status["active_stop_category"] = active_stop_category(
                                option_entry,
                                current_mark=current_mark,
                                stop_price=option_stop,
                            )
                    except Exception:
                        pass
    except Exception as e:
        pass

    # Load latest continuation cheat-sheet snapshot from strategy monitor.
    # Use as fallback only when candle-derived scoring is unavailable.
    try:
        if (not candle_indicator_snapshot) and CONTINUATION_STATUS_FILE.exists():
            snap = json.loads(CONTINUATION_STATUS_FILE.read_text())
            status["continuation_call_passed"] = int(((snap.get("call") or {}).get("passed") or 0))
            status["continuation_put_passed"] = int(((snap.get("put") or {}).get("passed") or 0))
            status["continuation_indicators_total"] = int(
                ((snap.get("call") or {}).get("total")
                or ((snap.get("put") or {}).get("total")
                or 5)
            ))
            status["continuation_last_test_at"] = snap.get("timestamp")
    except Exception:
        pass

    try:
        if LATEST_REJECTION_FILE.exists():
            latest_reject = json.loads(LATEST_REJECTION_FILE.read_text())
            reason_text = str((latest_reject or {}).get("exact_rejection_reason") or "").strip()
            side_text = str((latest_reject or {}).get("side") or "").strip().upper()
            if reason_text:
                if side_text in {"CALL", "PUT"}:
                    status["latest_rejection_reason"] = f"{side_text}: {reason_text}"
                else:
                    status["latest_rejection_reason"] = reason_text
    except Exception:
        pass

    try:
        export_path, _ = _load_latest_schwab_transaction_export()
        if export_path is not None:
            status["broker_pnl_source_file"] = export_path.name
    except Exception:
        pass

    try:
        email_state = _load_json_file(PROJECT_ROOT / "data" / "daily_trade_log_email_state.json") or {}
        status["trade_log_email_armed"] = str(os.getenv("DAILY_TRADE_LOG_EMAIL_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}
        status["trade_log_email_last_sent_date"] = email_state.get("last_sent_date")
    except Exception:
        pass

    try:
        summary = get_memory().load_trade_log_status_summary(
            PROJECT_ROOT / "data" / "mcleod_alpha.db"
        )
        status["trade_log_schema_ok"] = bool((summary or {}).get("has_absorption_score"))
    except Exception:
        pass

    try:
        dry_run_state = _load_json_file(PROJECT_ROOT / "data" / "preopen_dry_run_state.json") or {}
        status["preopen_dry_run_status"] = str(dry_run_state.get("status") or "NOT_RUN")
        status["preopen_dry_run_message"] = dry_run_state.get("message")
    except Exception:
        pass
    
    active_log = _resolve_active_bot_log_file()
    if not active_log.exists():
        return status
    
    try:
        with open(active_log, 'r') as f:
            lines = f.readlines()[-200:]  # Read last 200 lines for recent activity
            file_all = open(active_log, 'r').read()  # Read entire file for startup messages
        
        log_text = ''.join(lines)

        # Keep continuation indicator cards in sync with decision logs only when
        # candle-derived scoring is unavailable.
        if not candle_indicator_snapshot:
            current_indicator_section = None
            for raw_line in lines:
                line_text = str(raw_line or "").strip()
                upper_line = line_text.upper()
                if "CALL" in upper_line and "════" in line_text:
                    current_indicator_section = "CALL"
                    continue
                if "PUT" in upper_line and "════" in line_text:
                    current_indicator_section = "PUT"
                    continue

                score_match = re.search(r"Score:\s*(\d+)\s*/\s*(\d+)", line_text)
                if score_match and current_indicator_section in {"CALL", "PUT"}:
                    passed = int(score_match.group(1))
                    total = int(score_match.group(2))
                    status["continuation_indicators_total"] = total
                    if current_indicator_section == "CALL":
                        status["continuation_call_passed"] = passed
                    else:
                        status["continuation_put_passed"] = passed
        
        # Parse status indicators - startup messages that appear early, check entire file
        file_all_upper = file_all.upper()
        if "MODE: LIVE TRADING" in file_all_upper or "LIVE ENGINE CONFIGURED" in file_all_upper:
            status["mode"] = "LIVE TRADING"
        elif "MODE: PAPER TRADING" in file_all_upper:
            status["mode"] = "PAPER TRADING"
        
        # For account verification, check entire file since it only prints at startup
        if "Account Verified:" in file_all and "33310903" in file_all:
            status["account_verified"] = True
        
        # For broker reconciliation, check entire file since it's a startup process
        if "Broker reconciliation successful" in file_all:
            status["broker_reconciliation"] = "SUCCESS"
        elif "BROKER RECONCILIATION FAILED" in file_all:
            status["broker_reconciliation"] = "FAILED"
        elif "SAFE MODE ACTIVATED" in file_all:
            status["broker_reconciliation"] = "SAFE MODE"
        
        # Count pending orders
        if "pending SPY option order" in log_text:
            match = re.search(r'(\d+) pending SPY option order', log_text)
            if match:
                status["pending_orders"] = int(match.group(1))

        # Parse latest decision line + no-trade reason from recent logs.
        recent_lines = [ln.strip() for ln in lines if ln.strip()]

        # Use the latest candle timestamp emitted by the monitor, rather than
        # the log-file write time, for the banner candle clock.
        for line in reversed(file_all.splitlines()):
            candle_match = re.search(
                r"^Candles received:.*\blatest=(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\b",
                line,
                re.IGNORECASE,
            )
            if not candle_match:
                continue
            try:
                candle_at = datetime.fromisoformat(candle_match.group(1)).replace(tzinfo=timezone.utc)
                status["last_candle_at"] = candle_at.astimezone(EASTERN_TZ).isoformat()
                status["candle_age_seconds"] = round(
                    max(0.0, (datetime.now(timezone.utc) - candle_at).total_seconds()),
                    1,
                )
                break
            except ValueError:
                continue

        # Use the exact trend classification emitted for the latest evaluated candle.
        for line in reversed(recent_lines):
            text = str(line or "").strip()
            if not text:
                continue
            m_trend = re.search(
                r"(?:^Trend:\s*|\|\s*)(BULL_TREND|BEAR_TREND|NEUTRAL)\b",
                text,
                re.IGNORECASE,
            )
            if not m_trend:
                continue

            raw_trend = str(m_trend.group(1) or "UNKNOWN").upper()
            status["trend"] = raw_trend
            status["market_trend"] = raw_trend
            break

        def _extract_side_reasons(reason_text: str):
            text = str(reason_text or "").strip()
            if not text:
                return None, None

            call_reason = None
            put_reason = None

            m_call = re.search(r"CALL\s+(.+?)(?:;\s*PUT\s+|$)", text, re.IGNORECASE)
            if m_call:
                call_reason = m_call.group(1).strip()

            m_put = re.search(r"PUT\s+(.+?)(?:;\s*CALL\s+|$)", text, re.IGNORECASE)
            if m_put:
                put_reason = m_put.group(1).strip()

            # If reason is global (not side-tagged), show same reason for both sides.
            if call_reason is None and put_reason is None:
                return text, text

            return call_reason, put_reason

        for i in range(len(recent_lines) - 1, -1, -1):
            line_text = recent_lines[i]
            if line_text.startswith("NO TRADE "):
                status["last_decision"] = "NO_TRADE"
                for j in range(i + 1, min(i + 6, len(recent_lines))):
                    if recent_lines[j].startswith("Reason:"):
                        reason_text = recent_lines[j].replace("Reason:", "", 1).strip()
                        status["last_decision_reason"] = reason_text
                        call_reason, put_reason = _extract_side_reasons(reason_text)
                        status["last_no_trade_call_reason"] = call_reason
                        status["last_no_trade_put_reason"] = put_reason
                        break
                break
            if line_text.startswith("ENTER CALL ") or line_text.startswith("ENTER PUT "):
                status["last_decision"] = "ENTER"
                break
        
        # Get last actionable error (ignore DEBUG/state dump noise).
        error_markers = (
            "ERROR",
            "❌",
            "BROKER RECONCILIATION FAILED",
            "SAFE MODE ACTIVATED",
            "ENTRY BLOCKED",
            "blocked",
        )
        for line in reversed(lines):
            line_text = line.strip()
            if not line_text:
                continue
            if line_text.startswith("DEBUG") or "current_position = Position(" in line_text:
                continue
            if any(marker in line_text for marker in error_markers):
                status["last_error"] = line_text
                break

        # Compute quick, explicit trade-entry readiness state.
        enabled = True
        reason = "Ready for new entries"

        market_open_now = _is_market_hours_now_et()

        if not status["bot_running"]:
            enabled = False
            reason = "Bot is not running"
        elif not market_open_now:
            enabled = False
            reason = "Market Closed"
        elif status.get("heartbeat_ok") is False:
            enabled = False
            reason = "Bot heartbeat is stale"
        elif status.get("mode") != "LIVE TRADING":
            enabled = False
            reason = f"Mode is {status.get('mode', 'UNKNOWN')}"
        elif not status.get("account_verified"):
            enabled = False
            reason = "Trading account is not verified"
        elif status.get("broker_reconciliation") in {"FAILED", "SAFE MODE"}:
            enabled = False
            reason = f"Broker reconciliation is {status.get('broker_reconciliation')}"
        elif status.get("on_ethernet") is False:
            enabled = False
            reason = "Primary network is not Ethernet"
        elif status.get("current_position"):
            enabled = False
            reason = "Already in an open position"
        elif status.get("entry_paused"):
            enabled = False
            reason = "Entries paused by Cockpit"
        else:
            # Check only most recent lines so stale historical lock messages don't dominate.
            recent = [ln.strip() for ln in lines[-80:] if ln.strip()]
            for i in range(len(recent) - 1, -1, -1):
                text = recent[i]
                if "LIVE ENTRY DISABLED" in text:
                    enabled = False
                    reason = text.replace("🔒", "").strip()
                    for j in range(i + 1, min(i + 4, len(recent))):
                        if recent[j].startswith("Reason:"):
                            reason = recent[j].replace("Reason:", "").strip()
                            break
                    break
                if "ENTRY_PENDING LOCK ACTIVATED" in text:
                    enabled = False
                    reason = "Previous entry order is still pending fill"
                    break

        normalized_reason = normalize_reason_text(reason)
        status["trade_entry_enabled"] = enabled
        status["trade_entry_state"] = "ENABLED" if enabled else "DISABLED"
        status["trade_entry_reason"] = normalized_reason
        status["trade_entry_reason_code"] = reason_code_from_text(normalized_reason)
        status["trade_entry_reason_short"] = normalized_reason
        status["decision_contract"] = {
            "decision": "ENTER" if enabled else "NO_ENTRY",
            "reason": normalized_reason,
            "reason_code": status["trade_entry_reason_code"],
            "source": "cockpit_trade_entry_gate",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    except Exception as e:
        status["last_error"] = f"Error reading status: {str(e)}"

    today_key = datetime.now(EASTERN_TZ).date().isoformat()
    preopen_status = str(status.get("preopen_dry_run_status") or "NOT_RUN").upper()
    config_validation = _validate_runtime_config()
    status["config_validation"] = config_validation
    status["config_snapshot"] = {
        "spy_quote_refresh_seconds_open": SPY_QUOTE_REFRESH_SECONDS_OPEN,
        "spy_quote_refresh_seconds_closed": SPY_QUOTE_REFRESH_SECONDS_CLOSED,
        "broker_pnl_refresh_seconds": BROKER_PNL_REFRESH_SECONDS,
        "status_snapshot_cache_seconds": STATUS_SNAPSHOT_CACHE_SECONDS,
    }
    runtime_alert = _load_runtime_alert_flag()
    status["runtime_alert_active"] = bool(runtime_alert.get("active"))
    status["runtime_alert_message"] = str(runtime_alert.get("message") or "").strip() or None
    status["runtime_alert_severity"] = str(runtime_alert.get("severity") or "").strip() or None
    status["runtime_alert_updated_at"] = runtime_alert.get("updated_at")
    status["ops_readiness"] = {
        "pnl_source_current": bool(status.get("broker_pnl_source_file")) and str(status.get("broker_pnl_as_of_date") or "") == today_key,
        "daily_email_armed": bool(status.get("trade_log_email_armed")),
        "no_orphan_orders": int(status.get("pending_orders") or 0) == 0,
        "local_position_clear": not bool(status.get("has_open_position")),
        "latest_export_found": bool(status.get("broker_pnl_source_file")),
        "schema_ok": bool(status.get("trade_log_schema_ok")),
        "preopen_dry_run_ok": preopen_status == "SUCCESS",
        "config_ok": bool(config_validation.get("ok")),
        "runtime_alert_clear": not bool(status.get("runtime_alert_active")),
    }
    status["problem_messages"] = _build_problem_messages(status)
    status["problem_summary"] = status["problem_messages"][0] if status["problem_messages"] else None
    internet_quality = str((status.get("internet_quality") or {}).get("quality") or "UNKNOWN").upper()
    if _is_market_hours_now_et() and internet_quality in {"DEGRADED", "DOWN"}:
        status["internet_market_warning"] = True
        status["internet_market_warning_message"] = f"Market-hours internet warning: {internet_quality}"
    else:
        status["internet_market_warning"] = False
        status["internet_market_warning_message"] = None

    try:
        _maybe_notify_bot_stop(status)
    except Exception:
        pass
    
    return status

