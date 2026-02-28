# -*- coding: utf-8 -*-
"""Analytics config: load/save analytics_config.json, pass_rules, stations_order, timezone, defaults."""

import json
import os
from typing import Dict, List, Any, Set

try:
    import pytz
except ImportError:
    pytz = None  # type: ignore

_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "analytics_config.json")

_DEFAULT_STATIONS_ORDER = ["FLA", "FLB", "AST", "FTS", "FCT", "RIN", "NVL"]

_DEFAULT_CONFIG = {
    "pass_rules": {
        "FLA": [],
        "FLB": [],
        "AST": [],
        "FTS": [],
        "FCT": ["675-24109-0010-TS2", "675-24109-0020-TS2"],
        "RIN": [],
        "NVL": [],
        "unknown_station": "RIN",
    },
    "stations_order": _DEFAULT_STATIONS_ORDER,
    "timezone": "America/Los_Angeles",
    "extend_hours": 2,
    "top_k_errors_default": 5,
    "aggregation_default": "daily",
    "error_stats_ttc_buckets": [5, 15, 60],
    "error_stats_p90": 0.9,
}

_cached_config: Dict[str, Any] = {}


def _load_config() -> Dict[str, Any]:
    """Load config from JSON file, merge with defaults."""
    global _cached_config
    if _cached_config:
        return _cached_config
    result = dict(_DEFAULT_CONFIG)
    if os.path.isfile(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _merge(result, data)
        except (json.JSONDecodeError, OSError):
            pass
    _cached_config = result
    return result


def _merge(base: dict, override: dict) -> None:
    """Merge override into base in-place."""
    for k, v in override.items():
        if k not in base:
            base[k] = v
        elif isinstance(base[k], dict) and isinstance(v, dict):
            _merge(base[k], v)
        else:
            base[k] = v


def _reload_config() -> None:
    """Clear cache so next load reads from file."""
    global _cached_config
    _cached_config = {}


def get(key: str, default: Any = None) -> Any:
    """Get a top-level config value."""
    cfg = _load_config()
    return cfg.get(key, default)


def get_stations_order() -> List[str]:
    """Station order for Test Flow Analysis."""
    val = get("stations_order")
    if isinstance(val, list) and all(isinstance(x, str) for x in val):
        return list(val)
    return list(_DEFAULT_CONFIG["stations_order"])


def get_extend_hours() -> int:
    """SFC API: extend request range by N hours."""
    val = get("extend_hours")
    if isinstance(val, (int, float)):
        return int(val)
    return _DEFAULT_CONFIG["extend_hours"]


def get_top_k_errors_default() -> int:
    """Default Top K errors for error stats."""
    val = get("top_k_errors_default")
    if isinstance(val, (int, float)):
        v = int(val)
        if v >= 1:
            return v
    return _DEFAULT_CONFIG["top_k_errors_default"]


def get_ca_tz():
    """California timezone for date ranges."""
    tz_name = get("timezone") or _DEFAULT_CONFIG["timezone"]
    if pytz:
        try:
            return pytz.timezone(tz_name)
        except Exception:
            pass
    return None


def get_pass_rules() -> Dict[str, Any]:
    """
    Return pass_rules dict: every station in stations_order has a key (list of part numbers),
    plus unknown_station. Missing station keys are filled with [].
    """
    stations = get_stations_order()
    rules = get("pass_rules")
    if not isinstance(rules, dict):
        rules = dict(_DEFAULT_CONFIG["pass_rules"])
    out = {}
    for st in stations:
        if st in rules and isinstance(rules[st], list):
            out[st] = list(rules[st])
        else:
            out[st] = []
    out["unknown_station"] = (rules.get("unknown_station") or "RIN").strip().upper() or "RIN"
    return out


def set_pass_rules(pass_rules: Dict[str, Any]) -> None:
    """
    Save pass_rules to config file and reload.
    Ensures all station keys from stations_order exist (empty list if missing).
    pass_rules: { station: [part_numbers...], "unknown_station": "RIN" }
    """
    stations = get_stations_order()
    cfg = _load_config()
    pr = cfg.setdefault("pass_rules", {})
    pr.clear()
    for st in stations:
        if st in pass_rules and isinstance(pass_rules[st], list):
            pr[st] = [str(x).strip() for x in pass_rules[st] if str(x).strip()]
        else:
            pr[st] = []
    pr["unknown_station"] = (pass_rules.get("unknown_station") or "RIN").strip().upper() or "RIN"
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except OSError:
        raise
    _reload_config()


def get_error_stats_ttc_buckets() -> List[int]:
    """TTC bucket thresholds in minutes: [5, 15, 60] for <=5m, 5-15m, 15-60m, >60m."""
    val = get("error_stats_ttc_buckets")
    if isinstance(val, list) and len(val) >= 3:
        return [int(x) for x in val[:3] if isinstance(x, (int, float))]
    return list(_DEFAULT_CONFIG["error_stats_ttc_buckets"])


def get_error_stats_p90() -> float:
    """P90 percentile for TTC (0.9)."""
    val = get("error_stats_p90")
    if isinstance(val, (int, float)) and 0 <= val <= 1:
        return float(val)
    return _DEFAULT_CONFIG["error_stats_p90"]


def get_unassigned_part_numbers(observed_part_numbers: Set[str]) -> List[str]:
    """
    Return part numbers that are not in any station list.
    observed_part_numbers: set of part numbers seen in data.
    """
    rules = get_pass_rules()
    assigned: Set[str] = set()
    for k, v in rules.items():
        if k == "unknown_station":
            continue
        if isinstance(v, list):
            for pn in v:
                p = (pn or "").strip().upper()
                if p and p != "UNKNOWN":
                    assigned.add(p)
    unassigned = []
    for pn in observed_part_numbers:
        p = (pn or "").strip().upper()
        if p and p != "UNKNOWN" and p not in assigned:
            unassigned.append(p)
    return sorted(unassigned)
