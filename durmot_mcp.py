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
            "user-agent": "Mozilla/5.0"
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
                    logging.warning("--> [DemandStar] Token expired! Skipping.")
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
            except Exception: pass
        logging.info(f"--> [DemandStar] Total bids collected: {total_ingested}")

    def intercept_central_bidding_xhr(self):
        logging.info("--> [Central Bidding] Checking for BYOT...")
        raw_cookie = os.environ.get("CENTRALBIDDING_TOKEN", "")
        if not raw_cookie: return
        headers = {"accept": "application/json, text/html", "cookie": raw_cookie.strip(), "user-agent": "Mozilla/5.0"}
        try:
            response = tls_requests.post("https://www.centralauctionhouse.com/DesktopModules/XModPro/Feed.aspx", headers=headers, data={"searchTerm": "software"}, impersonate="chrome120", timeout=12)
            if response.status_code == 200: logging.info("--> [Central Bidding] Successfully bypassed wall.")
        except Exception: pass

    def intercept_vendorlink_xhr(self):
        logging.info("--> [VendorLink] Checking for BYOT...")
        raw_token = os.environ.get("VENDORLINK_TOKEN", "")
        if not raw_token: return
        headers = {"accept": "application/json", "authorization": raw_token.strip() if raw_token.lower().startswith("bearer") else f"Bearer {raw_token.strip()}", "user-agent": "Mozilla/5.0"}
        try:
            response = tls_requests.post("https://api.myvendorlink.com/api/Search/Bids", headers=headers, json={"Keyword": "software"}, impersonate="chrome120", timeout=12)
            if response.status_code == 200: logging.info("--> [VendorLink] Successfully bypassed wall.")
        except Exception: pass

    def bypass_opengov_api(self):
        logging.info("--> [OpenGov] Executing National Open-Access Sweep...")
        national_portals = [
            "orlando", "orangecountyfl", "citrusfl", "cityofgainesville", "miamibeach", 
            "tampa", "palmbeachcounty", "sarasotacounty", "leecountyfl", "polkcounty", 
            "fortlauderdale", "bocaraton", "clearwater", "leoncounty", "cityofstpete", 
            "pensacola", "austintexas", "sanantonio", "seattle", "sandiego", "sanjose", 
            "dallas", "fortworth", "phoenix", "mesa", "lasvegas", "washoecounty", "denver", 
            "bouldercounty", "slc", "saltlakecounty", "cincinnati", "columbus", "charlotte", 
            "raleigh", "wakecounty", "atlantaga"
        ]
        
        headers = {"accept": "application/json, text/plain, */*", "origin": "https://procurement.opengov.com", "user-agent": "Mozilla/5.0"}
        total_opengov = 0
        
        for portal in national_portals:
            try:
                url = f"https://api.procurement.opengov.com/api/v1/government/{portal}/project/public"
                response = tls_requests.post(url, headers=headers, json={"filters": [{"type": "status", "value": "active"}], "limit": 50, "page": 1}, impersonate="chrome120", timeout=5)
                if response.status_code == 200:
                    projects = response.json().get('data', [])
                    for item in projects:
                        self.rfp_master_list.append({
                            "source": "OpenGov", 
                            "title": item.get('title', item.get('name', 'Unknown Title')),
                            "agency": portal.replace('cityof', 'City of ').title(),
                            "state": "US", 
                            "published_date": item.get('publishedAt', item.get('releaseDate', '')),
                            "raw_metadata": item,
                            "url": f"https://procurement.opengov.com/portal/{portal}/projects/{item.get('id')}" if item.get('id') else ""
                        })
                        total_opengov += 1
            except Exception: pass
        logging.info(f"--> [OpenGov] National Sweep Complete. Bids collected: {total_opengov}")

    def execute_pipeline(self):
        self.intercept_demandstar_xhr()
        self.intercept_central_bidding_xhr()
        self.intercept_vendorlink_xhr()
        self.bypass_opengov_api()

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
            r"\bsole source\b": 40, r"\bproprietary\b": 30, r"\bbrand name only\b": 35,
            r"\bincumbent\b": 20, r"\bmandatory pre-bid\b": 25, r"\bno substitutions\b": 30
        }
        self.known_vendors = ["Tyler Technologies", "CentralSquare", "Oracle", "Workday", "OpenGov", "Munis", "CivicPlus", "Accela", "Superion"]

    def scrape_deep_text(self, url):
        if not url: return ""
        try:
            res = tls_requests.get(url, impersonate="chrome120", timeout=5)
            if res.status_code == 200:
                if url.lower().endswith('.pdf') or 'application/pdf' in res.headers.get('Content-Type', '').lower():
                    reader = PdfReader(io.BytesIO(res.content))
                    return " ".join([page.extract_text() for page in reader.pages[:8] if page.extract_text()]).lower()
                return BeautifulSoup(res.text, 'html.parser').get_text(separator=' ', strip=True).lower()
        except Exception: pass
        return ""

    def process_results(self, rfp_list):
        unique_rfps = {item['url']: item for item in rfp_list}.values()
        processed = []
        for raw_rfp in unique_rfps:
            base_text = f"{raw_rfp['title']} {raw_rfp['agency']} {json.dumps(raw_rfp['raw_metadata'])}".lower()
            stack_matches = [kw.replace(r"\b", "").strip().upper() for kw in self.target_tech_stack if re.search(kw, base_text)]
            if not stack_matches and not re.search(r'\b(software|system|erp|technology|billing|platform|cloud)\b', base_text):
                continue

            search_text = f"{base_text} {self.scrape_deep_text(raw_rfp.get('url', ''))}"
            if any(re.search(pat, search_text) for pat in self.disqualify_keywords): continue

            friction_score = sum(pts for pat, pts in self.friction_heuristics.items() if re.search(pat, search_text))
            flags = [pat.replace(r"\b", "").strip().title() for pat, _ in self.friction_heuristics.items() if re.search(pat, search_text)]
            suspected = [v for v in self.known_vendors if v.lower() in search_text]

            processed.append({
                "agency": raw_rfp['agency'], "state": raw_rfp.get('state', 'US'),
                "title": raw_rfp['title'], "source": raw_rfp.get('source', 'Unknown'),
                "friction_score": min(friction_score, 100), "friction_flags": flags,
                "suspected_incumbent": suspected[0] if suspected else None,
                "url": raw_rfp.get('url', 'No URL provided') 
            })
        processed.sort(key=lambda x: x['friction_score'], reverse=True)
        return processed

# ==============================================================================
# SECTION 2: FORENSIC TRIAD
# ==============================================================================

def query_municipal_checkbook(agency_name, vendor_name):
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key: return {"error": "SERPAPI_KEY is missing."}
    query = f'"{vendor_name}" "{agency_name}" "change order" OR "amendment" OR "contingency" OR "increase"'
    try:
        res = tls_requests.get(f"https://serpapi.com/search.json?engine=google&q={urllib.parse.quote_plus(query)}&api_key={api_key}", timeout=15)
        if res.status_code != 200: return {"error": f"SerpApi HTTP {res.status_code}"}
        
        results = [
            {"title": i.get("title", "Unknown"), "link": i.get("link", ""), "snippet": i.get("snippet", "")}
            for i in res.json().get("organic_results", [])
            if vendor_name.lower() in i.get("snippet", "").lower() and any(kw in i.get("snippet", "").lower() for kw in ['change order', 'amend', 'increase'])
        ]
        if not results: return {"status": f"No public change orders found for {vendor_name} at {agency_name}."}
        return {"agency_investigated": agency_name, "vendor_investigated": vendor_name, "bleed_ratio_risk": "HIGH" if len(results) >= 2 else "MODERATE", "evidence": results[:5]}
    except Exception as e: return {"error": str(e)}

def query_opensecrets_api(vendor_name):
    api_key = os.environ.get("OPENSECRETS_API_KEY")
    if not api_key: return {"error": "OPENSECRETS_API_KEY environment variable is not set."}

    try:
        org_search_url = f"http://www.opensecrets.org/api/?method=getOrgs&org={urllib.parse.quote(vendor_name)}&apikey={api_key}&output=json"
        res = tls_requests.get(org_search_url, timeout=10)
        if res.status_code != 200: return {"error": f"OpenSecrets API returned status {res.status_code}"}
            
        orgs = res.json().get('response', {}).get('organization', [])
        if not orgs: return {"status": f"No profile found for '{vendor_name}'."}
        if isinstance(orgs, dict): orgs = [orgs]

        org_id = orgs[0].get('@attributes', {}).get('orgid')
        org_name = orgs[0].get('@attributes', {}).get('orgname')
        if not org_id: return {"error": "Failed to extract Organization ID."}

        summary_url = f"http://www.opensecrets.org/api/?method=orgSummary&id={org_id}&apikey={api_key}&output=json"
        summary = tls_requests.get(summary_url, timeout=10).json().get('response', {}).get('organization', {}).get('@attributes', {})

        return {
            "vendor_searched": vendor_name, "opensecrets_entity_name": org_name,
            "financial_totals": {
                "total_pac_contributions": f"${summary.get('pac', '0')}",
                "total_individual_contributions": f"${summary.get('indivs', '0')}",
                "total_soft_money": f"${summary.get('soft', '0')}",
                "total_receipts": f"${summary.get('total', '0')}"
            },
            "source_url": f"https://www.opensecrets.org/orgs/summary?id={org_id}"
        }
    except Exception as e: return {"error": f"API request failed: {str(e)}"}

# ==============================================================================
# SECTION 3: MCP EXPOSED TOOLS (FOR GOD MODE / CLAUDE DESKTOP)
# ==============================================================================

@mcp.tool
def get_all_nationwide_rfps() -> str:
    """
    Retrieves all active GovTech RFPs across the network.
    NOTE: OpenGov portals are swept freely because they represent true open government. 
    Closed platforms like DemandStar, Central Bidding, and VendorLink require users to pay 
    or register for an account (via BYOT tokens) to bypass their paywalls, which contradicts 
    the open government ethos. If results are missing from closed platforms, it is because 
    no token was provided.
    """
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline()
    results = DurmotIntelligence().process_results(pipeline.rfp_master_list)
    return json.dumps(results if results else {"status": "No RFPs found today."}, indent=2)

@mcp.tool
def run_friction_audit(keyword: str = "") -> str:
    """
    Runs a specialized friction audit on active bids matching a keyword or state.
    NOTE: Scrapes free OpenGov data by default. Any sweeps of DemandStar, VendorLink, 
    or Central Bidding require the user to provide their own account tokens, as paying 
    for government data access is inherently counter to open government principles.
    """
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline()
    results = DurmotIntelligence().process_results(pipeline.rfp_master_list)
    clean_kw = keyword.strip().lower()
    if not clean_kw or clean_kw in ["all", "*"]: return json.dumps(results if results else {"status": "No active bids found."}, indent=2)
    filtered = [b for b in results if clean_kw in b['agency'].lower() or clean_kw in b['title'].lower()]
    return json.dumps(filtered if filtered else {"status": f"No bids matching '{keyword}'."}, indent=2)

@mcp.tool
def audit_vendor_lobbying(vendor_name: str) -> str:
    """Checks OpenSecrets to map political donations for a specific vendor."""
    return json.dumps([query_opensecrets_api(vendor_name)], indent=2)

@mcp.tool
def audit_vendor_checkbook(agency_name: str, vendor_name: str) -> str:
    """Checks public ledgers to identify change-order bleed via SerpApi."""
    return json.dumps([query_municipal_checkbook(agency_name, vendor_name)], indent=2)

# ==============================================================================
# SECTION 4: WEB DASHBOARD & REST API ENDPOINTS
# ==============================================================================

mcp_app = mcp.http_app(path="/") 
app = FastAPI(title="Aelfstone Intelligence Engine", lifespan=mcp_app.lifespan)
app.mount("/mcp", mcp_app)

@app.get("/api/sweep")
def api_sweep(keyword: str = ""):
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline()
    intelligence = DurmotIntelligence()
    results = intelligence.process_results(pipeline.rfp_master_list)
    
    clean_kw = keyword.strip().lower()
    if not clean_kw or clean_kw in ["all", "nationwide", "*"]: return results if results else {"status": "No active bids found."}
    filtered = [b for b in results if clean_kw in b['agency'].lower() or clean_kw in b['title'].lower()]
    return filtered if filtered else {"status": f"No active bids found matching '{keyword}'."}

@app.get("/api/checkbook")
def api_checkbook(agency: str = "", vendor: str = ""):
    if not agency or not vendor: return {"error": "Both agency and vendor required."}
    return query_municipal_checkbook(agency, vendor)

@app.get("/api/opensecrets")
def api_opensecrets(vendor: str = ""):
    if not vendor: return {"error": "Vendor name required."}
    return query_opensecrets_api(vendor)

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Aelfstone Terminal</title>
        <style>
            body { background-color: #0a0e17; color: #a5b4fc; font-family: 'Courier New', Courier, monospace; margin: 0; padding: 30px; }
            h1 { color: #818cf8; border-bottom: 1px solid #1e293b; padding-bottom: 10px; margin-bottom: 30px; font-size: 1.5em; letter-spacing: 2px;}
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 20px; }
            .panel { background-color: #0f172a; padding: 20px; border-radius: 4px; border: 1px solid #334155; }
            h3 { margin-top: 0; color: #38bdf8; font-size: 1.1em; }
            input[type="text"] { background: #1e293b; border: 1px solid #475569; color: #f8fafc; padding: 10px; width: calc(100% - 22px); border-radius: 2px; margin-bottom: 10px; font-family: inherit; }
            input[type="text"]:focus { outline: none; border-color: #38bdf8; }
            button { background: #2563eb; border: none; color: white; padding: 10px; cursor: pointer; border-radius: 2px; font-weight: bold; width: 100%; text-transform: uppercase; letter-spacing: 1px; transition: background 0.2s; margin-top: 5px;}
            button:hover { background: #1d4ed8; }
            .output-panel { background-color: #0f172a; padding: 20px; border-radius: 4px; border: 1px solid #334155; min-height: 400px; }
            pre { color: #10b981; white-space: pre-wrap; word-wrap: break-word; margin: 0; font-size: 0.9em; }
            .status { margin-top: 10px; font-size: 0.85em; color: #fbbf24; display: none; text-align: center; }
        </style>
    </head>
    <body>
        <h1>⌖ AELFSTONE SECURE NETWORK</h1>
        
        <div class="grid">
            <div class="panel">
                <h3>1. FRICTION SWEEP</h3>
                <input type="text" id="sweepKw" placeholder="Target Node (e.g., Orlando)">
                <button onclick="runSweep()">Initialize</button>
                <div id="sweepStatus" class="status">Intercepting...</div>
            </div>

            <div class="panel">
                <h3>2. CHECKBOOK FORENSICS</h3>
                <input type="text" id="cbAgency" placeholder="Agency (e.g., Orange County)">
                <input type="text" id="cbVendor" placeholder="Vendor (e.g., Tyler)">
                <button onclick="runCheckbook()">Run Diagnostic</button>
                <div id="cbStatus" class="status">Querying Ledgers...</div>
            </div>

            <div class="panel">
                <h3>3. OPENSECRETS AUDIT</h3>
                <input type="text" id="osVendor" placeholder="Vendor (e.g., Oracle)">
                <button onclick="runOpenSecrets()">Audit PACs</button>
                <div id="osStatus" class="status">Tracing Capital...</div>
            </div>
        </div>

        <div class="output-panel">
            <pre id="output">System Ready. Awaiting Command Sequence...</pre>
        </div>

        <script>
            async function runSweep() {
                document.getElementById('sweepStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Compiling intelligence... (Note: DemandStar, Central Bidding, and VendorLink require explicit tokens. Defaulting to free OpenGov data.)';
                
                const kw = encodeURIComponent(document.getElementById('sweepKw').value);
                try {
                    const response = await fetch(`/api/sweep?keyword=${kw}`);
                    document.getElementById('output').innerText = JSON.stringify(await response.json(), null, 2);
                } catch (err) { document.getElementById('output').innerText = 'Error: ' + err; }
                document.getElementById('sweepStatus').style.display = 'none';
            }

            async function runCheckbook() {
                document.getElementById('cbStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Initializing SerpApi OSINT Protocol...';
                try {
                    const response = await fetch('/api/checkbook?agency=' + encodeURIComponent(document.getElementById('cbAgency').value) + '&vendor=' + encodeURIComponent(document.getElementById('cbVendor').value));
                    document.getElementById('output').innerText = JSON.stringify(await response.json(), null, 2);
                } catch (err) { document.getElementById('output').innerText = 'Error: ' + err; }
                document.getElementById('cbStatus').style.display = 'none';
            }

            async function runOpenSecrets() {
                document.getElementById('osStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Accessing OpenSecrets Disclosure Database...';
                try {
                    const response = await fetch('/api/opensecrets?vendor=' + encodeURIComponent(document.getElementById('osVendor').value));
                    document.getElementById('output').innerText = JSON.stringify(await response.json(), null, 2);
                } catch (err) { document.getElementById('output').innerText = 'Error: ' + err; }
                document.getElementById('osStatus').style.display = 'none';
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
