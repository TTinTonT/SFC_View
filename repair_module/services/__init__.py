# -*- coding: utf-8 -*-
"""High-level Repair API functions (plain dict responses, no Flask)."""

from repair_module.services.options import get_repair_options
from repair_module.services.debug_reason_codes import list_debug_reason_codes
from repair_module.services.repair_wip import get_repair_wip
from repair_module.services.flow_state import get_flow_state
from repair_module.services.assy_tree import get_assy_tree
from repair_module.services.fail_history import get_fail_history
from repair_module.services.error_code import validate_error_code_service
from repair_module.services.fail_input import submit_fail_input
from repair_module.services.di_next import di_next
from repair_module.services.ri_next import ri_next
from repair_module.services.do_pass import do_pass
from repair_module.services.do_fail import do_fail
from repair_module.services.ro_next import ro_next
from repair_module.services.pass_jump import pass_jump
from repair_module.services.execute import execute_repair

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
