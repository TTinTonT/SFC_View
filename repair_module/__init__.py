# -*- coding: utf-8 -*-
"""
Self-contained Repair backend (Python library).

Copy the ``repair_module/`` folder into another project, install dependencies from
``repair_module/requirements.txt``, configure ``repair_module/config/db_config.py``,
then import from ``repair_module.services``.
"""

from repair_module.services import (
    get_repair_options,
    list_debug_reason_codes,
    get_repair_wip,
    get_flow_state,
    get_assy_tree,
    get_fail_history,
    validate_error_code_service,
    submit_fail_input,
    di_next,
    ri_next,
    do_pass,
    do_fail,
    ro_next,
    pass_jump,
    execute_repair,
)

__all__ = [
    "get_repair_options",
    "list_debug_reason_codes",
    "get_repair_wip",
    "get_flow_state",
    "get_assy_tree",
    "get_fail_history",
    "validate_error_code_service",
    "submit_fail_input",
    "di_next",
    "ri_next",
    "do_pass",
    "do_fail",
    "ro_next",
    "pass_jump",
    "execute_repair",
]

__version__ = "1.0.0"
