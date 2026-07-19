from __future__ import annotations


def normalize_reason_text(reason: str | None) -> str:
    text = str(reason or "").strip()
    if not text:
        return "Unknown"

    lowered = text.lower()
    if "market closed" in lowered or "outside regular market hours" in lowered:
        return "Market Closed"
    if "already in" in lowered and "trade" in lowered:
        return "Already In Trade"
    if "heartbeat" in lowered and "stale" in lowered:
        return "Heartbeat Stale"
    if "account" in lowered and "verified" in lowered:
        return "Account Not Verified"
    if "network" in lowered and "ethernet" in lowered:
        return "Network Not Ethernet"
    if "pending" in lowered and "fill" in lowered:
        return "Entry Pending Fill"
    if "startup" in lowered and "guard" in lowered:
        return "Startup Guard"

    return text


def reason_code_from_text(reason: str | None) -> str:
    normalized = normalize_reason_text(reason)
    lookup = {
        "Market Closed": "MARKET_CLOSED",
        "Already In Trade": "IN_TRADE",
        "Heartbeat Stale": "HEARTBEAT_STALE",
        "Account Not Verified": "ACCOUNT_NOT_VERIFIED",
        "Network Not Ethernet": "NETWORK_NOT_ETHERNET",
        "Entry Pending Fill": "ENTRY_PENDING_FILL",
        "Startup Guard": "STARTUP_GUARD",
        "Ready for new entries": "READY",
        "Ready For New Entries": "READY",
        "Unknown": "UNKNOWN",
    }
    return lookup.get(normalized, "OTHER")


def quote_state_from_age(age_seconds: float | None, max_stale_seconds: float, refresh_seconds: float | None) -> str:
    if age_seconds is None:
        return "UNAVAILABLE"

    age = float(age_seconds)
    if age > float(max_stale_seconds):
        return "STALE"

    target = max(1.0, float(refresh_seconds or 1.0))
    if age <= (target * 1.5):
        return "FRESH"
    return "DELAYED"
