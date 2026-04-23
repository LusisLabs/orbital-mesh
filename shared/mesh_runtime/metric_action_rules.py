"""Declarative metric-action rule engine.

# What this module is

When an OpenTelemetry signal arrives for a metric Mesh wasn't hand-coded to
recognize (e.g. ``kafka.consumer.lag``, ``redis.evictions_per_second``,
``queue.depth``), the original decision engine falls through to ``no_action``.
That's safe but useless — the operator has to either build out a hardcoded
branch in Python or manually steer every run.

This module fixes that gap with a **declarative rule registry**. Operators
author rules in JSON that say "when a metric shaped like X regresses by Y%,
propose action Z with parameters pulled from the signal's attributes". The
engine matches incoming signals against the rule set and returns a candidate
action that the decision stage can emit as a ``Decision``.

# Design goals

1. **Declarative over procedural.** Rules live in config, not code. Operators
   extend the catalog without pushing a new Python release.

2. **Safe by construction.** Every rule specifies its bounds up front — a
   ``scale_deployment`` rule with ``replicas_delta: [+1, +3]`` cannot produce
   a proposal to scale by 50. The engine enforces bounds at match time, so a
   typo in a template doesn't become a runaway actuation.

3. **Attribute-driven parameters.** Parameters are rendered from the signal's
   own OTel attributes using ``{resource_attributes.k8s.namespace.name}``
   placeholders. This keeps the rules portable — the same "scale on consumer
   lag" rule works across every service because the service identity comes
   from OTel, not the rule.

4. **Pattern matching, not 1:1.** A single rule matching metrics whose names
   contain ``(consumer_lag|queue_depth|backlog)`` covers Kafka, RabbitMQ,
   Celery, and SQS in one definition. One dozen patterns covers hundreds of
   specific metrics.

5. **Graceful fallthrough.** If no rule matches, the engine returns an empty
   candidate list. The decision stage then runs its existing fallback logic
   (typically ``no_action`` or ``escalate``). Adding rules can never make
   the system more aggressive than it was before — only more targeted.

# Rule file format

See ``policies/metric-actions.policy.json`` for the canonical example. Each
rule has:

- ``name``: human-readable identifier, shown in decision reasoning
- ``match``: a set of conditions that must all hold
- ``propose``: the action to emit when matched
- ``bounds``: optional guardrails on the proposed parameters

```json
{
  "rules": [
    {
      "name": "scale on consumer lag",
      "match": {
        "metric_name_pattern": "(consumer_lag|queue_depth|backlog|rabbitmq\\.queue\\.messages)",
        "direction": "increasing",
        "delta_pct_min": 30
      },
      "propose": {
        "decision_type": "scale_deployment",
        "system": "kubernetes_service",
        "action": "scale_deployment",
        "parameters": {
          "deployment_name": "{resource_attributes.k8s.deployment.name}",
          "namespace": "{resource_attributes.k8s.namespace.name}",
          "replicas_delta": 2
        }
      },
      "bounds": {
        "replicas_delta_max": 3,
        "cooldown_seconds": 300
      },
      "confidence": 0.78,
      "risk_level": "low",
      "rollback_plan": "scale deployment back to the prior replica count"
    }
  ]
}
```

# How matching works

The matcher evaluates conditions in this order, short-circuiting on the first
failure:

1. ``metric_name_pattern`` — a regex against the signal's metric name. Case-
   insensitive. A missing pattern matches everything (rarely what you want).
2. ``direction`` — ``increasing`` or ``decreasing``. Uses ``observed`` vs
   ``baseline`` from the signal's ``metric_regression`` block.
3. ``delta_pct_min`` / ``delta_pct_max`` — inclusive bounds on the relative
   change. ``None`` on either side means unbounded on that side.
4. ``resource_attributes`` — every key/value pair must be present on the
   signal's ``resource_attributes``. Supports wildcards: ``{"service.name": "*"}``
   means "attribute must exist" rather than "attribute must equal '*'".
5. ``attributes`` — same semantics but against the metric data point's
   attributes (things like ``http.route`` or ``k8s.pod.name``).

The first rule to match wins. Rule order in the registry is the tiebreaker —
operators are expected to put more specific rules first. There's no "best
match" scoring; rule files get reviewed by humans, and predictable ordering
beats cleverness for an audit-sensitive system.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


_LOG = logging.getLogger("mesh.decision.rules")


# Parameters that are purely structural (names, namespaces) — safe to interpolate
# from attributes as strings. Numeric parameters are kept separate so we never
# turn a stringy attribute into a replica count by accident.
_STRING_ATTRIBUTE_KEYS = {
    "deployment_name",
    "namespace",
    "cluster",
    "kube_context",
    "service",
    "flag_key",
    "environment",
    "container",
    "pod_name",
    "route",
}


@dataclass
class RuleMatch:
    """A rule that matched an incoming signal.

    ``parameters`` is already rendered — placeholders resolved against the signal
    and numeric bounds enforced. The decision stage can pass this straight to
    the actuator without re-processing.
    """

    rule_name: str
    decision_type: str
    system: str
    action: str
    parameters: dict[str, Any]
    confidence: float
    risk_level: str
    rollback_plan: str
    bounds: dict[str, Any] = field(default_factory=dict)
    matched_on: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricActionRule:
    """An in-memory representation of a rule after loading and basic validation.

    We keep rules as plain dataclasses rather than pydantic models because the
    rule surface is narrow and we want zero new dependencies. The loader
    performs enough validation at startup to surface bad rule files early; the
    matcher stays honest by only reading validated fields.
    """

    name: str
    match: dict[str, Any]
    propose: dict[str, Any]
    bounds: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.75
    risk_level: str = "medium"
    rollback_plan: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("rule name is required")
        required_propose_keys = {"decision_type", "system", "action", "parameters"}
        missing = required_propose_keys - set(self.propose)
        if missing:
            raise ValueError(f"rule {self.name!r} missing propose keys: {sorted(missing)}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError(f"rule {self.name!r} confidence must be between 0 and 1")
        if self.risk_level not in {"low", "medium", "high"}:
            raise ValueError(f"rule {self.name!r} risk_level must be low/medium/high")


class MetricActionMatcher:
    """Load a rule registry once and match many signals against it.

    Instantiate once at service startup (rule files are small, parsing is cheap
    but not free) and reuse across requests. The matcher is stateless beyond
    the loaded rules — safe to share across threads.
    """

    def __init__(self, rules: list[MetricActionRule]):
        self.rules = rules
        # Precompile regexes to keep matching fast on a hot path. A regex error
        # in a rule file should fail noisily at load time, not at the first
        # inbound alert when a human isn't watching.
        self._compiled_patterns: dict[str, re.Pattern[str]] = {}
        for rule in rules:
            pattern = rule.match.get("metric_name_pattern")
            if pattern:
                try:
                    self._compiled_patterns[rule.name] = re.compile(pattern, re.IGNORECASE)
                except re.error as exc:
                    raise ValueError(f"rule {rule.name!r} has invalid metric_name_pattern: {exc}") from exc

    def match(self, signal: dict[str, Any]) -> RuleMatch | None:
        """Return the first rule that matches the signal, or None.

        ``signal`` is an ``otel_metric_regression`` payload (see
        ``otel-metric-signal.schema.json``). The matcher reads ``metric_regression``,
        ``resource_attributes``, and ``metric_regression.attributes`` — those are
        the only fields a rule can match against.
        """
        # Log how many rules we're evaluating, at DEBUG so the normal
        # log stays focused on decisions rather than the path to them.
        # A DEBUG-level operator enabling it gets rule-by-rule visibility.
        metric_name = (signal.get("metric_regression") or {}).get("metric_name", "?")
        _LOG.debug("rules: evaluating %d rules against metric=%s", len(self.rules), metric_name)
        for rule in self.rules:
            matched_on = self._try_match(rule, signal)
            if matched_on is None:
                _LOG.debug("rules: skip %r", rule.name)
                continue
            rendered = self._render_parameters(rule, signal)
            _LOG.info(
                "rules: match rule=%r metric=%s action=%s",
                rule.name, metric_name, rule.propose["action"],
            )
            return RuleMatch(
                rule_name=rule.name,
                decision_type=rule.propose["decision_type"],
                system=rule.propose["system"],
                action=rule.propose["action"],
                parameters=rendered,
                confidence=float(rule.confidence),
                risk_level=rule.risk_level,
                rollback_plan=rule.rollback_plan or f"undo the last {rule.propose['action']} action",
                bounds=dict(rule.bounds),
                matched_on=matched_on,
            )
        _LOG.info("rules: no match for metric=%s after evaluating %d rules", metric_name, len(self.rules))
        return None

    # --- match evaluation -----------------------------------------------------

    def _try_match(self, rule: MetricActionRule, signal: dict[str, Any]) -> dict[str, Any] | None:
        """Evaluate all match conditions. Return the captured evidence, or None.

        The returned dict is stamped into ``RuleMatch.matched_on`` so the
        decision reasoning can cite exactly which conditions passed — critical
        for audit trails and human review.
        """
        metric_regression = signal.get("metric_regression") or {}
        metric_name = metric_regression.get("metric_name", "")
        observed = metric_regression.get("observed_value")
        baseline = metric_regression.get("baseline_value")
        delta_pct = metric_regression.get("delta_pct")
        resource_attrs = signal.get("resource_attributes") or {}
        attrs = metric_regression.get("attributes") or {}

        match_spec = rule.match
        evidence: dict[str, Any] = {}

        # 1. Metric name regex.
        pattern = self._compiled_patterns.get(rule.name)
        if pattern is not None:
            if not pattern.search(metric_name):
                return None
            evidence["metric_name_matched"] = metric_name

        # 2. Direction. Only meaningful when both values are present.
        direction = match_spec.get("direction")
        if direction and observed is not None and baseline is not None:
            if direction == "increasing" and float(observed) <= float(baseline):
                return None
            if direction == "decreasing" and float(observed) >= float(baseline):
                return None
            evidence["direction"] = direction

        # 3. Delta bounds.
        delta_min = match_spec.get("delta_pct_min")
        delta_max = match_spec.get("delta_pct_max")
        if (delta_min is not None or delta_max is not None):
            if delta_pct is None:
                # We can't confirm the bound without a delta. Skip rather than
                # match — false positives are worse than missing a noisy signal.
                return None
            if delta_min is not None and abs(float(delta_pct)) < float(delta_min):
                return None
            if delta_max is not None and abs(float(delta_pct)) > float(delta_max):
                return None
            evidence["delta_pct"] = delta_pct

        # 4. Resource-attribute conditions.
        for key, expected in (match_spec.get("resource_attributes") or {}).items():
            if not _attribute_matches(resource_attrs.get(key), expected):
                return None
            evidence.setdefault("resource_attributes", {})[key] = resource_attrs.get(key)

        # 5. Data-point-attribute conditions.
        for key, expected in (match_spec.get("attributes") or {}).items():
            if not _attribute_matches(attrs.get(key), expected):
                return None
            evidence.setdefault("attributes", {})[key] = attrs.get(key)

        return evidence

    # --- parameter rendering --------------------------------------------------

    def _render_parameters(self, rule: MetricActionRule, signal: dict[str, Any]) -> dict[str, Any]:
        """Interpolate ``{dotted.path}`` placeholders against the signal.

        Paths resolve in this order:

        1. ``{resource_attributes.X}`` — top-level ``resource_attributes`` dict
        2. ``{attributes.X}`` — ``metric_regression.attributes`` dict
        3. ``{X}`` without a dot — a top-level field on the signal (``service``,
           ``environment``, etc.)

        If a placeholder doesn't resolve, the parameter is left as the literal
        string. The decision engine then flags the missing attribute in its
        reasoning — better to ship an actionable proposal with ``namespace=""``
        plus a visible error than to silently drop the parameter.
        """
        template = rule.propose.get("parameters") or {}
        rendered: dict[str, Any] = {}
        for key, value in template.items():
            if isinstance(value, str) and "{" in value:
                rendered[key] = _render_placeholder(value, signal)
            else:
                rendered[key] = value

        # Numeric bound enforcement: clamp replicas_delta-style ints at render
        # time so a rule author can't accidentally ship a value that exceeds
        # their own stated bound.
        replicas_delta_max = rule.bounds.get("replicas_delta_max")
        if replicas_delta_max is not None and isinstance(rendered.get("replicas_delta"), (int, float)):
            rendered["replicas_delta"] = _clamp_signed(rendered["replicas_delta"], replicas_delta_max)

        return rendered


# --- loader ---------------------------------------------------------------------


@lru_cache(maxsize=8)
def load_metric_action_rules(path: str | None) -> MetricActionMatcher:
    """Load rules from ``path`` (defaults to the built-in starter policy).

    Returns a matcher with an empty rule list when the file is missing — this
    keeps test environments simple and makes the feature fully opt-in: no rule
    file, no behavior change. The LRU cache is scoped to the absolute path, so
    the same rules aren't reparsed across requests.
    """
    if path is None:
        default = _default_policy_path()
        path = str(default) if default.exists() else ""
    if not path or not Path(path).exists():
        return MetricActionMatcher(rules=[])
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    raw_rules = payload.get("rules") or []
    rules: list[MetricActionRule] = []
    for raw in raw_rules:
        rules.append(
            MetricActionRule(
                name=raw["name"],
                match=raw.get("match") or {},
                propose=raw.get("propose") or {},
                bounds=raw.get("bounds") or {},
                confidence=float(raw.get("confidence", 0.75)),
                risk_level=raw.get("risk_level", "medium"),
                rollback_plan=raw.get("rollback_plan", ""),
            )
        )
    return MetricActionMatcher(rules=rules)


def _default_policy_path() -> Path:
    return Path(__file__).resolve().parents[2] / "policies" / "metric-actions.policy.json"


# --- helpers --------------------------------------------------------------------


def _attribute_matches(actual: Any, expected: Any) -> bool:
    """Rule attribute comparison with a special wildcard.

    ``"*"`` means "the key must exist with any value". This is commonly what
    operators want — "only apply this rule when the signal identifies the
    cluster, regardless of which cluster" — without having to maintain a
    separate rule per cluster.
    """
    if expected == "*":
        return actual is not None
    return actual == expected


_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


def _render_placeholder(template: str, signal: dict[str, Any]) -> str:
    """Replace every ``{path}`` in ``template`` with the signal value at ``path``.

    Missing values render as empty strings so the rendered output is always a
    string. The decision stage validates required parameters downstream, so a
    missing attribute surfaces as a validation error rather than a silent skip.
    """
    def resolve(match: re.Match[str]) -> str:
        path = match.group(1).strip()
        value = _resolve_path(path, signal)
        return "" if value is None else str(value)

    return _PLACEHOLDER_RE.sub(resolve, template)


def _resolve_path(path: str, signal: dict[str, Any]) -> Any:
    """Dotted-path lookup against the signal.

    OTel attribute keys commonly contain dots (``k8s.deployment.name``), which
    collide with our path separator. We handle that by greedy-matching: at each
    step, we try the longest possible key first. This isn't perfect for every
    pathological case but is good enough for standard OTel semantic conventions.
    """
    if path in signal and not isinstance(signal[path], dict):
        return signal[path]

    segments = path.split(".")
    cursor: Any = signal
    index = 0
    while index < len(segments) and isinstance(cursor, dict):
        # Try progressively longer composite keys, since OTel attributes
        # like "k8s.deployment.name" are flat strings with dots.
        match_key = None
        match_length = 0
        for candidate_len in range(len(segments) - index, 0, -1):
            candidate = ".".join(segments[index : index + candidate_len])
            if candidate in cursor:
                match_key = candidate
                match_length = candidate_len
                break
        if match_key is None:
            return None
        cursor = cursor[match_key]
        index += match_length
    return cursor


def _clamp_signed(value: float, bound: float) -> float:
    """Clamp ``value`` to ``[-bound, +bound]`` preserving sign.

    Used for replica deltas where both positive and negative values are valid
    (scale up / scale down) and the bound is a magnitude cap.
    """
    if value > bound:
        return bound
    if value < -bound:
        return -bound
    return value


__all__ = [
    "MetricActionMatcher",
    "MetricActionRule",
    "RuleMatch",
    "load_metric_action_rules",
]
