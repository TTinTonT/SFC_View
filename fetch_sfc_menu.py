import os
import sys
import re
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# add current dir to path
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
    
    url = f"{SFC_BASE_URL}/L10_Report/Manufacture/yieldRateReport.jsp"
    
    data = {
        "FromDate": "2026/03/04",
        "FromTime": "07",
        "ToDate": "2026/03/11",
        "ToTime": "19",
        "MOType": "NORMAL",
        "LineName": "ALL",
        "ModelName": "ALL",
        "MONumber": ""
    }
    
    print(f"POST {url}...")
    r = sess.post(url, data=data, timeout=60, verify=False)
    print(f"Status: {r.status_code}")
    
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table")
        print(f"Found {len(tables)} tables")
        
        if tables:
            links = tables[1].find_all("a")
            print(f"Found {len(links)} links in data table")
            for a in links[:10]:
                print(f"Link text: '{a.get_text(strip=True)}', href: {a.get('href')}")

if __name__ == "__main__":
    main()
