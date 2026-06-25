#!/usr/bin/env python3
"""Evaluate shopping candidates against explicit criteria."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


TAOBAO_PLATFORMS = {"taobao", "tmall"}
OFFICIAL_STORE_TYPES = {"official", "flagship", "self_operated", "brand_direct"}
UNKNOWN = "unknown"
STORE_TYPE_TRUST_GRADES = {
    "official": "A",
    "flagship": "A",
    "self_operated": "A",
    "brand_direct": "A",
    "authorized": "B",
    "tmall_authorized": "B",
    "specialty": "B",
    "franchise": "B",
    "tmall_store": "B",
    "reseller": "C",
    "distributor": "C",
    "taobao_store": "C",
    "ordinary_store": "C",
    "suspicious": "D",
    "counterfeit_risk": "D",
}
TRUST_GRADE_SCORE = {"A": 3, "B": 2, "C": 1, "D": 0, UNKNOWN: -1}
HARD_CONSTRAINT_EVIDENCE_FIELDS = {
    "price_cny": {"price_cny", "price", "visible_price"},
    "power_w": {"power_w", "wattage", "rated_power"},
    "height_cm": {"height_cm", "height", "dimensions_text", "dimensions"},
    "color": {"color", "sku_color", "selected_sku"},
}
LANDSCAPE_FIELD_LIMITS = {
    "subtypes": 4,
    "price_bands": 5,
    "optional_attributes": 6,
    "pain_points": 6,
    "risk_signals": 4,
    "safe_signals": 4,
    "category_norms": 4,
    "decision_axes": 4,
}


@dataclass
class CheckResult:
    field: str
    status: str
    message: str


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def parse_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(float(value)):
            return None
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    multiplier = 1.0
    if "万" in text:
        multiplier = 10000.0
    elif "k" in text.lower():
        multiplier = 1000.0
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0)) * multiplier


def parse_color(value: Any) -> str:
    return "" if value is None else str(value).strip().lower()


def parse_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "是", "有", "支持"}:
        return True
    if text in {"false", "no", "n", "0", "否", "无", "不支持"}:
        return False
    return None


def get_path(obj: Dict[str, Any], path: Iterable[str]) -> Any:
    current: Any = obj
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def platform_is_taobao(candidate: Dict[str, Any]) -> bool:
    return str(candidate.get("platform") or "").lower() in TAOBAO_PLATFORMS


def taobao_url_has_market_context(url: Any) -> bool:
    text = str(url or "").lower()
    return any(marker in text for marker in ("spm=", "utparam=", "xxc=", "ns=", "mi_id=", "abbucket=", "from="))


def taobao_url_looks_simplified(url: Any) -> bool:
    text = str(url or "").lower()
    if "id=" not in text:
        return False
    if not any(host in text for host in ("detail.tmall.com/item", "item.taobao.com/item")):
        return False
    return not taobao_url_has_market_context(text)


def candidate_review_probe_url(candidate: Dict[str, Any]) -> Any:
    reviews = candidate.get("reviews") if isinstance(candidate.get("reviews"), dict) else {}
    return (
        candidate.get("review_probe_url")
        or reviews.get("review_probe_url")
        or candidate.get("source_url")
        or candidate.get("url")
    )


def candidate_explicit_review_probe_url(candidate: Dict[str, Any]) -> Any:
    reviews = candidate.get("reviews") if isinstance(candidate.get("reviews"), dict) else {}
    return candidate.get("review_probe_url") or reviews.get("review_probe_url")


def normalized_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    specs = candidate.setdefault("specs", {})
    for key in ("price_cny", "review_count", "bad_review_count", "bad_review_rate"):
        if key in candidate:
            parsed = parse_number(candidate.get(key))
            if parsed is not None:
                candidate[key] = parsed
    for key in ("power_w", "height_cm", "capacity_l"):
        if key in specs:
            parsed = parse_number(specs.get(key))
            if parsed is not None:
                specs[key] = parsed
    if candidate.get("review_count") and candidate.get("bad_review_count") and not candidate.get("bad_review_rate"):
        candidate["bad_review_rate"] = candidate["bad_review_count"] / candidate["review_count"]
    return candidate


def check_platform(criteria: Dict[str, Any], candidate: Dict[str, Any]) -> CheckResult:
    allowed = set(criteria.get("allowed_platforms") or [])
    platform = candidate.get("platform")
    if not allowed:
        return CheckResult("platform", "pass", "no platform restriction")
    if not platform:
        return CheckResult("platform", "needs_review", "platform is missing")
    if platform in allowed:
        return CheckResult("platform", "pass", f"{platform} is allowed")
    return CheckResult("platform", "fail", f"{platform} is not in allowed platforms")


def check_store(criteria: Dict[str, Any], candidate: Dict[str, Any]) -> CheckResult:
    required = set(criteria.get("store_requirements") or [])
    store_type = candidate.get("store_type") or UNKNOWN
    if not required:
        return CheckResult("store_type", "pass", "no store restriction")
    if store_type in required or store_type in OFFICIAL_STORE_TYPES.intersection(required):
        return CheckResult("store_type", "pass", f"store type is {store_type}")
    if store_type == UNKNOWN:
        return CheckResult("store_type", "needs_review", "store type is unknown")
    return CheckResult("store_type", "fail", f"store type {store_type} is not acceptable")


def check_brand(criteria: Dict[str, Any], candidate: Dict[str, Any]) -> CheckResult:
    policy = criteria.get("brand_policy") or {}
    brands = set(policy.get("brands") or [])
    brand = candidate.get("brand")
    if not brands:
        return CheckResult("brand", "pass", "no brand restriction")
    if not brand:
        return CheckResult("brand", "needs_review", "brand is missing")
    if brand in brands:
        return CheckResult("brand", "pass", f"brand {brand} is allowed")
    title = str(candidate.get("title") or "")
    if any(name and name in title for name in brands):
        return CheckResult("brand", "pass", "allowed brand appears in title")
    return CheckResult("brand", "fail", f"brand {brand} is not in allow list")


def check_numeric(
    criteria: Dict[str, Any],
    candidate: Dict[str, Any],
    criteria_key: str,
    candidate_path: Tuple[str, ...],
) -> Optional[CheckResult]:
    rule = (criteria.get("hard_constraints") or {}).get(criteria_key)
    if not rule:
        return None
    value = parse_number(get_path(candidate, candidate_path))
    if value is None:
        return CheckResult(criteria_key, "needs_review", f"{criteria_key} is missing")
    if "min" in rule and value < float(rule["min"]):
        return CheckResult(criteria_key, "fail", f"{value:g} is below minimum {rule['min']}")
    if "max" in rule and value > float(rule["max"]):
        return CheckResult(criteria_key, "fail", f"{value:g} is above maximum {rule['max']}")
    return CheckResult(criteria_key, "pass", f"{value:g} satisfies constraint")


def check_color(criteria: Dict[str, Any], candidate: Dict[str, Any]) -> Optional[CheckResult]:
    rule = (criteria.get("hard_constraints") or {}).get("color")
    if not rule:
        return None
    color = parse_color(get_path(candidate, ("specs", "color")))
    if not color:
        return CheckResult("color", "needs_review", "color is missing")
    disallowed = [parse_color(item) for item in rule.get("disallow", [])]
    if any(item and item in color for item in disallowed):
        return CheckResult("color", "fail", f"color {color} is disallowed")
    return CheckResult("color", "pass", f"color {color} is acceptable")


def normalize_trust_grade(value: Any) -> str:
    grade = str(value or "").strip().upper()
    return grade if grade in TRUST_GRADE_SCORE else UNKNOWN


def infer_store_trust_grade(candidate: Dict[str, Any]) -> str:
    store_trust = candidate.get("store_trust")
    if isinstance(store_trust, dict):
        grade = normalize_trust_grade(store_trust.get("grade"))
        if grade != UNKNOWN:
            return grade
    grade = normalize_trust_grade(candidate.get("store_trust_grade"))
    if grade != UNKNOWN:
        return grade
    store_type = str(candidate.get("store_type") or "").strip().lower()
    if store_type in STORE_TYPE_TRUST_GRADES:
        return STORE_TYPE_TRUST_GRADES[store_type]
    if platform_is_taobao(candidate):
        store_name = str(candidate.get("store_name") or "")
        if "官方旗舰店" in store_name or "品牌直营" in store_name:
            return "A"
        if "专卖店" in store_name or "专营店" in store_name:
            return "B"
    return UNKNOWN


def check_store_trust(criteria: Dict[str, Any], candidate: Dict[str, Any]) -> List[CheckResult]:
    policy = criteria.get("taobao_policy") or {}
    top_level_minimum = normalize_trust_grade(criteria.get("minimum_store_trust_grade"))
    taobao_minimum = normalize_trust_grade(policy.get("minimum_store_trust_grade")) if platform_is_taobao(candidate) else UNKNOWN
    minimum = top_level_minimum if top_level_minimum != UNKNOWN else taobao_minimum
    grade = infer_store_trust_grade(candidate)
    if not platform_is_taobao(candidate) and top_level_minimum == UNKNOWN:
        return []
    if grade == UNKNOWN:
        return [CheckResult("store_trust", "needs_review", "store trust grade is missing")]
    if minimum != UNKNOWN and TRUST_GRADE_SCORE[grade] < TRUST_GRADE_SCORE[minimum]:
        return [
            CheckResult(
                "store_trust",
                "fail",
                f"store trust grade {grade} is below required {minimum}",
            )
        ]
    if grade == "D":
        return [CheckResult("store_trust", "fail", "store trust grade D is too risky")]
    return [CheckResult("store_trust", "pass", f"store trust grade is {grade}")]


def check_selected_sku(criteria: Dict[str, Any], candidate: Dict[str, Any]) -> List[CheckResult]:
    policy = criteria.get("taobao_policy") or {}
    required = bool(policy.get("require_selected_sku_evidence", True))
    if not platform_is_taobao(candidate) or not required:
        return []
    sku = candidate.get("selected_sku")
    if not isinstance(sku, dict) or not sku:
        return [CheckResult("selected_sku", "needs_review", "current selected SKU is missing")]
    if parse_bool(sku.get("current")) is False:
        return [CheckResult("selected_sku", "fail", "captured SKU is not the current buyable selection")]
    verified = parse_bool(sku.get("verified"))
    label = sku.get("label") or sku.get("model") or sku.get("color")
    if verified is True and label:
        return [CheckResult("selected_sku", "pass", f"current SKU verified: {label}")]
    return [CheckResult("selected_sku", "needs_review", "current selected SKU is not fully verified")]


def check_purchase_evidence(candidate: Dict[str, Any]) -> List[CheckResult]:
    results: List[CheckResult] = []
    if candidate.get("url"):
        results.append(CheckResult("url", "pass", "purchase or evidence URL is present"))
    else:
        results.append(CheckResult("url", "needs_review", "purchase or evidence URL is missing"))

    verified = candidate.get("purchase_platform_verified")
    if verified is True:
        results.append(CheckResult("purchase_platform_verified", "pass", "purchase channel was verified"))
    elif verified is False:
        results.append(
            CheckResult(
                "purchase_platform_verified",
                "needs_review",
                "purchase channel was not verified",
            )
        )
    else:
        results.append(
            CheckResult(
                "purchase_platform_verified",
                "needs_review",
                "purchase channel verification is missing",
            )
        )
    if platform_is_taobao(candidate):
        source_url = candidate.get("source_url")
        review_probe_url = candidate_explicit_review_probe_url(candidate)
        url = candidate.get("url")
        if review_probe_url or source_url:
            results.append(
                CheckResult(
                    "review_probe_url",
                    "pass",
                    "original source/review probe URL is retained for Taobao/Tmall review checks",
                )
            )
        elif taobao_url_has_market_context(url):
            results.append(
                CheckResult(
                    "review_probe_url",
                    "pass",
                    "purchase URL appears to retain Taobao/Tmall marketplace context for review probing",
                )
            )
        elif taobao_url_looks_simplified(url):
            results.append(
                CheckResult(
                    "review_probe_url",
                    "needs_review",
                    "only a simplified Taobao/Tmall item URL is captured; preserve or retry the original search-result URL because simplified pages can hide reviews/Q&A",
                )
            )
        else:
            results.append(
                CheckResult(
                    "review_probe_url",
                    "needs_review",
                    "Taobao/Tmall source or review probe URL is missing; preserve the original marketplace URL when available",
                )
            )
    return results


def check_after_sales(criteria: Dict[str, Any], candidate: Dict[str, Any]) -> List[CheckResult]:
    policy = criteria.get("taobao_policy") or {}
    top_level_required = criteria.get("require_after_sales_evidence")
    if top_level_required is None:
        required = platform_is_taobao(candidate) and bool(policy.get("require_after_sales_evidence", True))
    else:
        required = bool(top_level_required)
    constraints = criteria.get("hard_constraints") or {}
    after_sales = candidate.get("after_sales")
    if not required and "installation_included" not in constraints:
        return []
    if not isinstance(after_sales, dict) or not after_sales:
        return [CheckResult("after_sales", "needs_review", "after-sales terms are missing")]

    results: List[CheckResult] = []
    installation_rule = constraints.get("installation_included")
    if installation_rule is not None:
        installation = parse_bool(after_sales.get("installation_included"))
        if installation is None:
            results.append(CheckResult("after_sales.installation_included", "needs_review", "installation inclusion is missing"))
        elif bool(installation_rule) and not installation:
            results.append(CheckResult("after_sales.installation_included", "fail", "installation is required but not included"))
        else:
            results.append(CheckResult("after_sales.installation_included", "pass", "installation requirement is satisfied"))

    visible_terms = [
        parse_bool(after_sales.get("seven_day_no_reason")),
        parse_bool(after_sales.get("return_freight_support")),
        parse_bool(after_sales.get("invoice_support")),
        bool(after_sales.get("warranty_text")),
        bool(after_sales.get("price_protection")),
    ]
    if any(item is True for item in visible_terms):
        results.append(CheckResult("after_sales", "pass", "visible after-sales terms are captured"))
    else:
        results.append(CheckResult("after_sales", "needs_review", "no concrete after-sales protection was captured"))
    return results


def check_review_risk(criteria: Dict[str, Any], candidate: Dict[str, Any]) -> List[CheckResult]:
    policy = criteria.get("taobao_policy") or {}
    top_level_required = criteria.get("require_review_probe")
    if platform_is_taobao(candidate):
        required = True
        if top_level_required is False and criteria.get("allow_skip_taobao_review_probe") is True:
            required = False
    elif top_level_required is None:
        required = bool(policy.get("require_review_probe", False))
    else:
        required = bool(top_level_required)
    reviews = candidate.get("reviews")
    if not required:
        return []
    if not isinstance(reviews, dict) or not reviews:
        message = "negative/follow-up/Q&A review probe is missing"
        if taobao_url_looks_simplified(candidate.get("url")) and (
            candidate.get("source_url") or candidate_explicit_review_probe_url(candidate)
        ):
            message += "; retry with source_url/review_probe_url before marking reviews unavailable"
        elif taobao_url_looks_simplified(candidate.get("url")):
            message += "; only a simplified Taobao/Tmall item URL is available, so the original source URL must be preserved and retried"
        return [CheckResult("reviews", "needs_review", message)]

    severe = reviews.get("severe_negative_themes") or []
    if severe:
        return [CheckResult("reviews.severe_negative_themes", "fail", f"severe negative themes found: {', '.join(map(str, severe[:3]))}")]

    results: List[CheckResult] = []
    missing = []
    for key, label in (
        ("negative_review_checked", "negative reviews"),
        ("follow_up_review_checked", "follow-up reviews"),
        ("qna_checked", "Q&A"),
    ):
        if parse_bool(reviews.get(key)) is not True:
            missing.append(label)
    if missing:
        message = "missing review checks: " + ", ".join(missing)
        if taobao_url_looks_simplified(candidate.get("url")) and (
            candidate.get("source_url") or candidate_explicit_review_probe_url(candidate)
        ):
            message += "; retry missing areas with source_url/review_probe_url"
        results.append(CheckResult("reviews", "needs_review", message))
    else:
        results.append(CheckResult("reviews", "pass", "negative/follow-up/Q&A checks completed"))

    medium = reviews.get("medium_negative_themes") or []
    if medium:
        results.append(CheckResult("reviews.medium_negative_themes", "needs_review", f"medium negative themes need judgment: {', '.join(map(str, medium[:3]))}"))
    return results


def evidence_fields(candidate: Dict[str, Any]) -> set[str]:
    fields: set[str] = set()
    for item in candidate.get("evidence") or []:
        if isinstance(item, dict) and item.get("field"):
            fields.add(str(item["field"]).strip())
    return fields


def check_hard_constraint_evidence(
    criteria: Dict[str, Any],
    candidate: Dict[str, Any],
    checks: List[CheckResult],
) -> List[CheckResult]:
    hard_constraints = criteria.get("hard_constraints") or {}
    if not hard_constraints:
        return []
    known_fields = evidence_fields(candidate)
    check_by_field = {check.field: check for check in checks}
    results: List[CheckResult] = []
    for criteria_key in hard_constraints:
        if criteria_key not in HARD_CONSTRAINT_EVIDENCE_FIELDS:
            continue
        field_check = check_by_field.get(criteria_key)
        if not field_check or field_check.status != "pass":
            continue
        accepted = HARD_CONSTRAINT_EVIDENCE_FIELDS[criteria_key]
        if accepted.intersection(known_fields):
            results.append(CheckResult(f"evidence.{criteria_key}", "pass", "supporting evidence is captured"))
        else:
            results.append(
                CheckResult(
                    f"evidence.{criteria_key}",
                    "needs_review",
                    f"missing supporting evidence for {criteria_key}",
                )
            )
    return results


def evaluate_candidate(criteria: Dict[str, Any], raw_candidate: Dict[str, Any]) -> Dict[str, Any]:
    candidate = normalized_candidate(dict(raw_candidate))
    checks: List[CheckResult] = [
        check_platform(criteria, candidate),
        check_store(criteria, candidate),
        check_brand(criteria, candidate),
    ]
    for item in (
        check_numeric(criteria, candidate, "price_cny", ("price_cny",)),
        check_numeric(criteria, candidate, "power_w", ("specs", "power_w")),
        check_numeric(criteria, candidate, "height_cm", ("specs", "height_cm")),
        check_color(criteria, candidate),
    ):
        if item:
            checks.append(item)
    checks.extend(check_store_trust(criteria, candidate))
    checks.extend(check_selected_sku(criteria, candidate))
    checks.extend(check_purchase_evidence(candidate))
    checks.extend(check_after_sales(criteria, candidate))
    checks.extend(check_review_risk(criteria, candidate))
    checks.extend(check_hard_constraint_evidence(criteria, candidate, checks))

    statuses = {check.status for check in checks}
    if "fail" in statuses:
        status = "fail"
    elif "needs_review" in statuses:
        status = "needs_review"
    else:
        status = "pass"

    return {
        "id": candidate.get("id") or candidate.get("url") or candidate.get("title"),
        "status": status,
        "score": score_candidate(candidate, checks, status),
        "candidate": candidate,
        "checks": [check.__dict__ for check in checks],
    }


def score_candidate(candidate: Dict[str, Any], checks: List[CheckResult], status: str) -> float:
    score = 0.0
    score += {"pass": 100.0, "needs_review": 55.0, "fail": 0.0}[status]
    score += sum(2.0 for check in checks if check.status == "pass")
    score -= sum(8.0 for check in checks if check.status == "needs_review")
    if (candidate.get("store_type") or "") in OFFICIAL_STORE_TYPES:
        score += 10.0
    grade = infer_store_trust_grade(candidate)
    score += {"A": 12.0, "B": 6.0, "C": -3.0, "D": -20.0, UNKNOWN: -6.0}[grade]
    after_sales = candidate.get("after_sales") if isinstance(candidate.get("after_sales"), dict) else {}
    if after_sales:
        score += sum(
            2.0
            for key in ("seven_day_no_reason", "return_freight_support", "invoice_support", "price_protection")
            if parse_bool(after_sales.get(key)) is True
        )
        if after_sales.get("warranty_text"):
            score += 2.0
    reviews = candidate.get("reviews") if isinstance(candidate.get("reviews"), dict) else {}
    if reviews:
        if reviews.get("severe_negative_themes"):
            score -= 35.0
        if reviews.get("medium_negative_themes"):
            score -= min(12.0, len(reviews.get("medium_negative_themes") or []) * 4.0)
        if all(parse_bool(reviews.get(key)) is True for key in ("negative_review_checked", "follow_up_review_checked", "qna_checked")):
            score += 6.0
    review_count = parse_number(candidate.get("review_count") or candidate.get("sales_text"))
    if review_count:
        score += min(15.0, math.log10(max(review_count, 1)) * 3)
    bad_rate = parse_number(candidate.get("bad_review_rate"))
    if bad_rate is not None:
        score += max(-15.0, 10.0 - bad_rate * 1000.0)
    price = parse_number(candidate.get("price_cny"))
    if price is not None:
        score += max(0.0, 8.0 - price / 100.0)
    evidence = candidate.get("evidence") or []
    score += min(8.0, len(evidence) * 1.5)
    return round(score, 2)


def listify(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    return [str(value)]


def bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def report_candidate_limit(criteria: Dict[str, Any]) -> int:
    return bounded_int(criteria.get("report_candidate_limit"), 3, 1, 5)


def compact_items(value: Any, limit: int = 3) -> List[str]:
    return listify(value)[:limit]


def landscape_item_limit(criteria: Dict[str, Any], key: str) -> int:
    overrides = criteria.get("category_landscape_limits") or {}
    if isinstance(overrides, dict) and key in overrides:
        return bounded_int(overrides.get(key), LANDSCAPE_FIELD_LIMITS.get(key, 4), 1, 8)
    return LANDSCAPE_FIELD_LIMITS.get(key, 4)


def compact_checks(checks: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    priority = {"fail": 0, "needs_review": 1, "pass": 2}
    ordered = sorted(
        checks,
        key=lambda check: priority.get(str(check.get("status", "needs_review")), 1),
    )
    return ordered[:limit]


def render_markdown_category_landscape(criteria: Dict[str, Any]) -> List[str]:
    landscape = criteria.get("category_landscape") or {}
    if not isinstance(landscape, dict):
        landscape = {}
    if not landscape:
        return []

    label_map = [
        ("subtypes", "Main subtypes"),
        ("price_bands", "Price bands"),
        ("optional_attributes", "Optional attributes"),
        ("pain_points", "Common pain points"),
        ("risk_signals", "Risk signals"),
        ("safe_signals", "Safe signals"),
        ("category_norms", "Category norms"),
        ("decision_axes", "Decision axes"),
    ]
    lines = ["## Category Landscape", ""]
    for key, label in label_map:
        values = compact_items(landscape.get(key), landscape_item_limit(criteria, key))
        if not values:
            continue
        lines.append(f"### {label}")
        for item in values:
            lines.append(f"- {item}")
        lines.append("")
    return lines


def render_markdown_iteration_notes(criteria: Dict[str, Any]) -> List[str]:
    version = str(criteria.get("report_version") or "").strip()
    status = str(criteria.get("report_status") or "").strip()
    changes = listify(criteria.get("changes_from_previous"))
    if not any([version, status, changes]):
        return []

    lines = ["## Iteration Status", ""]
    if version:
        lines.append(f"- Version: `{version}`")
    if status:
        lines.append(f"- Status: `{status}`")
    if changes:
        lines.append("- Changes from previous version:")
        for item in changes[:3]:
            lines.append(f"  - {item}")
    lines.append("")
    return lines


def render_markdown(criteria: Dict[str, Any], evaluated: List[Dict[str, Any]]) -> str:
    lines = [
        f"# Ghost Buyer Report: {criteria.get('task_name', 'untitled')}",
        "",
        f"Category: {criteria.get('category', 'unknown')}",
        "",
    ]
    lines.extend(render_markdown_iteration_notes(criteria))
    lines.extend(
        [
        "## Recommendation",
        "",
        str(criteria.get("recommendation") or criteria.get("summary") or "No recommendation provided."),
        "",
        ]
    )
    lines.extend(render_markdown_category_landscape(criteria))
    blockers = criteria.get("blockers") or []
    if blockers:
        lines.extend(["## Source Blockers", ""])
        for blocker in blockers:
            lines.append(f"- {blocker}")
        lines.append("")
    lines.extend(
        [
        "## Ranked Candidates",
        "",
        ]
    )
    limit = report_candidate_limit(criteria)
    for index, item in enumerate(evaluated[:limit], start=1):
        candidate = item["candidate"]
        image = candidate.get("image_url") or candidate.get("screenshot_path")
        source_url = candidate.get("source_url")
        review_probe_url = candidate_explicit_review_probe_url(candidate)
        link_lines = [f"- Purchase link: {candidate.get('url', 'unknown')}"]
        if source_url and source_url != candidate.get("url"):
            link_lines.append(f"- Source link: {source_url}")
        if review_probe_url and review_probe_url not in {candidate.get("url"), source_url}:
            link_lines.append(f"- Review probe link: {review_probe_url}")
        lines.extend(
            [
                f"### {index}. {candidate.get('title', item['id'])}",
                "",
                *link_lines,
                "",
                f"![Product image]({image})" if image else "_Product image not captured._",
                "",
                f"- Status: `{item['status']}`",
                f"- Score: `{item['score']}`",
                f"- Platform/store: `{candidate.get('platform', 'unknown')}` / `{candidate.get('store_name', 'unknown')}` (`{candidate.get('store_type', 'unknown')}`)",
                f"- Store trust: `{infer_store_trust_grade(candidate)}`",
                f"- Brand/model: `{candidate.get('brand', 'unknown')}` / `{candidate.get('model', 'unknown')}`",
                f"- Selected SKU: `{(candidate.get('selected_sku') or {}).get('label', 'unknown') if isinstance(candidate.get('selected_sku'), dict) else 'unknown'}`",
                f"- Price: `{candidate.get('price_cny', 'unknown')}` CNY",
                "",
                "Checks:",
            ]
        )
        for check in compact_checks(item["checks"]):
            lines.append(f"- `{check['status']}` {check['field']}: {check['message']}")
        lines.append("")
    if len(evaluated) > limit:
        lines.extend(
            [
                "## Omitted From Compact Report",
                "",
                f"{len(evaluated) - limit} lower-ranked candidates were omitted to keep the report concise.",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_html(criteria: Dict[str, Any], evaluated: List[Dict[str, Any]]) -> str:
    task_name = html.escape(str(criteria.get("task_name", "Ghost Buyer Report")))
    category = html.escape(str(criteria.get("category", "unknown")))
    generated_at = html.escape(str(criteria.get("generated_at", "")))
    constraints = criteria.get("hard_constraints") or {}

    def esc(value: Any, default: str = "unknown") -> str:
        if value is None or value == "":
            return default
        return html.escape(str(value))

    def status_class(status: str) -> str:
        return status if status in {"pass", "needs_review", "fail"} else "needs_review"

    def status_text(status: str) -> str:
        return {"pass": "通过", "needs_review": "需复核", "fail": "淘汰"}.get(status, status)

    def external_link_attrs() -> str:
        return ' target="_blank" rel="noopener noreferrer"'

    def render_checks(checks: List[Dict[str, Any]]) -> str:
        items = []
        for check in compact_checks(checks):
            status = str(check.get("status", "needs_review"))
            items.append(
                "<li>"
                f"<span class=\"check {status_class(status)}\">{html.escape(status_text(status))}</span>"
                f"<strong>{esc(check.get('field'))}</strong>"
                f"<span>{esc(check.get('message'))}</span>"
                "</li>"
            )
        return "\n".join(items)

    def render_evidence(evidence: List[Dict[str, Any]]) -> str:
        if not evidence:
            return "<p class=\"muted\">No structured evidence captured.</p>"
        rows = []
        for item in evidence[:3]:
            source = item.get("source_url")
            source_html = (
                f"<a href=\"{esc(source)}\"{external_link_attrs()}>source</a>" if source else "<span class=\"muted\">local</span>"
            )
            rows.append(
                "<tr>"
                f"<td>{esc(item.get('field'))}</td>"
                f"<td>{esc(item.get('value'))}</td>"
                f"<td>{source_html}</td>"
                f"<td>{esc(item.get('confidence'))}</td>"
                "</tr>"
            )
        return (
            "<table class=\"evidence\"><thead><tr><th>字段</th><th>证据</th><th>来源</th><th>置信度</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    def render_identity_links(candidate: Dict[str, Any], link_html: str) -> str:
        links = [link_html]
        seen = {str(candidate.get("url") or "")}
        for label, value in (
            ("来源链接", candidate.get("source_url")),
            ("评价探针链接", candidate_explicit_review_probe_url(candidate)),
        ):
            text = str(value or "")
            if not text or text in seen:
                continue
            seen.add(text)
            links.append(f"<a class=\"secondary-link\" href=\"{esc(text)}\"{external_link_attrs()}>{label}</a>")
        return "".join(links)

    def render_landscape_list(title: str, values: Any, key: str) -> str:
        items = compact_items(values, landscape_item_limit(criteria, key))
        if not items:
            return ""
        return f"<h3>{esc(title)}</h3><ul>" + "".join(f"<li>{esc(item)}</li>" for item in items) + "</ul>"

    def render_category_landscape() -> str:
        landscape = criteria.get("category_landscape") or {}
        if not isinstance(landscape, dict):
            landscape = {}
        if not landscape:
            return ""
        parts = [
            render_landscape_list("主要分型", landscape.get("subtypes"), "subtypes"),
            render_landscape_list("价位带", landscape.get("price_bands"), "price_bands"),
            render_landscape_list("可选属性", landscape.get("optional_attributes"), "optional_attributes"),
            render_landscape_list("常见痛点", landscape.get("pain_points"), "pain_points"),
            render_landscape_list("风险信号", landscape.get("risk_signals"), "risk_signals"),
            render_landscape_list("安全信号", landscape.get("safe_signals"), "safe_signals"),
            render_landscape_list("品类常态", landscape.get("category_norms"), "category_norms"),
            render_landscape_list("决策取舍", landscape.get("decision_axes"), "decision_axes"),
        ]
        return "<section class=\"panel landscape\"><h2>品类摸排</h2>" + "".join(parts) + "</section>"

    cards = []
    limit = report_candidate_limit(criteria)
    for index, item in enumerate(evaluated[:limit], start=1):
        candidate = item["candidate"]
        specs = candidate.get("specs") or {}
        status = str(item.get("status", "needs_review"))
        image = candidate.get("image_url") or candidate.get("screenshot_path")
        url = candidate.get("url")
        platform_label = "淘宝/天猫链接" if str(candidate.get("platform") or "").lower() in TAOBAO_PLATFORMS else "购买链接"
        link_html = (
            f"<a class=\"purchase-link\" href=\"{esc(url)}\"{external_link_attrs()}>打开{html.escape(platform_label)}</a>"
            if url
            else "<span class=\"purchase-link muted\">购买链接未捕获</span>"
        )
        image_html = (
            f"<img src=\"{esc(image)}\" alt=\"{esc(candidate.get('title'), 'product image')}\" loading=\"lazy\">"
            if image
            else "<div class=\"image-placeholder\">No image</div>"
        )
        purchase_verified = candidate.get("purchase_platform_verified")
        if purchase_verified is True:
            purchase_text = "淘宝/京东购买平台已验证"
        elif purchase_verified is False:
            purchase_text = "淘宝/京东购买平台未验证"
        else:
            purchase_text = "购买平台状态未知"

        cards.append(
            f"""
            <article class="card {status_class(status)}">
              <div class="media">{image_html}</div>
              <div class="content">
                <div class="rank">#{index} <span class="badge {status_class(status)}">{html.escape(status_text(status))}</span></div>
                <h2>{esc(candidate.get('title'), item.get('id', 'candidate'))}</h2>
                <div class="identity-row">{render_identity_links(candidate, link_html)}</div>
                <div class="meta">
                  <span>评分 {esc(item.get('score'))}</span>
                  <span>{esc(candidate.get('brand'))} / {esc(candidate.get('model'))}</span>
                  <span>{esc(candidate.get('platform'))} · {esc(candidate.get('store_type'))}</span>
                  <span>店铺等级 {esc(infer_store_trust_grade(candidate))}</span>
                </div>
                <div class="metrics">
                  <div><b>¥{esc(candidate.get('price_cny'))}</b><span>价格</span></div>
                  <div><b>{esc(specs.get('power_w'))}W</b><span>功率</span></div>
                  <div><b>{esc(specs.get('height_cm'))}cm</b><span>高度</span></div>
                  <div><b>{esc(candidate.get('review_count'))}</b><span>评价数</span></div>
                </div>
                <p class="note">{html.escape(purchase_text)}。{esc(candidate.get('purchase_note'), '')}</p>
                <ul class="checks">{render_checks(item.get('checks') or [])}</ul>
                {render_evidence(candidate.get('evidence') or [])}
              </div>
            </article>
            """
        )

    constraint_rows = []
    for key, value in constraints.items():
        constraint_rows.append(f"<tr><td>{esc(key)}</td><td>{esc(value)}</td></tr>")

    blockers = criteria.get("blockers") or []
    blocker_html = ""
    if blockers:
        blocker_html = "<h2>渠道阻塞</h2><ul>" + "".join(f"<li>{esc(item)}</li>" for item in blockers) + "</ul>"
    omitted_html = ""
    if len(evaluated) > limit:
        omitted_html = (
            f"<p class=\"muted\">为保持报告简洁，已省略 {len(evaluated) - limit} 个低排名候选；"
            "完整候选可在评估 JSON 或下一轮继续研究中展开。</p>"
        )

    def render_iteration_notes() -> str:
        version = str(criteria.get("report_version") or "").strip()
        status = str(criteria.get("report_status") or "").strip()
        changes = listify(criteria.get("changes_from_previous"))
        if not any([version, status, changes]):
            return ""
        rows = []
        if version:
            rows.append(f"<tr><td>版本</td><td>{esc(version)}</td></tr>")
        if status:
            rows.append(f"<tr><td>状态</td><td>{esc(status)}</td></tr>")
        table_html = f"<table><tbody>{''.join(rows)}</tbody></table>" if rows else ""
        change_html = ""
        if changes:
            change_html = "<h2>本版变化</h2><ul>" + "".join(f"<li>{esc(item)}</li>" for item in changes[:3]) + "</ul>"
        return table_html + change_html

    landscape_html = render_category_landscape()
    iteration_html = render_iteration_notes()

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{task_name}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17211b;
      --muted: #5d6962;
      --line: #d9ded7;
      --paper: #fbfbf8;
      --panel: #ffffff;
      --green: #147d4d;
      --amber: #9a6100;
      --red: #b32c2c;
      --blue: #255b8e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--paper);
      color: var(--ink);
      line-height: 1.55;
    }}
    header {{
      padding: 40px min(6vw, 64px) 24px;
      border-bottom: 1px solid var(--line);
      background: #f3f6f1;
    }}
    h1 {{ margin: 0 0 10px; font-size: 34px; letter-spacing: 0; }}
    h2 {{ margin: 8px 0 8px; font-size: 22px; letter-spacing: 0; }}
    main {{ padding: 24px min(6vw, 64px) 56px; }}
    .summary {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(300px, .8fr);
      gap: 18px;
      margin-bottom: 24px;
    }}
    .panel, .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .panel {{ padding: 18px; }}
    .panel h2 {{ font-size: 18px; margin-top: 0; }}
    .panel h3 {{ margin: 14px 0 6px; font-size: 15px; }}
    .muted {{ color: var(--muted); }}
    .landscape {{ margin: 0 0 24px; }}
    .landscape ul {{ margin: 6px 0 0; padding-left: 20px; }}
    .landscape li {{ margin: 3px 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    td, th {{ border-top: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }}
    .card {{
      display: grid;
      grid-template-columns: minmax(280px, 36%) minmax(0, 1fr);
      overflow: hidden;
      margin: 18px 0;
    }}
    .media {{ background: #eef1ec; min-height: 280px; display: flex; align-items: center; justify-content: center; }}
    .media img {{ width: 100%; height: 100%; max-height: 420px; object-fit: contain; display: block; }}
    .image-placeholder {{ color: var(--muted); }}
    .content {{ padding: 20px; }}
    .rank {{ font-weight: 700; color: var(--muted); }}
    .badge, .check {{
      display: inline-block;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 700;
      margin-right: 8px;
    }}
    .pass {{ color: var(--green); background: #e6f4ed; }}
    .needs_review {{ color: var(--amber); background: #fff2d7; }}
    .fail {{ color: var(--red); background: #f9e3e3; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 8px 16px; color: var(--muted); font-size: 14px; margin-bottom: 14px; }}
    .identity-row {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 8px 0 12px; }}
    .purchase-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--blue);
      border-radius: 8px;
      padding: 7px 12px;
      font-weight: 700;
      text-decoration: none;
      background: #eef5fb;
    }}
    .secondary-link {{
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 7px 10px;
      text-decoration: none;
      background: #ffffff;
      font-size: 14px;
    }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 14px 0; }}
    .metrics div {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px; }}
    .metrics b {{ display: block; font-size: 20px; }}
    .metrics span {{ color: var(--muted); font-size: 13px; }}
    .note {{ color: var(--blue); }}
    .checks {{ list-style: none; padding: 0; margin: 14px 0; }}
    .checks li {{ display: grid; grid-template-columns: 72px 120px minmax(0, 1fr); gap: 8px; padding: 7px 0; border-top: 1px solid var(--line); }}
    .evidence {{ margin-top: 12px; }}
    a {{ color: var(--blue); }}
    @media (max-width: 820px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      h1 {{ font-size: 27px; }}
      .summary, .card {{ grid-template-columns: 1fr; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .checks li {{ grid-template-columns: 72px 1fr; }}
      .checks li span:last-child {{ grid-column: 1 / -1; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{task_name}</h1>
    <p class="muted">Category: {category}{' · Generated: ' + generated_at if generated_at else ''}</p>
  </header>
  <main>
    <section class="summary">
      <div class="panel">
        <h2>结论摘要</h2>
        <p>{esc(criteria.get('summary'), '本报告基于已抓取证据排序。缺失的硬约束不会被当成通过。')}</p>
        <h2>最终建议</h2>
        <p>{esc(criteria.get('recommendation'), 'No recommendation provided.')}</p>
        {iteration_html}
        {blocker_html}
      </div>
      <div class="panel">
        <h2>硬约束</h2>
        <table><tbody>{''.join(constraint_rows)}</tbody></table>
      </div>
    </section>
    {landscape_html}
    {''.join(cards)}
    {omitted_html}
  </main>
</body>
</html>
"""


def command_template(args: argparse.Namespace) -> int:
    template = [
        {
            "id": "platform-product-id",
            "title": "",
            "brand": "",
            "model": "",
            "platform": "jd",
            "store_name": "",
            "store_type": "unknown",
            "url": "",
            "canonical_url": "",
            "source_url": "",
            "review_probe_url": "",
            "image_url": "",
            "screenshot_path": "",
            "source_platform": "",
            "purchase_platform_verified": None,
            "purchase_note": "",
            "selected_sku": {
                "label": "",
                "model": "",
                "color": "",
                "price_cny": None,
                "current": True,
                "verified": False
            },
            "store_trust": {
                "grade": "unknown",
                "signals": [],
                "rationale": ""
            },
            "price_cny": None,
            "sales_text": "",
            "review_count": None,
            "bad_review_count": None,
            "bad_review_rate": None,
            "after_sales": {
                "seven_day_no_reason": None,
                "return_freight_support": None,
                "warranty_text": "",
                "invoice_support": None,
                "price_protection": None,
                "installation_included": None,
                "notes": ""
            },
            "reviews": {
                "negative_review_checked": False,
                "follow_up_review_checked": False,
                "qna_checked": False,
                "severe_negative_themes": [],
                "medium_negative_themes": [],
                "mild_negative_themes": [],
                "summary": ""
            },
            "specs": {
                "power_w": None,
                "height_cm": None,
                "color": "",
                "capacity_l": None,
                "dimensions_text": ""
            },
            "evidence": []
        }
    ]
    write_json(Path(args.out), template)
    return 0


def command_evaluate(args: argparse.Namespace) -> int:
    criteria = load_json(Path(args.criteria))
    candidates = load_json(Path(args.candidates))
    if not isinstance(candidates, list):
        raise SystemExit("candidates JSON must be a list")
    evaluated = [evaluate_candidate(criteria, candidate) for candidate in candidates]
    evaluated.sort(key=lambda item: item["score"], reverse=True)
    result = {"criteria": criteria, "results": evaluated}
    if args.json_out:
        write_json(Path(args.json_out), result)
    if args.markdown_out:
        Path(args.markdown_out).write_text(render_markdown(criteria, evaluated), encoding="utf-8")
    if args.html_out:
        Path(args.html_out).write_text(render_html(criteria, evaluated), encoding="utf-8")
    if not args.json_out and not args.markdown_out and not args.html_out:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    template = subparsers.add_parser("template", help="write a candidate JSON template")
    template.add_argument("--out", required=True)
    template.set_defaults(func=command_template)

    evaluate = subparsers.add_parser("evaluate", help="evaluate candidate products")
    evaluate.add_argument("--criteria", required=True)
    evaluate.add_argument("--candidates", required=True)
    evaluate.add_argument("--markdown-out")
    evaluate.add_argument("--html-out")
    evaluate.add_argument("--json-out")
    evaluate.set_defaults(func=command_evaluate)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
