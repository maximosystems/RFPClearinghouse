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
            except Exception:
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
            except Exception:
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
        search_text = f"{base_search_text} {deep_text}"
        
        for pattern in self.disqualify_keywords:
            if re.search(pattern, search_text): return None  
        
        friction_score = 0
        friction_flags = []
        for pattern, points in self.friction_heuristics.items():
            if re.search(pattern, search_text):
                friction_score += points
                friction_flags.append(pattern.replace(r"\b", "").strip().title())

        suspected_vendors = [vendor for vendor in self.known_vendors if vendor.lower() in search_text]
                
        rfp['friction_score'] = min(friction_score, 100)
        rfp['friction_flags'] = friction_flags
        rfp['raw_metadata']['durmot_stack_matches'] = list(set(stack_matches)) 
        rfp['suspected_incumbent'] = suspected_vendors[0] if suspected_vendors else None
        
        return rfp

    def process_results(self, rfp_list):
        unique_rfps = {item['url']: item for item in rfp_list}.values()
        processed = []
        for raw_rfp in unique_rfps:
            rfp = self.score_and_flag(raw_rfp)
            if not rfp: continue
            
            processed.append({
                "agency": rfp['agency'],
                "state": rfp.get('state', 'US'),
                "title": rfp['title'],
                "published_date": rfp.get('published_date', ''),
                "source": rfp.get('source', 'Unknown'),
                "friction_score": rfp['friction_score'],
                "friction_flags": rfp['friction_flags'],
                "suspected_incumbent": rfp['suspected_incumbent'],
                "tech_stack_hits": rfp['raw_metadata'].get('durmot_stack_matches', []),
                "ai_next_action_prompt": f"If suspected_incumbent is not null, run audit_vendor_checkbook for '{rfp['agency']}' and '{rfp['suspected_incumbent']}'." if rfp['suspected_incumbent'] else "No clear incumbent identified.",
                "url": rfp.get('url', 'No URL provided') 
            })
            
        processed.sort(key=lambda x: x['friction_score'], reverse=True)
        return processed

# ==============================================================================
# SECTION 2: FORENSIC TRIAD (OPENSECRETS & OPEN DATA OSINT)
# ==============================================================================

def query_opensecrets_api(vendor_name):
    api_key = os.environ.get("OPENSECRETS_API_KEY")
    if not api_key:
        return {"error": "OPENSECRETS_API_KEY environment variable is not set."}

    logging.info(f"Querying OpenSecrets API for: {vendor_name}")
    try:
        org_search_url = f"http://www.opensecrets.org/api/?method=getOrgs&org={urllib.parse.quote(vendor_name)}&apikey={api_key}&output=json"
        res = tls_requests.get(org_search_url, timeout=10)
        if res.status_code != 200:
            return {"error": f"OpenSecrets API returned status {res.status_code}"}
            
        data = res.json()
        orgs = data.get('response', {}).get('organization', [])
        if not orgs: return {"status": f"No OpenSecrets profile found for '{vendor_name}'."}

        if isinstance(orgs, dict): orgs = [orgs]

        top_org = orgs[0].get('@attributes', {})
        org_id = top_org.get('orgid')
        org_name = top_org.get('orgname')

        if not org_id: return {"error": "Failed to extract Organization ID from OpenSecrets."}

        summary_url = f"http://www.opensecrets.org/api/?method=orgSummary&id={org_id}&apikey={api_key}&output=json"
        sum_res = tls_requests.get(summary_url, timeout=10)
        sum_data = sum_res.json()
        summary = sum_data.get('response', {}).get('organization', {}).get('@attributes', {})

        return {
            "vendor_searched": vendor_name,
            "opensecrets_entity_name": org_name,
            "financial_totals": {
                "total_pac_contributions": f"${summary.get('pac', '0')}",
                "total_individual_contributions": f"${summary.get('indivs', '0')}",
                "total_soft_money": f"${summary.get('soft', '0')}",
                "total_receipts": f"${summary.get('total', '0')}"
            },
            "source_url": f"https://www.opensecrets.org/orgs/summary?id={org_id}"
        }
    except Exception as e:
        return {"error": f"API request failed: {str(e)}"}

def query_municipal_checkbook(agency_name, vendor_name):
    logging.info(f"Scanning open checkbooks via SerpApi for: {vendor_name} at {agency_name}")
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key: return {"error": "SERPAPI_KEY is missing from environment variables."}

    query = f'"{vendor_name}" "{agency_name}" "change order" OR "amendment" OR "contingency" OR "increase"'
    url = f"https://serpapi.com/search.json?engine=google&q={urllib.parse.quote_plus(query)}&api_key={api_key}"
    
    try:
        res = tls_requests.get(url, timeout=15)
        if res.status_code != 200: return {"error": f"SerpApi returned status {res.status_code}: {res.text}"}
             
        data = res.json()
        results = []
        for item in data.get("organic_results", []):
            snippet = item.get("snippet", "")
            if vendor_name.lower() in snippet.lower() and any(kw in snippet.lower() for kw in ['change order', 'amend', 'increase']):
                results.append({"title": item.get("title", "Unknown"), "link": item.get("link", ""), "snippet": snippet})
                
        if not results: return {"status": f"No public change orders or budget increases found for {vendor_name} at {agency_name}."}
        risk_flag = "HIGH (Multiple historical budget expansions detected)" if len(results) >= 2 else "MODERATE"
        
        return {
            "agency_investigated": agency_name,
            "vendor_investigated": vendor_name,
            "bleed_ratio_risk": risk_flag,
            "public_record_evidence": results[:5]
        }
    except Exception as e:
        return {"error": f"Search API failed: {str(e)}"}

# ==============================================================================
# SECTION 3: MCP EXPOSED TOOLS
# ==============================================================================

@mcp.tool
def get_all_nationwide_rfps() -> str:
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline()
    intelligence = DurmotIntelligence()
    results = intelligence.process_results(pipeline.rfp_master_list)
    return json.dumps(results if results else {"status": "No RFPs found today."}, indent=2)

@mcp.tool
def get_clean_leads() -> str:
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline()
    intelligence = DurmotIntelligence()
    results = intelligence.process_results(pipeline.rfp_master_list)
    prime = [b for b in results if b['friction_score'] == 0]
    return json.dumps(prime if prime else {"status": "No zero-friction Prime Leads found today."}, indent=2)

@mcp.tool
def run_friction_audit(keyword: str = "") -> str:
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline()
    intelligence = DurmotIntelligence()
    results = intelligence.process_results(pipeline.rfp_master_list)
    
    clean_kw = keyword.strip().lower()
    if not clean_kw or clean_kw in ["all", "nationwide", "*"]:
        return json.dumps(results if results else {"status": "No active bids found."}, indent=2)

    state_names = {"florida": "FL", "texas": "TX", "california": "CA", "georgia": "GA", "new york": "NY"}
    target_state = state_names.get(clean_kw, clean_kw.upper())

    filtered = [
        b for b in results 
        if clean_kw in b['agency'].lower() 
        or b['state'].upper() == target_state 
        or clean_kw in b['title'].lower()
    ]
    return json.dumps(filtered if filtered else {"status": f"No active bids found matching '{keyword}'."}, indent=2)

@mcp.tool
def audit_vendor_lobbying(vendor_name: str) -> str:
    report = query_opensecrets_api(vendor_name)
    return json.dumps([report], indent=2)

@mcp.tool
def audit_vendor_checkbook(agency_name: str, vendor_name: str) -> str:
    report = query_municipal_checkbook(agency_name, vendor_name)
    return json.dumps([report], indent=2)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport='sse', host='0.0.0.0', port=port)
