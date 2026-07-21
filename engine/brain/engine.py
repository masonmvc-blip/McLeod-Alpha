"""Canonical live trading decision engine.

Only lifecycle methods on :class:`Brain` are part of the live decision API.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from . import live_rules
from . import risk


MAX_TRADE_HOLD_MINUTES = 20
OPTION_MIN_DAYS_TO_EXPIRY = 7
OPTION_MIN_DAILY_VOLUME = 500
OPTION_MAX_ABSOLUTE_SPREAD = 0.05
OPTION_MAX_SPREAD_PCT = 8.0
ALLOWED_EXIT_REASONS = {
    "STOP",
    "2% Stop",
    "3% Stop",
    "4% TRAIL",
    "5% TRAIL",
    "6% TRAIL",
    "7% TRAIL",
    "8% TRAIL",
    "MANUAL_EXIT_LIMIT",
    "MANUAL_EXIT_MARKET",
    "TARGET_HIT",
    "PROTECTIVE_STOP_SYNC_FAILED",
    "BROKER_RECONCILED_EXIT",
}


class TradeAction(StrEnum):
    """Every broker-facing instruction the Brain may issue for an open trade."""

    HOLD = "HOLD"
    UPDATE_STOP = "UPDATE_STOP"
    RESTORE_PROTECTIVE_STOP = "RESTORE_PROTECTIVE_STOP"
    MOVE_STOP_TO_BREAK_EVEN = "MOVE_STOP_TO_BREAK_EVEN"
    TAKE_PARTIAL_PROFIT = "TAKE_PARTIAL_PROFIT"
    EXIT = "EXIT"
    BLOCK_NEW_ENTRIES = "BLOCK_NEW_ENTRIES"


@dataclass(frozen=True)
class TradeDecision:
    """Complete, serializable Brain instruction for one trade-management cycle."""

    action: TradeAction
    reason: str
    state_transition: str
    stop_price: float | None = None
    quantity: int | None = None
    exit_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntryDecision:
    """Broker-neutral instruction for whether a new entry may proceed."""

    allowed: bool
    reason: str | None = None


class Brain:
    """Own the live market-to-trade decision lifecycle."""

    def evaluate_market(self, last, previous) -> dict:
        """Classify the closed-candle market regime."""
        return {"regime": live_rules.classify_entry_regime(last, previous)}

    def evaluate_entry(self, last, previous, candles) -> dict:
        """Score a closed candle and return the single eligible entry candidate."""
        market = self.evaluate_market(last, previous)
        call_score, call_reasons = self._score_call(last, previous)
        put_score, put_reasons = self._score_put(last, previous)
        volume = self._volume_momentum(candles)
        self._apply_volume_adjustment(last, volume, call_reasons, put_reasons, scores := {
            "CALL": call_score,
            "PUT": put_score,
        })

        direction = None
        if live_rules.is_entry_eligible("CALL", market["regime"], scores["CALL"]):
            direction = "CALL"
        elif live_rules.is_entry_eligible("PUT", market["regime"], scores["PUT"]):
            direction = "PUT"

        return {
            **market,
            "direction": direction,
            "call_score": scores["CALL"],
            "put_score": scores["PUT"],
            "call_reasons": call_reasons,
            "put_reasons": put_reasons,
            "volume": volume,
        }

    def build_trade(self, direction: str, entry_price: float) -> dict:
        """Build the canonical broker-ready trade plan for an eligible entry."""
        stop, target, quantity = live_rules.build_entry_risk_plan(direction, entry_price)
        normalized_direction = str(direction).upper()
        return {
            "direction": normalized_direction,
            "entry": float(entry_price),
            "stop": stop,
            "target": target,
            "quantity": quantity,
            "reason": "PHASE2_BULL_CALL" if normalized_direction == "CALL" else "PHASE2_BEAR_PUT",
        }

    @staticmethod
    def select_option_expiration(expirations, *, as_of: date | None = None) -> str:
        """Choose the canonical weekly expiration from adapter-supplied chain facts."""
        today = as_of or date.today()
        eligible_expirations = []
        for expiration_key in (expirations or {}):
            try:
                expiration_date = datetime.strptime(str(expiration_key).split(":", 1)[0], "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            if expiration_date.weekday() == 4 and (expiration_date - today).days >= OPTION_MIN_DAYS_TO_EXPIRY:
                eligible_expirations.append((expiration_date, expiration_key))
        if not eligible_expirations:
            raise ValueError("No Friday expiration at least 7 days away was found")

        return min(eligible_expirations)[1]

    def select_option_contract(self, option_chain, direction: str, underlying_price: float, *, as_of: date | None = None):
        """Select the eligible option contract from adapter-supplied chain facts."""
        normalized_direction = str(direction or "").upper()
        chain_key = "callExpDateMap" if normalized_direction == "CALL" else "putExpDateMap"
        expirations = (option_chain or {}).get(chain_key) or {}

        eligible_expirations = []
        reference_date = as_of or date.today()
        for expiration_key in expirations:
            try:
                expiration_date = datetime.strptime(str(expiration_key).split(":", 1)[0], "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            if expiration_date.weekday() == 4 and (expiration_date - reference_date).days >= OPTION_MIN_DAYS_TO_EXPIRY:
                eligible_expirations.append((expiration_date, expiration_key))

        for _, expiration_key in sorted(eligible_expirations):
            candidates = []
            for strike, contracts in (expirations.get(expiration_key) or {}).items():
                for contract in contracts or []:
                    try:
                        bid = float(contract.get("bid") or 0.0)
                        ask = float(contract.get("ask") or 0.0)
                        mark = float(contract.get("mark") or 0.0)
                        volume = int(contract.get("totalVolume") or 0)
                        open_interest = int(contract.get("openInterest") or 0)
                        strike_price = float(strike)
                    except (TypeError, ValueError):
                        continue
                    if bid <= 0 or ask <= 0 or mark <= 0:
                        continue
                    spread = ask - bid
                    spread_pct = (spread / mark) * 100.0
                    if spread > OPTION_MAX_ABSOLUTE_SPREAD or spread_pct > OPTION_MAX_SPREAD_PCT:
                        continue
                    if volume < OPTION_MIN_DAILY_VOLUME:
                        continue
                    candidates.append({
                        **contract,
                        "direction": normalized_direction,
                        "expiration": expiration_key,
                        "strike": strike,
                        "bid": bid,
                        "ask": ask,
                        "mark": mark,
                        "volume": volume,
                        "open_interest": open_interest,
                        "spread": spread,
                        "spread_pct": spread_pct,
                        "_strike_distance": abs(strike_price - float(underlying_price)),
                    })
            if candidates:
                selected = max(
                    candidates,
                    key=lambda option: (option["volume"], option["open_interest"], -option["_strike_distance"]),
                )
                selected.pop("_strike_distance", None)
                return selected
        return None

    def evaluate_entry_runtime_guard(
        self,
        *,
        quantity,
        required_quantity: int,
        safe_mode: bool,
        submission_rejected: bool,
        max_quantity_exceeded: bool,
        protective_stop_failed: bool,
        entry_pending: bool,
        already_in_trade: bool,
    ) -> EntryDecision:
        """Apply local lifecycle locks before the adapter queries broker state."""
        try:
            normalized_quantity = int(quantity)
        except (TypeError, ValueError):
            return EntryDecision(False, "invalid_contract_quantity")
        if normalized_quantity != int(required_quantity):
            return EntryDecision(False, "contract_quantity_must_equal_max")
        if safe_mode:
            return EntryDecision(False, "safe_mode")
        if submission_rejected:
            return EntryDecision(False, "submission_rejected_lock")
        if max_quantity_exceeded:
            return EntryDecision(False, "max_quantity_exceeded_lock")
        if protective_stop_failed:
            return EntryDecision(False, "protective_stop_failed_lock")
        if entry_pending:
            return EntryDecision(False, "entry_pending_lock")
        if already_in_trade:
            return EntryDecision(False, "already_in_trade")
        return EntryDecision(True)

    def evaluate_startup_entry_admission(self, *, attempted_entries: int, blocked_attempts: int) -> EntryDecision:
        """Apply the startup lifecycle gate from adapter-supplied attempt facts."""
        if int(attempted_entries or 0) < max(0, int(blocked_attempts or 0)):
            return EntryDecision(False, "startup_guard")
        return EntryDecision(True)

    def evaluate_entry_admission(
        self,
        *,
        has_broker_exposure: bool,
        risk_allowed: bool,
        risk_block_reason: str | None,
        has_option_symbol: bool,
    ) -> EntryDecision:
        """Apply entry eligibility to adapter-supplied broker and risk facts."""
        if has_broker_exposure:
            return EntryDecision(False, "existing_schwab_spy_option_exposure")
        if not risk_allowed:
            return EntryDecision(False, f"risk_block:{risk_block_reason}")
        if not has_option_symbol:
            return EntryDecision(False, "missing_option_symbol")
        return EntryDecision(True)

    def evaluate_startup_reconciliation(
        self,
        *,
        broker_available: bool,
        exposure_quantity: float,
        required_quantity: int,
        has_protective_stop: bool,
    ) -> EntryDecision:
        """Decide whether broker-reconciled startup state permits new entries."""
        if not broker_available:
            return EntryDecision(False, "safe_mode")
        if float(exposure_quantity or 0.0) > float(required_quantity):
            return EntryDecision(False, "max_quantity_exceeded_lock")
        if float(exposure_quantity or 0.0) > 0 and not has_protective_stop:
            return EntryDecision(False, "protective_stop_failed_lock")
        return EntryDecision(True)

    @staticmethod
    def initial_protective_stop(option_entry_price) -> float:
        """Return the canonical initial protective stop before broker tick rounding."""
        entry = Brain._positive_float(option_entry_price)
        return entry * 0.95 if entry else 0.0

    def evaluate_entry_quote(self, quote_snapshot, *, max_age_seconds: float, max_spread_pct: float) -> EntryDecision:
        """Fail closed when adapter-provided option quote facts are not tradeable."""
        issues = []
        quote_age_seconds = quote_snapshot.get("quote_age_seconds")
        if quote_age_seconds is not None and float(quote_age_seconds) > float(max_age_seconds):
            issues.append(f"stale quote ({float(quote_age_seconds):.1f}s old > {float(max_age_seconds):.1f}s max)")
        quote_spread_pct = quote_snapshot.get("quote_spread_pct")
        if quote_spread_pct is not None and float(quote_spread_pct) > float(max_spread_pct):
            issues.append(f"wide quote spread ({float(quote_spread_pct):.2f}% > {float(max_spread_pct):.2f}% max)")
        return EntryDecision(not issues, "; ".join(issues) if issues else None)

    def manage_trade(self, position, market) -> TradeDecision:
        """Apply the canonical live stop ladder and return one execution instruction."""
        if position is None:
            return TradeDecision(
                action=TradeAction.HOLD,
                reason="no_open_position",
                state_transition="FLAT",
            )

        current_price = float(market.get("current_price") or 0.0)
        now = market.get("now") or datetime.now()
        option_mark = self._positive_float(market.get("option_mark"))
        option_bid = self._positive_float(market.get("option_bid"))
        use_price = option_bid or option_mark
        option_entry = self._positive_float(getattr(position, "option_entry", 0.0))
        current_stop = self._positive_float(getattr(position, "option_stop", 0.0))
        initial_stop = self._positive_float(getattr(position, "option_initial_stop", 0.0))
        state_updates: dict[str, Any] = {}

        early_exit = self.evaluate_exit(
            position,
            {
                **market,
                "current_price": current_price,
                "option_mark": option_mark,
                "state_updates": state_updates,
            },
            conditions=("manual", "max_hold"),
        )
        if early_exit.action is TradeAction.EXIT:
            return early_exit

        if option_entry <= 0:
            return TradeDecision(
                action=TradeAction.HOLD,
                reason="missing_option_entry_price",
                state_transition="POSITION_OPEN",
            )

        if initial_stop <= 0:
            initial_stop = self.initial_protective_stop(option_entry)
            current_stop = initial_stop
            state_updates = {"option_initial_stop": initial_stop, "option_stop": current_stop}

        if market.get("protective_stop_active") is False:
            return TradeDecision(
                action=TradeAction.RESTORE_PROTECTIVE_STOP,
                reason="protective_stop_missing",
                state_transition="POSITION_UNPROTECTED",
                stop_price=current_stop,
                quantity=int(getattr(position, "quantity", 0) or 0),
                metadata={"state_updates": state_updates},
            )

        trailing_quote = option_bid or option_mark
        if trailing_quote:
            profit_pct = ((trailing_quote - option_entry) / option_entry) * 100.0
            candidate_stop, stop_type = self._trailing_stop(option_entry, initial_stop, trailing_quote, profit_pct)
            if candidate_stop > current_stop:
                state_updates["option_stop"] = candidate_stop
                return TradeDecision(
                    action=TradeAction.UPDATE_STOP,
                    reason=stop_type,
                    state_transition="POSITION_OPEN",
                    stop_price=candidate_stop,
                    quantity=int(getattr(position, "quantity", 0) or 0),
                    metadata={"profit_pct": profit_pct, "state_updates": state_updates},
                )

        return self.evaluate_exit(
            position,
            {
                **market,
                "current_price": current_price,
                "option_mark": option_mark,
                "option_bid": option_bid,
                "option_stop": current_stop,
                "state_updates": state_updates,
            },
            conditions=("stop", "target"),
        )

    def evaluate_exit(self, position, market, conditions=("manual", "max_hold", "stop", "target")) -> TradeDecision:
        """Return the canonical exit instruction for the supplied trade state."""
        if position is None:
            return TradeDecision(
                action=TradeAction.HOLD,
                reason="no_open_position",
                state_transition="FLAT",
            )

        enabled = set(conditions)
        current_price = float(market.get("current_price") or 0.0)
        option_mark = self._positive_float(market.get("option_mark"))
        option_bid = self._positive_float(market.get("option_bid"))
        option_entry = self._positive_float(getattr(position, "option_entry", 0.0))
        option_stop = self._positive_float(market.get("option_stop", getattr(position, "option_stop", 0.0)))
        state_updates = dict(market.get("state_updates") or {})

        if "manual" in enabled and market.get("manual_exit"):
            return TradeDecision(
                action=TradeAction.EXIT,
                reason=str(market.get("manual_exit_reason") or "MANUAL_EXIT_MARKET"),
                state_transition="EXIT_REQUESTED",
                exit_price=current_price,
                metadata={"state_updates": state_updates, "exit_option_mark": option_mark},
            )

        opened = getattr(position, "opened", None)
        now = market.get("now") or datetime.now()
        if "max_hold" in enabled and isinstance(opened, datetime) and now - opened >= timedelta(minutes=MAX_TRADE_HOLD_MINUTES):
            return TradeDecision(
                action=TradeAction.EXIT,
                reason="MAX_HOLD_20_MIN",
                state_transition="EXIT_REQUESTED",
                exit_price=current_price,
                metadata={"state_updates": state_updates, "exit_option_mark": option_mark},
            )

        use_price = option_bid or option_mark
        if "stop" in enabled and option_entry > 0 and use_price and option_stop > 0 and use_price <= option_stop:
            if market.get("protective_stop_active"):
                return TradeDecision(
                    action=TradeAction.HOLD,
                    reason="broker_protective_stop_active",
                    state_transition="BROKER_EXIT_PENDING",
                    metadata={"state_updates": state_updates},
                )
            return TradeDecision(
                action=TradeAction.EXIT,
                reason=self._stop_exit_reason(option_entry, use_price),
                state_transition="EXIT_REQUESTED",
                exit_price=use_price,
                metadata={"state_updates": state_updates, "exit_option_mark": option_mark},
            )

        direction = str(getattr(position, "direction", "")).upper()
        target = float(getattr(position, "target_price", 0.0) or 0.0)
        if "target" in enabled and target > 0 and ((direction == "CALL" and current_price >= target) or (direction == "PUT" and current_price <= target)):
            return TradeDecision(
                action=TradeAction.EXIT,
                reason="TARGET_HIT",
                state_transition="EXIT_REQUESTED",
                exit_price=current_price,
                metadata={"state_updates": state_updates, "exit_option_mark": option_mark},
            )

        return TradeDecision(
            action=TradeAction.HOLD,
            reason="exit_conditions_not_triggered",
            state_transition="POSITION_OPEN",
            metadata={"market": market},
        )

    def evaluate_protective_stop_result(self, position, *, restored: bool, restore_count: int) -> TradeDecision:
        """Decide the lifecycle state after the adapter attempts stop protection."""
        if not restored:
            return TradeDecision(
                action=TradeAction.EXIT,
                reason="PROTECTIVE_STOP_SYNC_FAILED",
                state_transition="EXIT_REQUESTED",
                exit_price=None,
            )

        if int(restore_count or 0) > 1:
            return TradeDecision(
                action=TradeAction.BLOCK_NEW_ENTRIES,
                reason="repeated_protective_stop_restore",
                state_transition="POSITION_PROTECTED_ENTRY_BLOCKED",
            )

        return TradeDecision(
            action=TradeAction.HOLD,
            reason="protective_stop_restored",
            state_transition="POSITION_OPEN",
        )

    def normalize_exit_reason(self, reason, option_entry_price, option_exit_price) -> str:
        """Map execution outcomes onto the canonical exit-reason vocabulary."""
        reason_text = str(reason or "").strip()
        stop_like = {
            "OPTION_STOP",
            "STOP_LOSS",
            "TRAILING_STOP",
            "STOP",
            "4-5%",
            "5-6%",
            "6%+",
            "3-5%",
            "5-7%",
            "7%+",
        }
        if reason_text in stop_like:
            return self._stop_exit_reason(option_entry_price, option_exit_price)
        if reason_text not in ALLOWED_EXIT_REASONS:
            return "TARGET_HIT"
        return reason_text

    def update_memory(self, *, pnl=None, stopped=False) -> None:
        """Update Brain-owned live risk memory after an execution outcome."""
        if pnl is not None:
            risk.record_trade(pnl)
        if stopped:
            risk.record_stop()

    @staticmethod
    def _positive_float(value) -> float:
        try:
            numeric = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return numeric if numeric > 0 else 0.0

    @staticmethod
    def _trailing_stop(entry, initial_stop, quote, profit_pct) -> tuple[float, str]:
        if profit_pct >= 8:
            return quote * 0.99, "Trail 1%"
        if profit_pct >= 7:
            return quote * 0.985, "Trail 1.5%"
        if profit_pct >= 6:
            return quote * 0.98, "Trail 2%"
        if profit_pct >= 5:
            return quote * 0.975, "Trail 2.5%"
        if profit_pct >= 4:
            return quote * 0.97, "Trail 3%"
        if profit_pct >= 3:
            return entry * 0.99, "3% Entry Lock"
        if profit_pct >= 2:
            return entry * 0.97, "2% Entry Lock"
        return initial_stop, "Initial 5%"

    @staticmethod
    def _stop_exit_reason(entry, exit_price) -> str:
        profit_pct = ((float(exit_price) - float(entry)) / float(entry)) * 100.0
        if profit_pct >= 8:
            return "8% TRAIL"
        if profit_pct >= 7:
            return "7% TRAIL"
        if profit_pct >= 6:
            return "6% TRAIL"
        if profit_pct >= 5:
            return "5% TRAIL"
        if profit_pct >= 4:
            return "4% TRAIL"
        if profit_pct >= 3:
            return "3% Stop"
        if profit_pct >= 2:
            return "2% Stop"
        return "STOP"

    @staticmethod
    def _active_stop_reason(position) -> str:
        """Preserve the stop tier the Brain previously instructed the broker to use."""
        return str(getattr(position, "active_stop_reason", "") or "STOP")

    @staticmethod
    def _score_call(last, previous) -> tuple[int, list[str]]:
        score, reasons = 0, []
        if last.close > last.vwap:
            score, reasons = score + 1, reasons + ["price_above_vwap"]
        if last.ema10 > last.ema20 > last.ema50:
            score, reasons = score + 2, reasons + ["bull_ema_stack"]
        if last.ema10 > previous.ema10:
            score, reasons = score + 1, reasons + ["ema10_rising"]
        if last.macd_hist > previous.macd_hist:
            score, reasons = score + 1, reasons + ["macd_improving"]
        if last.close > previous.high:
            score, reasons = score + 1, reasons + ["breaks_prev_high"]
        return score, reasons

    @staticmethod
    def _score_put(last, previous) -> tuple[int, list[str]]:
        score, reasons = 0, []
        if last.close < last.vwap:
            score, reasons = score + 1, reasons + ["price_below_vwap"]
        if last.ema10 < last.ema20 < last.ema50:
            score, reasons = score + 2, reasons + ["bear_ema_stack"]
        if last.ema10 < previous.ema10:
            score, reasons = score + 1, reasons + ["ema10_falling"]
        if last.macd_hist < previous.macd_hist:
            score, reasons = score + 1, reasons + ["macd_weakening"]
        if last.close < previous.low:
            score, reasons = score + 1, reasons + ["breaks_prev_low"]
        return score, reasons

    @staticmethod
    def _volume_momentum(candles) -> dict:
        if len(candles) < 6:
            return {"trend": "UNKNOWN", "current_volume": 0, "avg_volume": 0, "volume_ratio": 0}
        current = float(candles.iloc[-1]["volume"])
        average = float(candles.iloc[-6:-1]["volume"].mean())
        ratio = current / average if average > 0 else 0
        trend = "INCREASING" if ratio >= 1.25 else "DECREASING" if ratio <= 0.80 else "NEUTRAL"
        return {"trend": trend, "current_volume": current, "avg_volume": average, "volume_ratio": ratio}

    @staticmethod
    def _apply_volume_adjustment(last, volume, call_reasons, put_reasons, scores) -> None:
        if float(last.close) > float(last.open):
            direction, reason = "CALL", "bullish_move"
        elif float(last.close) < float(last.open):
            direction, reason = "PUT", "bearish_move"
        else:
            return
        adjustment = {"INCREASING": 1, "DECREASING": -1}.get(volume["trend"], 0)
        if not adjustment:
            return
        scores[direction] += adjustment
        reasons = call_reasons if direction == "CALL" else put_reasons
        reasons.append(f"volume_{'confirming' if adjustment > 0 else 'weakening'}_{reason}")