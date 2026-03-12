import os
import sys
from bs4 import BeautifulSoup
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.path.insert(0, os.path.abspath("."))
from sfc.client import _get_session
from config.app_config import SFC_BASE_URL

def main():
    sess = _get_session()
    if not sess:
        print("Login failed")
        return
        
    print(f"Logged in. Setting customer to NVIDIA via Top.jsp")
    sess.get(f"{SFC_BASE_URL}/System/Top.jsp", verify=False)
    
    url = f"{SFC_BASE_URL}/L10_Report/Manufacture/Show_First_Fail_PPID3.jsp"
    
    # Try fetching the first one from our yield_debug.html
    params = {
        "FromDate": "20260304",
        "ToDate": "20260311",
        "FromTime": "00",
        "ToTime": "23",
        "LineName": "ALL",
        "MONumber": "",
        "MOType": "NORMAL",
        "GroupName": "SYS_TEST"
    }
    
    print(f"GET {url}...")
    r = sess.get(url, params=params, verify=False)
    print(f"Status: {r.status_code}")
    
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table")
        if table:
            rows = table.find_all("tr")
            print(f"Found table with {len(rows)} rows")
            if rows:
                headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
                print("HEADERS:", headers)
                for i, row in enumerate(rows[1:3]): # print a couple rows
                    cells = [td.get_text(strip=True) for td in row.find_all(["th", "td"])]
                    print(f"Row {i+1}: {cells}")
        else:
            print("No table found")

if __name__ == "__main__":
    main()
