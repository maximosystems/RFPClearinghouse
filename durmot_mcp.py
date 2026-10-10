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
# INDUSTRY & INTELLIGENCE PROFILES
# ==============================================================================
INDUSTRY_PROFILES = {
    "govtech": {
        "name": "GovTech & Software",
        "search_terms": ["software", "erp", "system", "technology", "billing", "cloud"],
        "tech_stack": [r"\bsoftware\b", r"\berp\b", r"\butility billing\b", r"\bcrm\b", r"\btyler\b", r"\bmunis\b", r"\bcloud\b", r"\bsaas\b"],
        "disqualify": [r"\bwater treatment\b", r"\bpump station\b", r"\bsewer\b", r"\bdirectional boring\b", r"\bconcrete\b", r"\basphalt\b", r"\broofing\b"],
        "vendors": ["Tyler Technologies", "CentralSquare", "Oracle", "Workday", "Munis", "CivicPlus", "Acta Solutions", "Axon", "Motorola Solutions", "Palantir"]
    },
    "texas_dirty": {
        "name": "Dirty Texas (DIR & Sole Source)",
        "search_terms": ["DIR contract", "sole source", "piggyback", "interlocal agreement", "exempt procurement"],
        "tech_stack": [r"\bdir\b", r"\bdir-cpo\b", r"\bsole source\b", r"\binterlocal\b", r"\bpiggyback\b", r"\bdepartment of information resources\b", r"\btyler\b"],
        "disqualify": [r"\bwater treatment\b", r"\broofing\b"],
        "vendors": ["Tyler Technologies", "Motorola Solutions", "Axon", "SHI Government Solutions", "Carahsoft", "Gartner"]
    },
    "asset_recovery": {
        "name": "Asset Recovery & Mineral Rights",
        "search_terms": ["excess proceeds", "surplus funds", "mineral deed", "royalty suspense", "unclaimed funds"],
        "tech_stack": [r"\bexcess proceeds\b", r"\bsurplus funds\b", r"\bmineral deed\b", r"\bdivision order\b", r"\broyalty\b", r"\bdelinquent tax\b"],
        "disqualify": [r"\bsoftware\b", r"\broofing\b"],
        "vendors": []
    },
    "oppo_shells": {
        "name": "Corporate Shells & PIR Reports",
        "search_terms": ["public information report", "annual report", "managing member", "director", "officer"],
        "tech_stack": [r"\bpublic information report\b", r"\bannual report\b", r"\bmanaging member\b", r"\bofficer\b", r"\bfranchise tax\b"],
        "disqualify": [],
        "vendors": []
    },
    "construction": {
        "name": "Construction & Roofing",
        "search_terms": ["roofing", "asphalt", "concrete", "paving", "construction", "hvac", "renovation"],
        "tech_stack": [r"\broofing\b", r"\basphalt\b", r"\bconcrete\b", r"\bpaving\b", r"\bhvac\b", r"\bconstruction\b", r"\btremco\b", r"\bgarland\b"],
        "disqualify": [r"\bsoftware\b", r"\berp\b", r"\bsaas\b", r"\bcloud\b", r"\bcybersecurity\b"],
        "vendors": ["Centimark", "Tremco", "Garland", "Cemex", "Vulcan Materials"]
    },
    "all": {
        "name": "All Unfiltered",
        "search_terms": [""],
        "tech_stack": [r"."],
        "disqualify": [],
        "vendors": []
    }
}

# ==============================================================================
# SECTION 1: INGESTION PIPELINE (PORTALS + SERPER GOOGLE OSINT)
# ==============================================================================

class RFPDataIngestion:
    def __init__(self, toggles=None, profile_name="govtech"):
        self.rfp_master_list = []
        self.profile_name = profile_name
        self.toggles = toggles or {"serper": True, "opengov": True, "demandstar": False, "centralbidding": False, "vendorlink": False}
        self.profile = INDUSTRY_PROFILES.get(profile_name, INDUSTRY_PROFILES["govtech"])
        self.search_terms = self.profile["search_terms"]

    def intercept_serper_google_dragnet(self, state="All", keyword=""):
        if not self.toggles.get("serper"): return
        api_key = os.environ.get("SERPER_API_KEY")
        if not api_key:
            logging.warning("--> [Serper Dragnet] SERPER_API_KEY missing. Skipping Google OSINT sweep.")
            return

        logging.info(f"--> [Serper Dragnet] Initiating Google OSINT Sweep for [{self.profile['name']}] State: [{state}]...")
        
        # State-specific authority domains
        if state == "TX":
            state_scope = "(site:*.tx.us OR site:texas.gov OR inurl:texas)"
        elif state == "FL":
            state_scope = "(site:*.fl.us OR site:myflorida.com OR inurl:florida)"
        elif state == "CA":
            state_scope = "(site:*.ca.gov OR inurl:california)"
        elif state == "NY":
            state_scope = "(site:*.ny.gov OR inurl:newyork)"
        else:
            state_scope = "(site:*.gov OR site:*.us OR site:procurement.opengov.com)"

        kw_clean = f'"{keyword}"' if keyword else ""
        dork_queries = []

        if self.profile_name == "asset_recovery":
            dork_queries = [
                f'{kw_clean} ("excess proceeds" OR "surplus funds" OR "unclaimed tax sale") filetype:pdf {state_scope}'.strip(),
                f'{kw_clean} ("royalty suspense" OR "mineral deed" OR "division order" OR "quiet title") {state_scope}'.strip()
            ]
        elif self.profile_name == "oppo_shells":
            jurisdiction = f"us_{state.lower()}" if state in ["TX", "FL", "CA", "NY"] else "us_tx"
            dork_queries = [
                f'{kw_clean} ("public information report" OR "annual report" OR "managing member") site:opencorporates.com/companies/{jurisdiction}'.strip(),
                f'{kw_clean} ("franchise tax" OR "officers" OR "directors") site:opencorporates.com'.strip()
            ]
        elif self.profile_name == "texas_dirty":
            dork_queries = [
                f'{kw_clean} ("DIR contract" OR "DIR-CPO" OR "sole source" OR "interlocal agreement") ("software" OR "services") site:*.tx.us'.strip(),
                f'{kw_clean} ("Notice of Intent to Award" OR "sole source" OR "proprietary") site:*.tx.us'.strip()
            ]
        else:
            terms_joined = " OR ".join([f'"{t}"' for t in self.search_terms if t])
            terms_grouped = f"({terms_joined})" if terms_joined else ""
            dork_queries = [
                f'{kw_clean} ("sole source" OR "notice of intent to award" OR "request for proposals" OR "piggyback") {terms_grouped} {state_scope}'.strip(),
                f'{kw_clean} ("brand name only" OR "proprietary" OR "cooperative purchasing") {terms_grouped} {state_scope}'.strip()
            ]

        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        total_serper = 0

        for q in dork_queries:
            if not q.strip(): continue
            payload = {"q": q, "tbs": "sbd:1", "num": 25}
            try:
                res = tls_requests.post("https://google.serper.dev/search", headers=headers, json=payload, timeout=12)
                if res.status_code == 200:
                    for item in res.json().get("organic", []):
                        url = item.get("link", "")
                        title = item.get("title", "Unknown Title")
                        snippet = item.get("snippet", "")
                        date_str = item.get("date", datetime.now().strftime("%Y-%m-%d"))

                        domain = urllib.parse.urlparse(url).netloc
                        clean_dom = re.sub(r'^(www\.|procurement\.|bids\.)', '', domain)
                        agency = clean_dom.split('.')[0].replace('-', ' ').title()

                        self.rfp_master_list.append({
                            "source": "Serper Google OSINT",
                            "title": title,
                            "agency": agency,
                            "state": state if state != "All" else "US",
                            "published_date": date_str,
                            "raw_metadata": {"snippet": snippet, "query": q, "url": url},
                            "url": url
                        })
                        total_serper += 1
            except Exception as e:
                logging.error(f"--> [Serper Dragnet Error] {str(e)}")

        logging.info(f"--> [Serper Dragnet] OSINT Ingestion Complete: {total_serper} nodes acquired.")

    def intercept_demandstar_xhr(self):
        if not self.toggles.get("demandstar"): return
        url = "https://api.demandstar.com/contents/content/v1/bids/search"
        raw_token = os.environ.get("DEMANDSTAR_TOKEN", "")
        auth_token = re.sub(r'[\r\n]+', '', raw_token).strip()
        if not auth_token: return
        headers = {"accept": "application/json", "content-type": "application/json", "user-agent": "Mozilla/5.0"}
        if not auth_token.lower().startswith("bearer ") and not auth_token.startswith("ey"): 
            headers["cookie"] = auth_token
        else: 
            headers["authorization"] = auth_token if auth_token.startswith("Bearer ") else f"Bearer {auth_token}"

        for term in self.search_terms:
            if not term: continue
            payload = {"bidName": term, "showBids": "externalBids", "includeExternalBids": "true", "sortBy": "broadCastDate", "sortOrder": "DESC", "page": 1, "limit": 25}
            try:
                response = tls_requests.post(url, headers=headers, json=payload, impersonate="chrome120", timeout=12)
                if response.status_code == 200:
                    for item in response.json().get('result', []):
                        self.rfp_master_list.append({
                            "source": "DemandStar",
                            "title": item.get('bidName', 'Unknown'),
                            "agency": item.get('agency', 'Unknown'),
                            "state": str(item.get('state') or 'US').strip().upper(),
                            "published_date": item.get('broadCastDate', ''),
                            "raw_metadata": item,
                            "url": f"https://www.demandstar.com/app/bids/{item.get('bidId', '')}"
                        })
            except Exception: pass

    def bypass_opengov_api(self):
        if not self.toggles.get("opengov"): return
        portals = ["orlando", "orangecountyfl", "citrusfl", "cityofgainesville", "leoncounty", "austintexas", "seattle", "phoenix"]
        headers = {
            "accept": "*/*", "content-type": "application/json", "origin": "https://procurement.opengov.com",
            "referer": "https://procurement.opengov.com/", "user-agent": "Mozilla/5.0"
        }
        for portal in portals:
            for status in ["open", "evaluation", "closed"]:
                try:
                    url = f"https://api.procurement.opengov.com/api/v1/government/{portal}/project/public"
                    payload = {"filters": [{"type": "status", "value": status}], "quickSearchQuery": None, "limit": 50, "page": 0, "sortField": "title", "sortDirection": "ASC"}
                    response = tls_requests.post(url, headers=headers, json=payload, impersonate="chrome120", timeout=5)
                    if response.status_code == 200:
                        for item in response.json().get('rows', []):
                            self.rfp_master_list.append({
                                "source": "OpenGov",
                                "title": item.get('title', item.get('name', 'Unknown Title')),
                                "agency": portal.replace('cityof', 'City of ').title(),
                                "state": "TX" if portal == "austintexas" else ("FL" if "fl" in portal or portal in ["orlando", "cityofgainesville", "leoncounty"] else "US"),
                                "published_date": item.get('publishedAt', item.get('releaseDate', item.get('created_at', ''))),
                                "raw_metadata": item,
                                "url": f"https://procurement.opengov.com/portal/{portal}/projects/{item.get('id')}" if item.get('id') else ""
                            })
                except Exception: pass

    def execute_pipeline(self, state="All", keyword=""):
        self.intercept_serper_google_dragnet(state=state, keyword=keyword)
        self.bypass_opengov_api()
        self.intercept_demandstar_xhr()

class DurmotIntelligence:
    def __init__(self, deep_scrape=True, profile_name="govtech"):
        self.deep_scrape = deep_scrape
        self.profile = INDUSTRY_PROFILES.get(profile_name, INDUSTRY_PROFILES["govtech"])
        self.target_tech_stack = self.profile["tech_stack"]
        self.disqualify_keywords = self.profile["disqualify"]
        self.known_vendors = self.profile["vendors"]
        
        self.friction_heuristics = {
            r"\bsole source\b": 40, r"\bproprietary\b": 30, r"\bbrand name only\b": 35,
            r"\bincumbent\b": 20, r"\bmandatory pre-bid\b": 25, r"\bno substitutions\b": 30,
            r"\bpiggyback\b": 35, r"\bcooperative purchasing\b": 35, r"\bsourcewell\b": 30,
            r"\bomnia partners\b": 30, r"\bnaspo\b": 30,
            r"\bdir contract\b": 35, r"\bdir-cpo\b": 35, r"\binterlocal agreement\b": 25,
            r"\bexcess proceeds\b": 40, r"\bsurplus funds\b": 40, r"\broyalty suspense\b": 45,
            r"\bpublic information report\b": 35,
            r"METADATA_GHOSTWRITER_FLAG": 50
        }

    def scrape_deep_text(self, url):
        if not self.deep_scrape or not url: return ""
        try:
            res = tls_requests.get(url, impersonate="chrome120", timeout=5)
            if res.status_code == 200:
                if url.lower().endswith('.pdf') or 'application/pdf' in res.headers.get('Content-Type', '').lower():
                    reader = PdfReader(io.BytesIO(res.content))
                    hidden_text = ""
                    meta = reader.metadata
                    if meta:
                        author_data = f"{meta.get('/Author', '')} {meta.get('/Creator', '')}".lower()
                        if any(v.lower() in author_data for v in self.known_vendors):
                            hidden_text = "METADATA_GHOSTWRITER_FLAG "
                    pdf_text = " ".join([page.extract_text() for page in reader.pages[:8] if page.extract_text()]).lower()
                    return hidden_text + pdf_text
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
                if pub_date and pub_date < cutoff_date: continue

            base_text = f"{raw_rfp['title']} {raw_rfp['agency']} {json.dumps(raw_rfp['raw_metadata'])}".lower()
            stack_matches = [kw.replace(r"\b", "").strip().upper() for kw in self.target_tech_stack if kw != r"." and re.search(kw, base_text)]
            if not stack_matches and self.target_tech_stack[0] != r".":
                if not any(re.search(kw, base_text) for kw in self.target_tech_stack): continue

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
# SECTION 2: FORENSIC TRIAD & OSINT ENGINES
# ==============================================================================

def query_municipal_checkbook(agency_name, vendor_name):
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY is missing."}
    query = (
        f'"{vendor_name}" "{agency_name}" '
        f'("Initial Award" OR "Notice of Intent" OR "Contract Award" OR "piggyback" OR "cooperative purchasing" OR "rider agreement") '
        f'-site:indeed.com -site:glassdoor.com -inurl:job -inurl:careers'
    )
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query, "tbs": "sbd:1"}, timeout=15)
        if res.status_code != 200: return {"error": f"Serper API HTTP {res.status_code}"}
        results = [
            {"title": i.get("title", "Unknown"), "link": i.get("link", ""), "snippet": i.get("snippet", "")}
            for i in res.json().get("organic", []) if vendor_name.lower() in i.get("snippet", "").lower()
        ]
        if not results: return {"status": f"No public genesis documents found for {vendor_name} at {agency_name}."}
        return {"agency_investigated": agency_name, "vendor_investigated": vendor_name, "genesis_risk": "HIGH" if len(results) >= 2 else "MODERATE", "evidence": results[:5]}
    except Exception as e: return {"error": str(e)}

def query_opensecrets_bypass(vendor_name):
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY is missing."}
    query = f'"{vendor_name}" contributions lobbying site:opensecrets.org/orgs/summary'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query}, timeout=15)
        if res.status_code != 200: return {"error": f"Serper HTTP {res.status_code}"}
        results = res.json().get("organic", [])
        if not results: return {"status": f"No OpenSecrets profile indexed for '{vendor_name}'."}
        return {"vendor_searched": vendor_name, "opensecrets_url": results[0].get("link", ""), "financial_snippet": results[0].get("snippet", ""), "status": "API Bypass Executed via Serper"}
    except Exception as e: return {"error": str(e)}

def query_revolving_door(agency_name, vendor_name):
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY is missing."}
    query = f'"{vendor_name}" "{agency_name}" site:linkedin.com/in'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query}, timeout=15)
        if res.status_code != 200: return {"error": f"Serper HTTP {res.status_code}"}
        results = []
        for i in res.json().get("organic", []):
            snippet = i.get("snippet", "")
            title = i.get("title", "").split("-")[0].strip()
            if vendor_name.lower() in snippet.lower() or agency_name.lower() in snippet.lower():
                results.append({"suspect_name": title, "linkedin_url": i.get("link", ""), "evidence_snippet": snippet})
        if not results: return {"status": f"No obvious revolving door profiles found for {vendor_name} at {agency_name}."}
        return {"agency_investigated": agency_name, "vendor_investigated": vendor_name, "revolving_door_risk": "HIGH" if len(results) >= 1 else "LOW", "profiles_found": results[:5]}
    except Exception as e: return {"error": str(e)}

def query_corporate_registry(target_name, state_code="tx"):
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY is missing."}
    query = f'"{target_name}" ("managing member" OR "director" OR "agent" OR "public information report" OR "officer") site:opencorporates.com/companies/us_{state_code.lower()}'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query}, timeout=15)
        if res.status_code != 200: return {"error": f"Serper HTTP {res.status_code}"}
        results = [
            {"company_name": i.get("title", "").split("::")[0].strip(), "url": i.get("link", ""), "evidence": i.get("snippet", "")}
            for i in res.json().get("organic", []) if target_name.lower() in i.get("snippet", "").lower()
        ]
        if not results: return {"status": f"No corporate filings or shell records found for '{target_name}' in {state_code.upper()}."}
        return {"target_investigated": target_name, "jurisdiction": state_code.upper(), "shell_risk": "HIGH" if len(results) >= 2 else "MODERATE", "filings": results[:5]}
    except Exception as e: return {"error": str(e)}

def query_real_estate_cad(target_name, state_code="tx"):
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY is missing."}
    query = f'"{target_name}" (inurl:cad OR inurl:appraisal OR "Property Search" OR "Deed of Trust" OR "Warranty Deed") (site:*.{state_code.lower()}.us OR site:texas.gov OR inurl:officialrecords)'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query}, timeout=15)
        if res.status_code != 200: return {"error": f"Serper HTTP {res.status_code}"}
        results = [
            {"property_record": i.get("title", ""), "url": i.get("link", ""), "evidence": i.get("snippet", "")}
            for i in res.json().get("organic", []) if target_name.lower() in i.get("snippet", "").lower()
        ]
        if not results: return {"status": f"No real estate records found for '{target_name}' in {state_code.upper()}."}
        return {"target_investigated": target_name, "jurisdiction": state_code.upper(), "real_estate_risk": "HIGH" if len(results) >= 2 else "MODERATE", "records": results[:5]}
    except Exception as e: return {"error": str(e)}

def query_mineral_surplus(target_or_county, state_code="tx"):
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY is missing."}
    query = f'"{target_or_county}" ("excess proceeds" OR "surplus funds" OR "mineral deed" OR "oil and gas lease" OR "division order" OR "royalty suspense") (site:*.{state_code.lower()}.us OR site:apps.rrc.texas.gov OR filetype:pdf)'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query}, timeout=15)
        if res.status_code != 200: return {"error": f"Serper HTTP {res.status_code}"}
        results = [
            {"record_title": i.get("title", ""), "url": i.get("link", ""), "evidence": i.get("snippet", "")}
            for i in res.json().get("organic", []) if target_or_county.lower() in i.get("snippet", "").lower()
        ]
        if not results: return {"status": f"No mineral rights or surplus funds found for '{target_or_county}' in {state_code.upper()}."}
        return {"target_investigated": target_or_county, "jurisdiction": state_code.upper(), "asset_recovery_potential": "HIGH" if len(results) >= 1 else "LOW", "records": results[:5]}
    except Exception as e: return {"error": str(e)}

# ==============================================================================
# SECTION 3: MCP EXPOSED TOOLS
# ==============================================================================

@mcp.tool
def get_all_nationwide_rfps(days: int = 0, target_type: str = "govtech", state: str = "All") -> str:
    pipeline = RFPDataIngestion(profile_name=target_type)
    pipeline.execute_pipeline(state=state)
    return json.dumps(DurmotIntelligence(profile_name=target_type).process_results(pipeline.rfp_master_list, days=days), indent=2)

@mcp.tool
def run_friction_audit(keyword: str = "", days: int = 0, target_type: str = "govtech", state: str = "All") -> str:
    pipeline = RFPDataIngestion(profile_name=target_type)
    pipeline.execute_pipeline(state=state, keyword=keyword)
    results = DurmotIntelligence(profile_name=target_type).process_results(pipeline.rfp_master_list, days=days)
    clean_kw = keyword.strip().lower()
    if not clean_kw or clean_kw in ["all", "*"]: return json.dumps(results, indent=2)
    filtered = [b for b in results if clean_kw in b['agency'].lower() or clean_kw in b['title'].lower()]
    return json.dumps(filtered if filtered else {"status": f"No bids matching '{keyword}'."}, indent=2)

@mcp.tool
def audit_vendor_lobbying(vendor_name: str) -> str:
    return json.dumps([query_opensecrets_bypass(vendor_name)], indent=2)

@mcp.tool
def audit_vendor_checkbook(agency_name: str, vendor_name: str) -> str:
    return json.dumps([query_municipal_checkbook(agency_name, vendor_name)], indent=2)

@mcp.tool
def audit_revolving_door(agency_name: str, vendor_name: str) -> str:
    return json.dumps([query_revolving_door(agency_name, vendor_name)], indent=2)

@mcp.tool
def audit_corporate_registry(target_name: str, state_code: str = "tx") -> str:
    return json.dumps([query_corporate_registry(target_name, state_code)], indent=2)

@mcp.tool
def audit_real_estate_holdings(target_name: str, state_code: str = "tx") -> str:
    return json.dumps([query_real_estate_cad(target_name, state_code)], indent=2)

@mcp.tool
def audit_mineral_and_surplus(target_or_county: str, state_code: str = "tx") -> str:
    return json.dumps([query_mineral_surplus(target_or_county, state_code)], indent=2)

# ==============================================================================
# SECTION 4: WEB DASHBOARD & REST API ENDPOINTS
# ==============================================================================

mcp_app = mcp.http_app(path="/") 
app = FastAPI(title="Aelfstone Intelligence Engine", lifespan=mcp_app.lifespan)
app.mount("/mcp", mcp_app)

@app.get("/api/sweep")
def api_sweep(
    keyword: str = "", state: str = "All", type: str = "govtech", days: int = 0, 
    serp: bool = True, ds: bool = False, cb: bool = False, vl: bool = False, og: bool = True, 
    pdf: bool = True, auto_forensics: bool = True
):
    pipeline = RFPDataIngestion(toggles={"serper": serp, "demandstar": ds, "centralbidding": cb, "vendorlink": vl, "opengov": og}, profile_name=type)
    pipeline.execute_pipeline(state=state, keyword=keyword)
    
    results = DurmotIntelligence(deep_scrape=pdf, profile_name=type).process_results(pipeline.rfp_master_list, days=days)
    
    clean_kw = keyword.strip().lower()
    if clean_kw and clean_kw not in ["all", "nationwide", "*"]:
        results = [b for b in results if clean_kw in b['agency'].lower() or clean_kw in b['title'].lower()]
        
    if state != "All":
        results = [b for b in results if b['state'].upper() == state.upper() or b['state'] == 'US']

    # Auto-forensics capped to top 3 targets to prevent HTTP timeouts
    if auto_forensics:
        count = 0
        for b in results:
            if count >= 3: break
            if (b.get('friction_score', 0) > 0 and b.get('suspected_incumbent')) or type in ['asset_recovery', 'oppo_shells']:
                target_entity = b.get('suspected_incumbent') or b.get('title')
                b['forensic_checkbook'] = query_municipal_checkbook(b['agency'], target_entity)
                b['forensic_opensecrets'] = query_opensecrets_bypass(target_entity)
                b['forensic_revolving_door'] = query_revolving_door(b['agency'], target_entity)
                b['forensic_corporate_registry'] = query_corporate_registry(target_entity, state if state != "All" else "tx")
                count += 1

    if not results: return {"status": "No targets found for this configuration."}
    return results

@app.get("/api/checkbook")
def api_checkbook(agency: str = "", vendor: str = ""):
    return query_municipal_checkbook(agency, vendor)

@app.get("/api/opensecrets")
def api_opensecrets(vendor: str = ""):
    return query_opensecrets_bypass(vendor)

@app.get("/api/revolvingdoor")
def api_revolvingdoor(agency: str = "", vendor: str = ""):
    return query_revolving_door(agency, vendor)

@app.get("/api/corporate")
def api_corporate(target: str = "", state: str = "tx"):
    return query_corporate_registry(target, state)

@app.get("/api/realestate")
def api_realestate(target: str = "", state: str = "tx"):
    return query_real_estate_cad(target, state)

@app.get("/api/minerals")
def api_minerals(target: str = "", state: str = "tx"):
    return query_mineral_surplus(target, state)

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
            input[type="checkbox"] { margin-right: 8px; accent-color: #38bdf8;}
            label { font-size: 0.88em; display: inline-block; margin-bottom: 8px; cursor: pointer; color: #cbd5e1;}
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
                <h3>1. MARKET DRAGNET (PHASE 1 - GOOGLE OSINT)</h3>
                
                <div class="controls-group">
                    <select id="sweepDays">
                        <option value="0">Timeframe: All Historical (100+ Days)</option>
                        <option value="30">Timeframe: Last 30 Days</option>
                        <option value="60">Timeframe: Last 60 Days</option>
                    </select>
                </div>
                <div class="controls-group">
                    <select id="sweepType">
                        <option value="govtech">Target: GovTech & Software</option>
                        <option value="texas_dirty">Target: Dirty Texas (DIR & Sole Source)</option>
                        <option value="asset_recovery">Target: Asset Recovery & Mineral Rights</option>
                        <option value="oppo_shells">Target: Corporate Shells & PIR Reports</option>
                        <option value="construction">Target: Construction & Roofing</option>
                        <option value="all">Target: All Industries (Unfiltered)</option>
                    </select>
                </div>
                <div class="controls-group">
                    <select id="sweepState">
                        <option value="All">Location: Nationwide</option>
                        <option value="TX">Location: Texas</option>
                        <option value="FL">Location: Florida</option>
                        <option value="CA">Location: California</option>
                        <option value="NY">Location: New York</option>
                    </select>
                </div>
                <input type="text" id="sweepKw" placeholder="Target / Vendor / County Keyword">
                
                <div style="margin-top: 15px; border-top: 1px solid #1e293b; padding-top: 10px;">
                    <label><input type="checkbox" id="t_serp" checked> <strong>Serper Google OSINT Dragnet</strong></label><br>
                    <label><input type="checkbox" id="t_og" checked> OpenGov API Ingestion</label><br>
                    <label><input type="checkbox" id="t_ds"> DemandStar (BYOT)</label><br>
                    <label><input type="checkbox" id="t_pdf" checked> Deep PDF Inspection</label><br>
                    <label><input type="checkbox" id="t_auto" checked> <strong>Auto-Trigger Forensics (Capped at 3)</strong></label>
                </div>

                <button onclick="runSweep()">Initialize Dragnet</button>
                <div id="sweepStatus" class="status">Sweeping Google OSINT Nodes...</div>
            </div>

            <div style="display: flex; flex-direction: column; gap: 20px;">
                <div class="panel">
                    <h3>2. CHECKBOOK & CONTRACT FORENSICS</h3>
                    <input type="text" id="cbAgency" placeholder="Agency (e.g., Orange County or Austin)">
                    <input type="text" id="cbVendor" placeholder="Vendor (e.g., Tyler Technologies)">
                    <button onclick="runCheckbook()">Run Diagnostic</button>
                    <div id="cbStatus" class="status">Querying Municipal Ledgers...</div>
                </div>

                <div class="panel">
                    <h3>3. CAMPAIGN FINANCE BYPASS</h3>
                    <input type="text" id="osVendor" placeholder="Vendor (e.g., Oracle or Tyler)">
                    <button onclick="runOpenSecrets()">Trace Capital</button>
                    <div id="osStatus" class="status">Executing Serper Bypass...</div>
                </div>

                <div class="panel">
                    <h3>4. REVOLVING DOOR TRACKER</h3>
                    <input type="text" id="rdAgency" placeholder="Agency (e.g., Austin or Travis County)">
                    <input type="text" id="rdVendor" placeholder="Vendor (e.g., Tyler Technologies)">
                    <button onclick="runRevolvingDoor()">Scan Personnel</button>
                    <div id="rdStatus" class="status">Cross-referencing LinkedIn records...</div>
                </div>

                <div class="panel">
                    <h3>5. CORPORATE SHELL & PIR AUDIT</h3>
                    <input type="text" id="corpTarget" placeholder="Target Individual or Shell Entity">
                    <input type="text" id="corpState" value="TX" placeholder="State Code (e.g., TX, FL)">
                    <button onclick="runCorporate()">Audit Annual Reports</button>
                    <div id="corpStatus" class="status">Dorking OpenCorporates & PIRs...</div>
                </div>

                <div class="panel">
                    <h3>6. REAL ESTATE & CAD ASSET TRACER</h3>
                    <input type="text" id="reTarget" placeholder="Target Individual or LLC">
                    <input type="text" id="reState" value="TX" placeholder="State Code (e.g., TX, FL)">
                    <button onclick="runRealEstate()">Trace Property Holdings</button>
                    <div id="reStatus" class="status">Dorking Appraisal Districts...</div>
                </div>

                <div class="panel">
                    <h3>7. MINERAL RIGHTS & SURPLUS RECOVERY</h3>
                    <input type="text" id="minTarget" placeholder="Target Name or County">
                    <input type="text" id="minState" value="TX" placeholder="State Code (e.g., TX)">
                    <button onclick="runMinerals()">Scan for Assets</button>
                    <div id="minStatus" class="status">Scraping RRC & County Ledgers...</div>
                </div>
            </div>
        </div>

        <div class="output-panel">
            <pre id="output">System Ready. Awaiting Command Sequence...</pre>
        </div>

        <script>
            async function runSweep() {
                document.getElementById('sweepStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Executing Dragnet sweep...';
                
                const kw = encodeURIComponent(document.getElementById('sweepKw').value);
                const type = encodeURIComponent(document.getElementById('sweepType').value);
                const state = encodeURIComponent(document.getElementById('sweepState').value);
                const days = encodeURIComponent(document.getElementById('sweepDays').value);
                
                const serp = document.getElementById('t_serp').checked;
                const og = document.getElementById('t_og').checked;
                const ds = document.getElementById('t_ds').checked;
                const pdf = document.getElementById('t_pdf').checked;
                const auto = document.getElementById('t_auto').checked;

                try {
                    const response = await fetch(`/api/sweep?keyword=${kw}&state=${state}&type=${type}&days=${days}&serp=${serp}&og=${og}&ds=${ds}&pdf=${pdf}&auto_forensics=${auto}`);
                    document.getElementById('output').innerText = JSON.stringify(await response.json(), null, 2);
                } catch (err) { document.getElementById('output').innerText = 'Error: ' + err; }
                document.getElementById('sweepStatus').style.display = 'none';
            }

            async function runCheckbook() {
                document.getElementById('cbStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Initializing Checkbook Forensic Audit...';
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

            async function runRevolvingDoor() {
                document.getElementById('rdStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Scanning LinkedIn databases...';
                try {
                    const response = await fetch('/api/revolvingdoor?agency=' + encodeURIComponent(document.getElementById('rdAgency').value) + '&vendor=' + encodeURIComponent(document.getElementById('rdVendor').value));
                    document.getElementById('output').innerText = JSON.stringify(await response.json(), null, 2);
                } catch (err) { document.getElementById('output').innerText = 'Error: ' + err; }
                document.getElementById('rdStatus').style.display = 'none';
            }

            async function runCorporate() {
                document.getElementById('corpStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Scanning Secretary of State PIR & Annual Reports...';
                try {
                    const response = await fetch('/api/corporate?target=' + encodeURIComponent(document.getElementById('corpTarget').value) + '&state=' + encodeURIComponent(document.getElementById('corpState').value));
                    document.getElementById('output').innerText = JSON.stringify(await response.json(), null, 2);
                } catch (err) { document.getElementById('output').innerText = 'Error: ' + err; }
                document.getElementById('corpStatus').style.display = 'none';
            }

            async function runRealEstate() {
                document.getElementById('reStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Scanning Appraisal Districts and Deed Records...';
                try {
                    const response = await fetch('/api/realestate?target=' + encodeURIComponent(document.getElementById('reTarget').value) + '&state=' + encodeURIComponent(document.getElementById('reState').value));
                    document.getElementById('output').innerText = JSON.stringify(await response.json(), null, 2);
                } catch (err) { document.getElementById('output').innerText = 'Error: ' + err; }
                document.getElementById('reStatus').style.display = 'none';
            }

            async function runMinerals() {
                document.getElementById('minStatus').style.display = 'block';
                document.getElementById('output').innerText = 'Scanning Railroad Commission and County Ledgers...';
                try {
                    const response = await fetch('/api/minerals?target=' + encodeURIComponent(document.getElementById('minTarget').value) + '&state=' + encodeURIComponent(document.getElementById('minState').value));
                    document.getElementById('output').innerText = JSON.stringify(await response.json(), null, 2);
                } catch (err) { document.getElementById('output').innerText = 'Error: ' + err; }
                document.getElementById('minStatus').style.display = 'none';
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
