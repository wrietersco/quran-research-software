"""
Service E — rule-based post-corrections and Quran-oriented hooks (extensible).

Logs every rule application. Default: no mutation; register overrides later.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

RuleFn = Callable[[dict[str, Any]], dict[str, Any]]


def _rule_log(name: str, detail: str) -> None:
    logger.info("rules.apply: RULE[%s] %s", name, detail)


def apply_rules(
    record: dict[str, Any],
    *,
    extra_rules: list[RuleFn] | None = None,
) -> dict[str, Any]:
    """
    Apply built-in (currently identity) rules, then ``extra_rules`` in order.

    Mutates and returns the same dict for chaining.
    """
    _rule_log("identity", "baseline — no built-in mutation in this version")
    if extra_rules:
        for i, fn in enumerate(extra_rules):
            logger.debug("rules.apply: invoking extra_rule[%s] %s", i, fn.__name__)
            record = fn(record)
    else:
        logger.debug("rules.apply: no extra_rules registered")
    record.setdefault("rules_applied", [])
    if isinstance(record["rules_applied"], list):
        record["rules_applied"].append("identity_v1")
    return record
