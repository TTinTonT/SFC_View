import os
import sys
import json
from datetime import datetime, timedelta

# add current dir to path
sys.path.insert(0, os.path.abspath("."))
from analytics.service import run_analytics_query
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def main():
    try:
        now = datetime.now()
        # Fetch data for the last 7 days to match the Yield Rate screenshot
        data = run_analytics_query(user_start=now - timedelta(days=7), user_end=now)
        
        print(f"\n--- ANALYTICS SUMMARY ---")
        print(json.dumps(data["summary"], indent=2))
        
        print(f"\n--- TEST FLOW TOTALS ---")
        print(json.dumps(data["test_flow"]["totals"], indent=2))
        
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
