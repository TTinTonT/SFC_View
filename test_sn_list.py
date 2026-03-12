from datetime import datetime
from analytics.sn_list import compute_sn_list

computed = {
    "_sn_tests": {
        "2100726000003": [
            {"station": "FLB", "result": "PASS", "test_time": "2026/03/12 09:30:28", "test_time_dt": datetime(2026, 3, 12, 9, 30, 28)},
            {"station": "FTS", "result": "FAIL", "test_time": "2026/03/12 09:37:28", "test_time_dt": datetime(2026, 3, 12, 9, 37, 28)},
        ]
    },
    "_sn_pass": {"2100726000003": False},
    "_sn_latest_part": {"2100726000003": "675-24109-0000-T2B"},
    "_sn_latest_dt": {"2100726000003": datetime(2026, 3, 12, 9, 37, 28)},
    "rows": [
        {"serial_number": "2100726000003", "station": "FLB", "result": "PASS", "test_time": "2026/03/12 09:30:28", "test_time_dt": datetime(2026, 3, 12, 9, 30, 28)},
        {"serial_number": "2100726000003", "station": "FTS", "result": "FAIL", "test_time": "2026/03/12 09:37:28", "test_time_dt": datetime(2026, 3, 12, 9, 37, 28)},
    ]
}

res = compute_sn_list(computed, metric="test_flow", station="FLB", outcome="pass")
print("Target station (FLB) pass output:")
for r in res:
    print(r)
