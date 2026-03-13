# -*- coding: utf-8 -*-
"""Parse log filenames via SSH to calculate exact unit pass records."""
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import paramiko

from config.app_config import LOG_SERVER_IP, LOG_SERVER_USER, LOG_SERVER_PWD

# Example log: IGFG_NA_675-24109-0000-T2B_2100926000111_P_RIN_20260311T082610Z.zip
# Groups: (Model) (SN) (P/F) (Station) (DateTime)
LOG_REGEX = re.compile(
    r"^[^_]+_[^_]+_([^_]+)_([^_]+)_(P|F)_([^_]+)_(\d{8}T\d{6}Z)\.zip$"
)

def _get_dates_in_range(start_date: datetime, end_date: datetime) -> List[datetime]:
    """Return a list of local datetimes representing each day in the range."""
    # We just need the unique Year/Month/Day folders
    dates = []
    curr = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    while curr <= end:
        dates.append(curr)
        curr += timedelta(days=1)
    return dates

def fetch_ssh_logs(user_start: datetime, user_end: datetime) -> List[dict]:
    """
    Connect to the log server, extract files matching the dates,
    and parse the names into standard test dict rows.
    """
    rows = []
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(
            hostname=LOG_SERVER_IP,
            username=LOG_SERVER_USER,
            password=LOG_SERVER_PWD,
            timeout=10
        )
        
        dates_to_check = _get_dates_in_range(user_start, user_end)
        
        for dt in dates_to_check:
            year_str = dt.strftime("%Y")
            month_str = dt.strftime("%m")
            day_str = dt.strftime("%d")
            
            # The user specified /mnt/L10/2026/ then /{month}/{date}
            # For example, /mnt/L10/2026/03/11 or /mnt/L10/2026/0311
            # We see files are placed in station subfolders: /mnt/L10/2026/03/11/FLA/*.zip
            folder_path = f"/mnt/L10/{year_str}/{month_str}/{day_str}"
            
            # Use 'find' to discover all zips inside the day folder recursively
            cmd = f"find {folder_path} -name '*.zip' 2>/dev/null"
            stdin, stdout, stderr = ssh.exec_command(cmd)
            
            # Reading output lines
            lines = stdout.readlines()
            for line in lines:
                filename = os.path.basename(line.strip())
                if not filename:
                    continue
                    
                match = LOG_REGEX.match(filename)
                if match:
                    model = match.group(1)
                    sn = match.group(2)
                    pf_flag = match.group(3)
                    station = match.group(4)
                    date_str = match.group(5)
                    
                    try:
                        # Parse 20260311T082610Z as UTC
                        test_time_utc = datetime.strptime(date_str, "%Y%m%dT%H%M%SZ")
                        # Convert to CST (UTC+8) for comparison with user_start/user_end
                        test_time_cst = test_time_utc + timedelta(hours=8)
                    except ValueError:
                        continue
                        
                    # Filter perfectly to user range (which are naive local datetimes)
                    if not (user_start <= test_time_cst <= user_end):
                        continue
                        
                    result_str = "PASS" if pf_flag == "P" else "FAIL"
                    
                    rows.append({
                        "serial_number": sn,
                        "work_order": "UNKNOWN",
                        "part_number": model,
                        "station": station,
                        "test_time": test_time_cst.strftime("%Y/%m/%d %H:%M:%S"),
                        "test_time_dt": test_time_cst,
                        "result": result_str,
                        "error_code": "",
                        "failure_msg": "From SSH Logs" if result_str == "FAIL" else "",
                        "current_station": station,
                        "station_instance": "",
                        "is_bonepile": False
                    })
                    
    except Exception as e:
        print(f"SSH Log fetch error: {e}")
    finally:
        ssh.close()
        
    return rows
