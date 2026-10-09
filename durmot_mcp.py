import sys
import os
import re
import io
import json
import logging
import urllib.parse
from bs4 import BeautifulSoup
from pypdf import PdfReader
from curl_cffi import requests as tls_requests

# FastMCP SDK
from fastmcp import FastMCP

# OPSEC CRITICAL: All logs must go to stderr so they appear in Railway's Deploy Logs.
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr 
)

mcp = FastMCP("Durmot Lead & Forensic Engine")

# ==============================================================================
# SECTION 1: GOVTECH SCRAPING & FRICTION ENGINE
# ==============================================================================

class RFPDataIngestion:
    def __init__(self):
        self.rfp_master_list = []

    def intercept_demandstar_xhr(self):
        logging.info("--> [DemandStar] Checking for BYOT (Bring Your Own Token)...")
        url = "https://api.demandstar.com/contents/content/v1/bids/search"
        raw_token = os.environ.get("DEMANDSTAR_TOKEN", "")
        auth_token = re.sub(r'[\r\n]+', '', raw_token).strip()
        
        if not auth_token:
            logging.info("--> [DemandStar] No token provided. Skipping DemandStar.")
            return

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://www.demandstar.com",
            "referer": "https://www.demandstar.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        if not auth_token.lower().startswith("bearer ") and not auth_token.startswith("ey"):
            headers["cookie"] = auth_token
        else:
            headers["authorization"] = auth_token if auth_token.startswith("Bearer ") else f"Bearer {auth_token}"

        search_terms = ["software", "erp", "system", "technology", "billing", "implementation", "cloud"]
        total_ingested = 0
        
        for term in search_terms:
            payload = {
                "bidName": term, "showBids": "externalBids", "includeExternalBids": "true",
                "bidStatus": "AC", "sortBy": "broadCastDate", "sortOrder": "DESC",
                "page": 1, "limit": 50
            }
            try:
                response = tls_requests.post(url, headers=headers, json=payload, impersonate="chrome120", timeout=12)
                
                if response.status_code == 401:
                    logging.warning("--> [DemandStar] Token expired! Skipping DemandStar.")
                    return  
                    
                if response.status_code == 200:
                    data = response.json()
                    bids = data.get('result', []) if isinstance(data, dict) else data
                    for item in bids:
                        raw_state = item.get('state') or item.get('agencyState') or item.get('broadcastState') or 'US'
                        self.rfp_master_list.append({
                            "source": "DemandStar", 
                            "title": item.get('bidName', 'Unknown Title'),
                            "agency": item.get('agency', 'Unknown Agency'),
                            "state": str(raw_state).strip().upper(),
                            "published_date": item.get('broadCastDate', ''),
                            "raw_metadata": item,
                            "url": f"https://www.demandstar.com/app/bids/{item.get('bidId', '')}"
                        })
                        total_ingested += 1
            except Exception as e:
                pass
                
        logging.info(f"--> [DemandStar] Total bids collected: {total_ingested}")

    def intercept_central_bidding_xhr(self):
        logging.info("--> [Central Bidding] Checking for BYOT (SJRWMD Secondary)...")
        raw_cookie = os.environ.get("CENTRALBIDDING_TOKEN", "")
        
        if not raw_cookie:
            logging.info("--> [Central Bidding] No token provided. Skipping.")
            return

        headers = {
            "accept": "application/json, text/html",
            "cookie": raw_cookie.strip(),
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        url = "https://www.centralauctionhouse.com/DesktopModules/XModPro/Feed.aspx"
        try:
            response = tls_requests.post(url, headers=headers, data={"searchTerm": "software"}, impersonate="chrome120", timeout=12)
            if response.status_code == 200:
                logging.info("--> [Central Bidding] Successfully bypassed wall. (Ready for payload mapping)")
            else:
                logging.warning(f"--> [Central Bidding] Token expired or rejected (HTTP {response.status_code})")
        except Exception:
            pass

    def intercept_vendorlink_xhr(self):
        logging.info("--> [VendorLink] Checking for BYOT (OUC etc.)...")
        raw_token = os.environ.get("VENDORLINK_TOKEN", "")
        
        if not raw_token:
            logging.info("--> [VendorLink] No token provided. Skipping.")
            return

        headers = {
            "accept": "application/json",
            "authorization": raw_token.strip() if raw_token.lower().startswith("bearer") else f"Bearer {raw_token.strip()}",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        url = "https://api.myvendorlink.com/api/Search/Bids"
        try:
            response = tls_requests.post(url, headers=headers, json={"Keyword": "software"}, impersonate="chrome120", timeout=12)
            if response.status_code == 200:
                logging.info("--> [VendorLink] Successfully bypassed wall. (Ready for payload mapping)")
            else:
                logging.warning(f"--> [VendorLink] Token expired or rejected (HTTP {response.status_code})")
        except Exception:
            pass

    def bypass_opengov_api(self):
        logging.info("--> [OpenGov] Executing National Open-Access Sweep...")
        
        # Massive National OpenGov Array (Public/No-Auth Required)
        national_portals = [
            # Florida Heavyweights
            "orlando", "orangecountyfl", "citrusfl", "cityofgainesville", "miamibeach", 
            "tampa", "palmbeachcounty", "sarasotacounty", "leecountyfl",
            "polkcounty", "fortlauderdale", "bocaraton", "clearwater",
            "leoncounty", "cityofstpete", "pensacola",
            
            # National Heavyweights
            "austintexas", "sanantonio", "seattle", "sandiego", 
            "sanjose", "dallas", "fortworth", "phoenix", "mesa",
            "lasvegas", "washoecounty", "denver", "bouldercounty",
            "slc", "saltlakecounty", "cincinnati", "columbus",
            "charlotte", "raleigh", "wakecounty", "atlantaga"
        ]
        
        headers = {
            "accept": "application/json, text/plain, */*",
            "origin": "https://procurement.opengov.com",
            "user-agent": "Mozilla/5.0"
        }
        
        total_opengov = 0
        for portal in national_portals:
            url = f"https://api.procurement.opengov.com/api/v1/government/{portal}/project/public"
            payload = {"filters": [{"type": "status", "value": "active"}], "limit": 50, "page": 1}
            try:
                response = tls_requests.post(url, headers=headers, json=payload, impersonate="chrome120", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    projects = data.get('data', []) if isinstance(data, dict) else data
                    if projects:
                        logging.info(f"--> [OpenGov] {portal.upper()} returned {len(projects)} active projects")
                        
                    for item in projects:
                        self.rfp_master_list.append({
                            "source": "OpenGov", 
                            "title": item.get('title', item.get('name', 'Unknown Title')),
                            "agency": portal.replace('cityof', 'City of ').title(),
                            "state": "US", # State routing is handled by the OpenGov namespace
                            "published_date": item.get('publishedAt', item.get('releaseDate', '')),
                            "raw_metadata": item,
                            "url": f"https://procurement.opengov.com/portal/{portal}/projects/{item.get('id')}" if item.get('id') else ""
                        })
                        total_opengov += 1
            except Exception as e:
                pass # Silently skip any invalid portal slugs and keep hunting
                
        logging.info(f"--> [OpenGov] National Sweep Complete. Bids collected: {total_opengov}")

    def execute_pipeline(self):
        self.intercept_demandstar_xhr()       # Needs BYOT (SJRWMD)
        self.intercept_central_bidding_xhr()  # Needs BYOT (SJRWMD Secondary)
        self.intercept_vendorlink_xhr()       # Needs BYOT (Orlando Utilities Commission)
        self.bypass_opengov_api()             # Free Sweep (Orlando, Orange County Utilities, National nodes)
        logging.info(f"--> [Master List] Total raw records aggregated: {len(self.rfp_master_list)}")

class DurmotIntelligence:
    def __init__(self):
        self.disqualify_keywords = [
            r"\bwater treatment plant\b", r"\bpump station\b", r"\bsewer line\b",
            r"\bdirectional boring\b", r"\bconcrete\b", r"\basphalt\b",
            r"\bdesign-build\b", r"\bzoning\b", r"\bauction\b"
        ]
        self.target_tech_stack = [
            r"\bsoftware\b", r"\berp\b", r"\butility billing\b",
            r"\bcrm\b", r"\btyler\b", r"\bmunis\b", r"\bopengov\b",
            r"\bimplementation\b", r"\bcloud\b", r"\bsystem\b"
        ]
        self.friction_heuristics = {
            r"\bsole source\b": 40,
            r"\bproprietary\b": 30,
            r"\bbrand name only\b": 35,
            r"\bincumbent\b": 20,
            r"\bmandatory pre-bid\b": 25,
            r"\bno substitutions\b": 30
        }
        self.known_vendors = [
            "Tyler Technologies", "CentralSquare", "Oracle", "Workday", 
            "OpenGov", "Munis", "CivicPlus", "Accela", "Superion"
        ]

    def scrape_deep_text(self, url):
        if not url: return ""
        try:
            res = tls_requests.get(url, impersonate="chrome120", timeout=5)
            if res.status_code == 200:
                if url.lower().endswith('.pdf') or 'application/pdf' in res.headers.get('Content-Type', '').lower():
                    reader = PdfReader(io.BytesIO(res.content))
                    return " ".join([page.extract_text() for page in reader.pages[:8] if page.extract_text()]).lower()
                return BeautifulSoup(res.text, 'html.parser').get_text(separator=' ', strip=True).lower()
        except Exception:
            pass
        return ""

    def score_and_flag(self, rfp):
        base_search_text = f"{rfp['title']} {rfp['agency']} {json.dumps(rfp['raw_metadata'])}".lower()
        stack_matches = [kw.replace(r"\b", "").strip().upper() for kw in self.target_tech_stack if re.search(kw, base_search_text)]
                
        if not stack_matches and not re.search(r'\b(software|system|erp|technology|billing|platform|cloud)\b', base_search_text):
            return None

        deep_text = self.scrape_deep_text(rfp.get('url', ''))
        search_text = f"{base_search_
