import sys
import os
import re
import io
import json
import logging
import urllib.parse
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from pypdf import PdfReader
from curl_cffi import requests as tls_requests

# FastMCP & FastAPI Integration
from fastmcp import FastMCP
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

# OPSEC CRITICAL: Logs stream to Railway Deploy Logs
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr 
)

# 1. Initialize MCP Server
mcp = FastMCP("Aelfstone Intelligence Engine")

# ==============================================================================
# INDUSTRY PROFILES (DYNAMIC OSINT TARGETING)
# ==============================================================================
INDUSTRY_PROFILES = {
    "govtech": {
        "search_terms": ["software", "erp", "system", "technology", "billing", "cloud"],
        "tech_stack": [r"\bsoftware\b", r"\berp\b", r"\butility billing\b", r"\bcrm\b", r"\btyler\b", r"\bmunis\b", r"\bopengov\b", r"\bcloud\b"],
        "disqualify": [r"\bwater treatment\b", r"\bpump station\b", r"\bsewer\b", r"\bdirectional boring\b", r"\bconcrete\b", r"\basphalt\b", r"\broofing\b"],
        "vendors": ["Tyler Technologies", "CentralSquare", "Oracle", "Workday", "OpenGov", "Munis", "CivicPlus"]
    },
    "construction": {
        "search_terms": ["roofing", "asphalt", "concrete", "paving", "construction", "hvac", "renovation"],
        "tech_stack": [r"\broofing\b", r"\basphalt\b", r"\bconcrete\b", r"\bpaving\b", r"\bhvac\b", r"\bconstruction\b", r"\btremco\b", r"\bgarland\b"],
        "disqualify": [r"\bsoftware\b", r"\berp\b", r"\bsaas\b", r"\bcloud\b", r"\bcybersecurity\b"],
        "vendors": ["Centimark", "Tremco", "Garland", "Cemex", "Vulcan Materials"]
    },
    "all": {
        "search_terms": [""],
        "tech_stack": [r"."], # Regex match anything
        "disqualify": [],
        "vendors": []
    }
}

# ==============================================================================
# SECTION 1: GOVTECH SCRAPING & FRICTION ENGINE
# ==============================================================================

class RFPDataIngestion:
    def __init__(self, toggles=None, profile_name="govtech"):
        self.rfp_master_list = []
        self.toggles = toggles or {"demandstar": True, "centralbidding": True, "vendorlink": True, "opengov": True}
        self.profile = INDUSTRY_PROFILES.get(profile_name, INDUSTRY_PROFILES["govtech"])
        self.search_terms = self.profile["search_terms"]

    def intercept_demandstar_xhr(self):
        if not self.toggles.get("demandstar"): return
        logging.info("--> [DemandStar] Checking for BYOT...")
        url = "https://api.demandstar.com/contents/content/v1/bids/search"
        raw_token = os.environ.get("DEMANDSTAR_TOKEN", "")
        auth_token = re.sub(r'[\r\n]+', '', raw_token).strip()
        
        if not auth_token: return
        headers = {"accept": "application/json", "content-type": "application/json", "user-agent": "Mozilla/5.0"}
        if not auth_token.lower().startswith("bearer ") and not auth_token.startswith("ey"): headers["cookie"] = auth_token
        else: headers["authorization"] = auth_token if auth_token.startswith("Bearer ") else f"Bearer {auth_token}"

        total_ingested = 0
        for term in self.search_terms:
            if not term: continue
            payload = {"bidName": term, "showBids": "externalBids", "includeExternalBids": "true", "sortBy": "broadCastDate", "sortOrder": "DESC", "page": 1, "limit": 50}
            try:
                response = tls_requests.post(url, headers=headers, json=payload, impersonate="chrome120", timeout=12)
                if response.status_code == 200:
                    bids = response.json().get('result', [])
                    for item in bids:
                        self.rfp_master_list.append({
                            "source": "DemandStar", "title": item.get('bidName', 'Unknown'),
                            "agency": item.get('agency', 'Unknown'), "state": str(item.get('state') or 'US').strip().upper(),
                            "published_date": item.get('broadCastDate', ''), "raw_metadata": item,
                            "url": f"https://www.demandstar.com/app/bids/{item.get('bidId', '')}"
                        })
                        total_ingested += 1
            except Exception: pass
        logging.info(f"--> [DemandStar] Bids collected: {total_ingested}")

    def intercept_central_bidding_xhr(self):
        if not self.toggles.get("centralbidding"): return
        raw_cookie = os.environ.get("CENTRALBIDDING_TOKEN", "")
        if not raw_cookie: return
        headers = {"accept": "application/json", "content-type": "application/json", "cookie": raw_cookie.strip(), "user-agent": "Mozilla/5.0"}
        term = self.search_terms[0] if self.search_terms[0] else "bid"
        try: tls_requests.post("https://www.centralauctionhouse.com/DesktopModules/XModPro/Feed.aspx", headers=headers, data={"searchTerm": term}, impersonate="chrome120", timeout=12)
        except Exception: pass

    def intercept_vendorlink_xhr(self):
        if not self.toggles.get("vendorlink"): return
        raw_token = os.environ.get("VENDORLINK_TOKEN", "")
        if not raw_token: return
        headers = {"accept": "application/json", "content-type": "application/json", "authorization": raw_token.strip() if raw_token.lower().startswith("bearer") else f"Bearer {raw_token.strip()}", "user-agent": "Mozilla/5.0"}
        term = self.search_terms[0] if self.search_terms[0] else "bid"
        try: tls_requests.post("
