from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ReplayValidationResult:
    passed: bool
    outputs_identical: bool
    audits_identical: bool
    hashes_identical: bool
    execution_order_identical: bool
    replay_hash: str


class ReplayValidator:
    def validate(self, runner: Callable[[], Mapping[str, Any]]) -> ReplayValidationResult:
        first = dict(runner())
        second = dict(runner())

        first_hash = self._hash_payload(first)
        second_hash = self._hash_payload(second)

        outputs_identical = first.get("result") == second.get("result")
        audits_identical = first.get("audit") == second.get("audit")
        execution_order_identical = first.get("execution_order") == second.get("execution_order")
        hashes_identical = first_hash == second_hash
        passed = outputs_identical and audits_identical and execution_order_identical and hashes_identical

        return ReplayValidationResult(
            passed=passed,
            outputs_identical=outputs_identical,
            audits_identical=audits_identical,
            hashes_identical=hashes_identical,
            execution_order_identical=execution_order_identical,
            replay_hash=first_hash,
        )

    @staticmethod
    def _hash_payload(payload: Mapping[str, Any]) -> str:
        text = repr(sorted(payload.items()))
        return sha256(text.encode("utf-8")).hexdigest()
