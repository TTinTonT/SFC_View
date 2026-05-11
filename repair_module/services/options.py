# -*- coding: utf-8 -*-
from repair_module.config.repair_config import REASON_CODES, REPAIR_ACTIONS, DUTY_TYPES


def get_repair_options():
    """
    Same as GET /api/debug/repair/options.
    Returns dict with ok, reason_codes, repair_actions, duty_types.
    """
    try:
        return {
            "ok": True,
            "reason_codes": [{"code": r[0], "label": r[1], "desc": r[2]} for r in REASON_CODES],
            "repair_actions": list(REPAIR_ACTIONS),
            "duty_types": list(DUTY_TYPES),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
