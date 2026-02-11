# -*- coding: utf-8 -*-
"""Pass/fail logic for SFC rows based on part number rules."""

from typing import List

from config.pass_rules import is_sn_passed as _is_sn_passed_from_rules


def is_sn_passed(rows_for_sn: List[dict]) -> bool:
    """
    Return True if SN has at least one row with RESULT=PASS and station
    matching the pass rule for that row's part_number.
    """
    return _is_sn_passed_from_rules(rows_for_sn)
