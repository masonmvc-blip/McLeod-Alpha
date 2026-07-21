#!/usr/bin/env python3
"""Compare Cockpit runtime fingerprints across two hosts."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


COMPARE_KEYS = (
    "cockpit_sha256",
    "bot_script_sha256",
    "python_version",
    "dependency_hash",
    "bot_python_mode",
)


@dataclass
class HostSnapshot:
    label: str
    url: str
    hostname: str
    parity_state: str
    parity_summary: str
    fingerprint: dict[str, Any]


def _status_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {base_url}")
    path = parsed.path.rstrip("/")
    endpoint = f"{path}/api/status" if path else "/api/status"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, endpoint, "", "", ""))


def _fetch_status(url: str, timeout: float, insecure: bool) -> dict[str, Any]:
    req = urllib.request.Request(url=url, headers={"Accept": "application/json"})
    context = None
    if insecure:
        context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Status payload is not a JSON object")
    return data


def _snapshot_from_status(label: str, base_url: str, status: dict[str, Any]) -> HostSnapshot:
    fp = status.get("runtime_fingerprint")
    fingerprint = fp if isinstance(fp, dict) else {}
    return HostSnapshot(
        label=label,
        url=base_url,
        hostname=str(fingerprint.get("hostname") or "unknown"),
        parity_state=str(status.get("parity_state") or "UNKNOWN"),
        parity_summary=str(status.get("parity_summary") or ""),
        fingerprint=fingerprint,
    )


def _short(value: Any, max_len: int = 14) -> str:
    text = str(value or "")
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}..."


def _print_host(snap: HostSnapshot) -> None:
    print(f"[{snap.label}] {snap.url}")
    print(f"  host={snap.hostname}")
    print(f"  parity={snap.parity_state} {snap.parity_summary}".rstrip())
    for key in COMPARE_KEYS:
        value = snap.fingerprint.get(key)
        print(f"  {key}={_short(value)}")


def _compare(a: HostSnapshot, b: HostSnapshot) -> list[str]:
    mismatches: list[str] = []
    for key in COMPARE_KEYS:
        av = a.fingerprint.get(key)
        bv = b.fingerprint.get(key)
        if av != bv:
            mismatches.append(
                f"{key} differs: {a.label}={_short(av, 24)} vs {b.label}={_short(bv, 24)}"
            )
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Cockpit parity across two hosts.")
    parser.add_argument("--url-a", required=True, help="First Cockpit base URL")
    parser.add_argument("--url-b", required=True, help="Second Cockpit base URL")
    parser.add_argument("--label-a", default="A", help="Display label for first host")
    parser.add_argument("--label-b", default="B", help="Display label for second host")
    parser.add_argument("--timeout", type=float, default=6.0, help="HTTP timeout in seconds")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (useful for local/Tailscale cert-store mismatches)",
    )
    args = parser.parse_args()

    try:
        status_a = _fetch_status(_status_url(args.url_a), timeout=args.timeout, insecure=args.insecure)
        status_b = _fetch_status(_status_url(args.url_b), timeout=args.timeout, insecure=args.insecure)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: unable to fetch status payloads ({exc})")
        return 2

    snap_a = _snapshot_from_status(args.label_a, args.url_a, status_a)
    snap_b = _snapshot_from_status(args.label_b, args.url_b, status_b)

    print("Cockpit Runtime Parity")
    print("=" * 34)
    _print_host(snap_a)
    _print_host(snap_b)
    print()

    mismatches = _compare(snap_a, snap_b)
    if mismatches:
        print("FAIL: runtime mismatch detected")
        for item in mismatches:
            print(f"  - {item}")
        print("Action: deploy same repo state + restart both hosts, then retest.")
        return 2

    print("PASS: runtime fingerprints match across both hosts")
    if args.url_a.strip().rstrip("/") == args.url_b.strip().rstrip("/"):
        print("Note: both inputs point to the same URL; compare two distinct hosts for full validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
