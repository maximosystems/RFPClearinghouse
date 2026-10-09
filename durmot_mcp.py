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
        "tech_stack": [r"\bsoftware\b", r"\berp\b", r"\butility billing\b", r"\bcrm\b", r"\btyler\b", r"\bmunis\b", r"\bcloud\b", r"\bsaas\b"],
        "disqualify": [r"\bwater treatment\b", r"\bpump station\b", r"\bsewer\b", r"\bdirectional boring\b", r"\bconcrete\b", r"\basphalt\b", r"\broofing\b"],
        "vendors": ["Tyler Technologies", "CentralSquare", "Oracle", "Workday", "Munis", "CivicPlus"]
    },
    "construction": {
        "search_terms": ["roofing", "asphalt", "concrete", "paving", "construction", "hvac", "renovation"],
        "tech_stack": [r"\broofing\b", r"\basphalt\b", r"\bconcrete\b", r"\bpaving\b", r"\bhvac\b", r"\bconstruction\b", r"\btremco\b", r"\bgarland\b"],
        "disqualify": [r"\bsoftware\b", r"\berp\b", r"\bsaas\b", r"\bcloud\b", r"\bcybersecurity\b"],
        "vendors": ["Centimark", "Tremco", "Garland", "Cemex", "Vulcan Materials"]
    },
    "all": {
        "search_terms": [""],
        "tech_stack": [r"."],
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
        if not auth_token.lower().startswith("bearer ") and not auth_token.startswith("ey"): 
            headers["cookie"] = auth_token
        else: 
            headers["authorization"] = auth_token if auth_token.startswith("Bearer ") else f"Bearer {auth_token}"

        total_ingested = 0
        for term in self.search_terms:
            if not term: continue
            payload = {
                "bidName": term, 
                "showBids": "externalBids", 
                "includeExternalBids": "true", 
                "sortBy": "broadCastDate", 
                "sortOrder": "DESC", 
                "page": 1, 
                "limit": 50
            }
            try:
                response = tls_requests.post(
                    url, 
                    headers=headers, 
                    json=payload, 
                    impersonate="chrome120", 
                    timeout=12
                )
                if response.status_code == 200:
                    bids = response.json().get('result', [])
                    for item in bids:
                        self.rfp_master_list.append({
                            "source": "DemandStar", 
                            "title": item.get('bidName', 'Unknown'),
                            "agency": item.get('agency', 'Unknown'), 
                            "state": str(item.get('state') or 'US').strip().upper(),
                            "published_date": item.get('broadCastDate', ''), 
                            "raw_metadata": item,
                            "url": f"https://www.demandstar.com/app/bids/{item.get('bidId', '')}"
                        })
                        total_ingested += 1
            except Exception: pass
        logging.info(f"--> [DemandStar] Bids collected: {total_ingested}")

    def intercept_central_bidding_xhr(self):
        if not self.toggles.get("centralbidding"): return
        raw_cookie = os.environ.get("CENTRALBIDDING_TOKEN", "")
        if not raw_cookie: return
        headers = {
            "accept": "application/json", 
            "content-type": "application/json", 
            "cookie": raw_cookie.strip(), 
            "user-agent": "Mozilla/5.0"
        }
        term = self.search_terms[0] if self.search_terms[0] else "bid"
        try: 
            tls_requests.post(
                "https://www.centralauctionhouse.com/DesktopModules/XModPro/Feed.aspx", 
                headers=headers, 
                data={"searchTerm": term}, 
                impersonate="chrome120", 
                timeout=12
            )
        except Exception: pass

    def intercept_vendorlink_xhr(self):
        if not self.toggles.get("vendorlink"): return
        raw_token = os.environ.get("VENDORLINK_TOKEN", "")
        if not raw_token: return
        
        auth_string = raw_token.strip() if raw_token.lower().startswith("bearer") else f"Bearer {raw_token.strip()}"
        headers = {
            "accept": "application/json", 
            "content-type": "application/json", 
            "authorization": auth_string, 
            "user-agent": "Mozilla/5.0"
        }
        term = self.search_terms[0] if self.search_terms[0] else "bid"
        try: 
            tls_requests.post(
                "https://api.myvendorlink.com/api/Search/Bids", 
                headers=headers, 
                json={"Keyword": term}, 
                impersonate="chrome120", 
                timeout=12
            )
        except Exception: pass

    def bypass_opengov_api(self):
        if not self.toggles.get("opengov"): return
        logging.info("--> [OpenGov] Executing Sweeps on Active Portals...")
        
        national_portals = [
            "orlando", "orangecountyfl", "citrusfl", "cityofgainesville", 
            "leoncounty", "austintexas", "seattle", "phoenix"
        ]
        
        headers = {
            "accept": "*/*", 
            "content-type": "application/json",
            "origin": "https://procurement.opengov.com", 
            "referer": "https://procurement.opengov.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        total_opengov = 0
        
        for portal in national_portals:
            for status in ["open", "evaluation", "closed"]:
                try:
                    url = f"https://api.procurement.opengov.com/api/v1/government/{portal}/project/public"
                    payload = {
                        "filters": [{"type": "status", "value": status}],
                        "quickSearchQuery": None,
                        "limit": 100,
                        "page": 0, 
                        "sortField": "title",
                        "sortDirection": "ASC"
                    }
                    
                    response = tls_requests.post(
                        url, 
                        headers=headers, 
                        json=payload, 
                        impersonate="chrome120", 
                        timeout=5
                    )
                    
                    if response.status_code == 200:
                        json_resp = response.json()
                        projects = json_resp.get('rows', [])
                            
                        for item in projects:
                            self.rfp_master_list.append({
                                "source": "OpenGov", 
                                "title": item.get('title', item.get('name', 'Unknown Title')),
                                "agency": portal.replace('cityof', 'City of ').title(),
                                "state": "US", 
                                "published_date": item.get('publishedAt', item.get('releaseDate', item.get('created_at', ''))),
                                "raw_metadata": item,
                                "url": f"https://procurement.opengov.com/portal/{portal}/projects/{item.get('id')}" if item.get('id') else ""
                            })
                            total_opengov += 1
                except Exception as e: 
                    logging.error(f"--> [DEBUG CRASH] Error hitting {portal}: {str(e)}")
                    
        logging.info(f"--> [OpenGov] National Sweep Complete. Bids collected: {total_opengov}")

    def execute_pipeline(self):
        self.intercept_demandstar_xhr()
        self.intercept_central_bidding_xhr()
        self.intercept_vendorlink_xhr()
        self.bypass_opengov_api()

class DurmotIntelligence:
    def __init__(self, deep_scrape=True, profile_name="govtech"):
        self.deep_scrape = deep_scrape
        self.profile = INDUSTRY_PROFILES.get(profile_name, INDUSTRY_PROFILES["govtech"])
        
        self.target_tech_stack = self.profile["tech_stack"]
        self.disqualify_keywords = self.profile["disqualify"]
        self.known_vendors = self.profile["vendors"]
        
        self.friction_heuristics = {
            r"\bsole source\b": 40, r"\bproprietary\b": 30, r"\bbrand name only\b": 35,
            r"\bincumbent\b": 20, r"\bmandatory pre-bid\b": 25, r"\bno substitutions\b": 30
        }

    def scrape_deep_text(self, url):
        if not self.deep_scrape or not url: return ""
        try:
            res = tls_requests.get(url, impersonate="chrome120", timeout=5)
            if res.status_code == 200:
                if url.lower().endswith('.pdf') or 'application/pdf' in res.headers.get('Content-Type', '').lower():
                    reader = PdfReader(io.BytesIO(res.content))
                    return " ".join([page.extract_text() for page in reader.pages[:8] if page.extract_text()]).lower()
                return BeautifulSoup(res.text, 'html.parser').get_text(separator=' ', strip=True).lower()
        except Exception: pass
        return ""

    def process_results(self, rfp_list, days=0):
        unique_rfps = {item['url']: item for item in rfp_list}.values()
        processed = []
        
        cutoff_date = datetime.now() - timedelta(days=days) if days > 0 else None

        for raw_rfp in unique_rfps:
            if cutoff_date and raw_rfp.get('published_date'):
                date_str = str(raw_rfp['published_date'])
                pub_date = None
                
                match_iso = re.search(r'(\d{4}-\d{2}-\d{2})', date_str)
                match_us = re.search(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', date_str)
                
                if match_iso:
                    try: pub_date = datetime.strptime(match_iso.group(1), "%Y-%m-%d")
                    except: pass
                elif match_us:
                    try: pub_date = datetime.strptime(f"{match_us.group(3)}-{match_us.group(1).zfill(2)}-{match_us.group(2).zfill(2)}", "%Y-%m-%d")
                    except: pass
                    
                if pub_date and pub_date < cutoff_date:
                    continue

            base_text = f"{raw_rfp['title']} {raw_rfp['agency']} {json.dumps(raw_rfp['raw_metadata'])}".lower()
            
            stack_matches = [kw.replace(r"\b", "").strip().upper() for kw in self.target_tech_stack if kw != r"." and re.search(kw, base_text)]
            if not stack_matches and self.target_tech_stack[0] != r".":
                if not any(re.search(kw, base_text) for kw in self.target_tech_stack):
                    continue

            search_text = f"{base_text} {self.scrape_deep_text(raw_rfp.get('url', ''))}"
            if any(re.search(pat, search_text) for pat in self.disqualify_keywords): continue

            friction_score = sum(pts for pat, pts in self.friction_heuristics.items() if re.search(pat, search_text))
            flags = [pat.replace(r"\b", "").strip().title() for pat, _ in self.friction_heuristics.items() if re.search(pat, search_text)]
            suspected = [v for v in self.known_vendors if v.lower() in search_text]

            processed.append({
                "agency": raw_rfp['agency'], "state": raw_rfp.get('state', 'US'),
                "title": raw_rfp['title'], "published_date": raw_rfp.get('published_date', 'Unknown'),
                "source": raw_rfp.get('source', 'Unknown'),
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
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY is missing. Get a free one at serper.dev"}
    
    # Hunting for the Genesis documents instead of just change orders
    query = f'"{vendor_name}" "{agency_name}" "Initial Award" OR "Notice of Intent" OR "Contract Award"'
    
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }
    
    # Using Google's 'tbs=sbd:1' (Sort by Date) to try to surface historical genesis documents
    payload = {
        "q": query,
        "tbs": "sbd:1"
    }
    
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json=payload, timeout=15)
        if res.status_code != 200: return {"error": f"Serper API HTTP {res.status_code}"}
        
        results = [
            {"title": i.get("title", "Unknown"), "link": i.get("link", ""), "snippet": i.get("snippet", "")}
            for i in res.json().get("organic", [])
            if vendor_name.lower() in i.get("snippet", "").lower()
        ]
        if not results: return {"status": f"No public genesis documents found for {vendor_name} at {agency_name}."}
        
        return {
            "agency_investigated": agency_name, 
            "vendor_investigated": vendor_name, 
            "genesis_risk": "HIGH" if len(results) >= 2 else "MODERATE", 
            "evidence": results[:5]
        }
    except Exception as e: return {"error": str(e)}

def query_opensecrets_api(vendor_name):
    api_key = os.environ.get("OPENSECRETS_API_KEY")
    if not api_key: return {"error": "OPENSECRETS_API_KEY environment variable is not set."}

    try:
        # 1. Grab the Organization ID
        org_search_url = f"http://www.opensecrets.org/api/?method=getOrgs&org={urllib.parse.quote(vendor_name)}&apikey={api_key}&output=json"
        res = tls_requests.get(org_search_url, timeout=10)
        if res.status_code != 200: return {"error": f"OpenSecrets API returned status {res.status_code}"}
            
        orgs = res.json().get('response', {}).get('organization', [])
        if not orgs: return {"status": f"No profile found for '{vendor_name}'."}
        if isinstance(orgs, dict): orgs = [orgs]

        org_id = orgs[0].get('@attributes', {}).get('orgid')
        org_name = orgs[0].get('@attributes', {}).get('orgname')
        if not org_id: return {"error": "Failed to extract Organization ID."}

        # 2. Time Machine Loop: Step backward by 2-year election cycles to find Patient Zero
        current_year = datetime.now().year
        start_cycle = current_year if current_year % 2 == 0 else current_year + 1
        
        genesis_year = "Unknown"
        latest_summary = None
        
        for cycle in range(start_cycle, 1996, -2):
            summary_url = f"http://www.opensecrets.org/api/?method=orgSummary&id={org_id}&cycle={cycle}&apikey={api_key}&output=json"
            summary_res = tls_requests.get(summary_url, timeout=10)
            
            if summary_res.status_code != 200: break
            
            try:
                summary = summary_res.json().get('response', {}).get('organization', {}).get('@attributes', {})
                total_receipts = float(summary.get('total', '0'))
            except:
                break
                
            if total_receipts > 0:
                genesis_year = str(cycle)
                if not latest_summary:
                    latest_summary = summary
            else:
                # Dropped to 0, the previous loop was the true genesis year
                break

        if not latest_summary:
            return {"status": f"No financial history found for '{vendor_name}'."}

        return {
            "vendor_searched": vendor_name, 
            "opensecrets_entity_name": org_name,
            "patient_zero_year": genesis_year,
            "latest_financial_totals": {
                "total_pac_contributions": f"${latest_summary.get('pac', '0')}",
                "total_individual_contributions": f"${latest_summary.get('indivs', '0')}",
                "total_soft_money": f"${latest_summary.get('soft', '0')}",
                "total_receipts": f"${latest_summary.get('total', '0')}"
            },
            "source_url": f"https://www.opensecrets.org/orgs/summary?id={org_id}"
        }
    except Exception as e: return {"error": f"API request failed: {str(e)}"}

# ==============================================================================
# SECTION 3: MCP EXPOSED TOOLS (FOR GOD MODE / CLAUDE DESKTOP)
# ==============================================================================

@mcp.tool
def get_all_nationwide_rfps(days: int = 0) -> str:
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline()
    results = DurmotIntelligence().process_results(pipeline.rfp_master_list, days=days)
    return json.dumps(results if results else {"status": "No RFPs found today."}, indent=2)

@mcp.tool
def run_friction_audit(keyword: str = "", days: int = 0) -> str:
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline()
    results = DurmotIntelligence().process_results(pipeline.rfp_master_list, days=days)
    clean_kw = keyword.strip().lower()
    if not clean_kw or clean_kw in ["all", "*"]: return json.dumps(results if results else {"status": "No active bids found."}, indent=2)
    filtered = [b for b in results if clean_kw in b['agency'].lower() or clean_kw in b['title'].lower()]
    return json.dumps(filtered if filtered else {"status": f"No bids matching '{keyword}'."}, indent=2)

@mcp.tool
def audit_vendor_lobbying(vendor_name: str) -> str:
    return json.dumps([query_opensecrets_api(vendor_name)], indent=2)

@mcp.tool
def audit_vendor_checkbook(agency_name: str, vendor_name: str) -> str:
    return json.dumps([query_municipal_checkbook(agency_name, vendor_name)], indent=2)

# ==============================================================================
# SECTION 4: WEB DASHBOARD & REST API ENDPOINTS
# ==============================================================================

mcp_app = mcp.http_app(path="/") 
app = FastAPI(title="Aelfstone Intelligence Engine", lifespan=mcp_app.lifespan)
app.mount("/mcp", mcp_app)

@app.get("/api/sweep")
def api_sweep(
    keyword: str = "", 
    state: str = "All", 
    type: str = "govtech", 
    days: int = 0, 
    ds: bool = True, 
    cb: bool = True, 
    vl: bool = True, 
    og: bool = True, 
    pdf: bool = True,
    auto_forensics: bool = True
):
    pipeline = RFPDataIngestion(toggles={"demandstar": ds, "centralbidding": cb, "vendorlink": vl, "opengov": og}, profile_name=type)
    pipeline.execute_pipeline()
    
    intelligence = DurmotIntelligence(deep_scrape=pdf, profile_name=type)
    results = intelligence.process_results(pipeline.rfp_master_list, days=days)
    
    clean_kw = keyword.strip().lower()
    if clean_kw and clean_kw not in ["all", "nationwide", "*"]:
        results = [b for b in results if clean_kw in b['agency'].lower() or clean_kw in b['title'].lower()]
        
    if state != "All":
        results = [b for b in results if b['state'].upper() == state.upper() or b['state'] == 'US']

    # AUTOMATIC FORENSICS TRIGGER
    if auto_forensics:
        for b in results:
            if b.get('friction_score', 0) > 0 and b.get('suspected_incumbent'):
                logging.info(f"--> [AUTO-FORENSICS] Triggered for {b['suspected_incumbent']} at {b['agency']}...")
                b['forensic_checkbook'] = query_municipal_checkbook(b['agency'], b['suspected_incumbent'])
                b['forensic_opensecrets'] = query_opensecrets_api(b['suspected_incumbent'])

    if not results:
        return {"status": "No targets found for this configuration."}
        
    return results

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
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 20px; }
            .panel { background-color: #0f172a; padding: 20px; border-radius: 4px; border: 1px solid #334155; }
            h3 { margin-top: 0; color: #38bdf8; font-size: 1.1em; border-bottom: 1px solid #1e293b; padding-bottom: 10px;}
            input[type="text"], select { background: #1e293b; border: 1px solid #475569; color: #f8fafc; padding: 10px; width: calc(100% - 22px); border-radius: 2px; margin-bottom: 10px; font-family: inherit; }
            select { width: 100%; cursor: pointer; }
            input[type="text"]:focus, select:focus { outline: none; border-color: #38bdf8; }
            input[type="checkbox"] { margin-right: 8px; accent-color: #38bdf8;}
            label { font-size: 0.9em; display: inline-block; margin-bottom: 8px; cursor: pointer; color: #cbd5e1;}
            button { background: #2563eb; border: none; color: white; padding: 12px; cursor: pointer; border-radius: 2px; font-weight: bold; width: 100%; text-transform: uppercase; letter-spacing: 1px; transition: background 0.2s; margin-top: 10px;}
            button:hover { background: #1d4ed8; }
            .output-panel { background-color: #0f172a; padding: 20px; border-radius: 4px; border: 1px solid #334155; min-height: 500px; max-height: 800px; overflow-y: auto;}
            pre { color: #10b981; white-space: pre-wrap; word-wrap: break-word; margin: 0; font-size: 0.9em; line-height: 1.4;}
            .status { margin-top: 10px; font-size: 0.85em; color: #fbbf24; display: none; text-align: center; }
            .controls-group { display: flex; gap: 10px; margin-bottom: 10px; }
        </style>
    </head>
    <body>
        <h1>⌖ AELFSTONE INTELLIGENCE PLATFORM</h1>
        
        <div class="grid">
            <div class="panel">
                <h3>1. MARKET DRAGNET (PHASE 1)</h3>
                
                <div class="controls-group">
                    <select id="sweepDays">
                        <option value="0">Timeframe: All Historical (100+ Days)</option>
                        <option value="30">Timeframe: Last 30 Days</option>
                        <option value="60">Timeframe: Last 60 Days</option>
                        <option value="90">Timeframe: Last 90 Days</option>
                        <option value="120">Timeframe: Last 120 Days</option>
                    </select>
                </div>

                <div class="controls-group">
                    <select id="sweepType">
                        <option value="govtech">Target: GovTech & Software</option>
                        <option value="construction">Target: Construction & Roofing</option>
                        <option value="all">Target: All Industries (Unfiltered)</option>
                    </select>
                </div>
                <div class="controls-group">
                    <select id="sweepState">
                        <option value="All">Location: Nationwide</option>
                        <option value="FL">Location: Florida</option>
                        <option value="TX">Location: Texas</option>
                        <option value="CA">Location: California</option>
                        <option value="NY">Location: New York</option>
                    </select>
                </div>
                <input type="text" id="sweepKw" placeholder="Optional Keyword (e.g., Orlando)">
                
                <div style="margin-top: 15px; border-top: 1px solid #1e293b; padding-top: 10px;">
                    <label><input type="checkbox" id="t_ds" checked> DemandStar (BYOT)</label><br>
                    <label><input type="checkbox" id="t_cb" checked> Central Bidding (BYOT)</label><br>
                    <label><input type="checkbox" id="t_vl" checked> VendorLink (BYOT)</label><br>
                    <label><input type="checkbox" id="t_og" checked> OpenGov (Historical / Free)</label><br>
                    <label><input type="checkbox" id="t_pdf" checked> Deep PDF Inspection</label><br>
                    <label><input type="checkbox" id="t_auto" checked> <strong>Auto-Trigger Forensics (API Heavy)</strong></label>
                </div>

                <button onclick="runSweep()">Initialize Dragnet</button>
                <div id="sweepStatus" class="status">Intercepting Network Nodes...</div>
            </div>

            <div style="display: flex; flex-direction: column; gap: 20px;">
                <div class="panel">
                    <h3>2. CHECKBOOK FORENSICS</h3>
                    <input type="text" id="cbAgency" placeholder="Agency (e.g., Orange County)">
                    <input type="text" id="cbVendor" placeholder="Vendor (e.g., Tyler)">
                    <button onclick="runCheckbook()">Run Diagnostic</button>
                    <div id="cbStatus" class="status">Querying Municipal Ledgers...</div>
                </div>

                <div class="panel">
                    <h3>3. OPENSECRETS AUDIT</h3>
                    <input type="text" id="osVendor" placeholder="Vendor (e.g., Oracle)">
                    <button onclick="runOpenSecrets()">Trace Capital</button>
                    <div id="osStatus" class="status">Tracing PAC Contributions...</div>
                </div>
            </div>
        </div>

        <div class="output-panel">
            <pre id="output">System Ready. Awaiting Command Sequence...</pre>
        </div>

        <script>
            async function runSweep() {
                document.getElementById('sweepStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Compiling intelligence. This may take 15-30 seconds depending on payload size...';
                
                const kw = encodeURIComponent(document.getElementById('sweepKw').value);
                const type = encodeURIComponent(document.getElementById('sweepType').value);
                const state = encodeURIComponent(document.getElementById('sweepState').value);
                const days = encodeURIComponent(document.getElementById('sweepDays').value);
                
                const ds = document.getElementById('t_ds').checked;
                const cb = document.getElementById('t_cb').checked;
                const vl = document.getElementById('t_vl').checked;
                const og = document.getElementById('t_og').checked;
                const pdf = document.getElementById('t_pdf').checked;
                const auto = document.getElementById('t_auto').checked;

                try {
                    const response = await fetch(`/api/sweep?keyword=${kw}&type=${type}&state=${state}&days=${days}&ds=${ds}&cb=${cb}&vl=${vl}&og=${og}&pdf=${pdf}&auto_forensics=${auto}`);
                    document.getElementById('output').innerText = JSON.stringify(await response.json(), null, 2);
                } catch (err) { document.getElementById('output').innerText = 'Error: ' + err; }
                document.getElementById('sweepStatus').style.display = 'none';
            }

            async function runCheckbook() {
                document.getElementById('cbStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Initializing Serper OSINT Protocol...';
                try {
                    const response = await fetch('/api/checkbook?agency=' + encodeURIComponent(document.getElementById('cbAgency').value) + '&vendor=' + encodeURIComponent(document.getElementById('cbVendor').value));
                    document.getElementById('output').innerText = JSON.stringify(await response.json(), null, 2);
                } catch (err) { document.getElementById('output').innerText = 'Error: ' + err; }
                document.getElementById('cbStatus').style.display = 'none';
            }

            async function runOpenSecrets() {
                document.getElementById('osStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Tracing Historical PAC Contributions...';
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
