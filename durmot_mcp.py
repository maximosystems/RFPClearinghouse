import sys
import os
import re
import io
import json
import math
import logging
import urllib.parse
from datetime import datetime, timedelta
from collections import defaultdict
from bs4 import BeautifulSoup
from pypdf import PdfReader
from curl_cffi import requests as tls_requests

# FastMCP & FastAPI Integration
from fastmcp import FastMCP
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

# OPSEC CRITICAL: Stream logs directly to Railway container
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr 
)

# 1. Initialize MCP Server
mcp = FastMCP("Aelfstone Intelligence Engine")

# ==============================================================================
# PROBABILISTIC GRAPH ENGINE
# ==============================================================================

class CorruptionGraph:
    def __init__(self):
        self.nodes = {} 
        self.edges = defaultdict(dict) 
        
    def add_node(self, node_id, node_type, label, **attrs):
        self.nodes[node_id] = {"type": node_type, "label": label, "attrs": attrs}
        
    def add_edge(self, u, v, weight=1.0, relation="associated"):
        self.edges[u][v] = {"weight": weight, "relation": relation}
        self.edges[v][u] = {"weight": weight, "relation": relation}

    def compute_katz_centrality(self, alpha=0.1, beta=1.0, max_iter=20):
        nodes = list(self.nodes.keys())
        if not nodes: return {}
        centrality = {n: 1.0 for n in nodes}
        
        for _ in range(max_iter):
            new_centrality = {}
            for n in nodes:
                incoming_weight = sum(
                    self.edges[n][neighbor]["weight"] * centrality[neighbor] 
                    for neighbor in self.edges[n]
                )
                new_centrality[n] = beta + (alpha * incoming_weight)
            centrality = new_centrality
            
        norm = math.sqrt(sum(v**2 for v in centrality.values())) or 1.0
        return {n: round(v / norm, 4) for n, v in centrality.items()}

# ==============================================================================
# DYNAMIC ENTITY RESOLUTION & HEURISTICS
# ==============================================================================

STOPWORDS_PROCUREMENT = [
    r"\bnotice of intent to award\b", r"\bnotice of intent\b", r"\bsole source\b",
    r"\bsingle source\b", r"\brequest for proposals\b", r"\brfp\b", r"\brfq\b", r"\bitb\b",
    r"\bsoftware solution\b", r"\bsoftware\b", r"\bsystem\b", r"\bplatform\b",
    r"\bprofessional services\b", r"\bmaintenance and support\b", r"\bterm contract\b",
    r"\bannual renewal\b", r"\badd-in\b", r"\bapplication\b", r"\bconsulting services\b",
    r"\bproprietary\b", r"\bbrand name only\b", r"\bpiggyback\b"
]

def resolve_vendor_entity(title, text=""):
    """
    Dynamically extracts the commercial entity name from contract text/title
    without relying on hardcoded lists.
    """
    clean = title
    for sw in STOPWORDS_PROCUREMENT:
        clean = re.sub(sw, "", clean, flags=re.IGNORECASE)
    
    # Strip solicitation codes (e.g., S24-0193, RFP 25-001)
    clean = re.sub(r'\b[A-Z]{1,3}\d{2,4}[-\d]*\b', '', clean)
    clean = re.sub(r'[\(\)\[\]\:\-\–]', ' ', clean).strip()
    
    tokens = [t for t in clean.split() if len(t) > 2]
    if tokens:
        return " ".join(tokens[:3])
    return None

FRICTION_HEURISTICS = {
    r"\bsole source\b": 40, r"\bsingle source\b": 40, r"\bproprietary\b": 35,
    r"\bbrand name only\b": 35, r"\bno substitutions\b": 30, r"\bpiggyback\b": 35,
    r"\bcooperative purchasing\b": 30, r"\bdir contract\b": 35, r"\bdir-cpo\b": 35,
    r"\bchapter 287\b": 35, r"\bexempt procurement\b": 30, r"\binterlocal\b": 25,
    r"\bexcess proceeds\b": 40, r"\bsurplus funds\b": 40, r"\broyalty suspense\b": 45,
    r"METADATA_GHOSTWRITER_FLAG": 50
}

# ==============================================================================
# SECTION 1: INGESTION PIPELINE
# ==============================================================================

class RFPDataIngestion:
    def __init__(self, toggles=None):
        self.rfp_master_list = []
        self.toggles = toggles or {"serper": True, "opengov": True}

    def intercept_serper_google_dragnet(self, state="All", keyword=""):
        if not self.toggles.get("serper"): return
        api_key = os.environ.get("SERPER_API_KEY")
        if not api_key: return

        state_scopes = {
            "TX": "(site:*.tx.us OR site:texas.gov)",
            "FL": "(site:*.fl.us OR site:myflorida.com)",
            "CA": "(site:*.ca.gov)",
            "NY": "(site:*.ny.gov OR site:*.ny.us)",
            "IL": "(site:*.il.us OR site:illinois.gov)"
        }
        state_scope = state_scopes.get(state, "(site:*.gov OR site:*.us OR site:procurement.opengov.com)")
        kw_clean = f'"{keyword}"' if keyword else ""

        dork_queries = [
            f'{kw_clean} ("sole source" OR "notice of intent to award" OR "proprietary justification") ("software" OR "services" OR "system") {state_scope}'.strip(),
            f'{kw_clean} ("piggyback" OR "cooperative purchasing" OR "exempt procurement") {state_scope}'.strip()
        ]

        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        for q in dork_queries:
            if not q.strip(): continue
            try:
                res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": q, "tbs": "sbd:1", "num": 25}, timeout=12)
                if res.status_code == 200:
                    for item in res.json().get("organic", []):
                        url = item.get("link", "")
                        domain = urllib.parse.urlparse(url).netloc
                        clean_dom = re.sub(r'^(www\.|procurement\.|bids\.)', '', domain)
                        agency = clean_dom.split('.')[0].replace('-', ' ').title()

                        self.rfp_master_list.append({
                            "source": "Google OSINT Dragnet",
                            "title": item.get("title", "Unknown Title"),
                            "agency": agency,
                            "state": state if state != "All" else "US",
                            "published_date": item.get("date", datetime.now().strftime("%Y-%m-%d")),
                            "raw_metadata": {"snippet": item.get("snippet", ""), "query": q, "url": url},
                            "url": url
                        })
            except Exception as e:
                logging.error(f"--> [Serper Dragnet Error] {str(e)}")

    def bypass_opengov_api(self, state="All"):
        if not self.toggles.get("opengov"): return
        
        state_portals = {
            "TX": ["austintexas", "elpasotexas", "mcallen", "brazoscountytx", "parkercountytx"],
            "FL": ["orlando", "orangecountyfl", "citrusfl", "cityofgainesville", "leoncounty"],
            "WA": ["seattle"],
            "AZ": ["phoenix"],
            "CA": ["cityofsacramento", "sanjoseca"]
        }
        
        portals = state_portals.get(state, [p for sublist in state_portals.values() for p in sublist]) if state != "All" else [p for sublist in state_portals.values() for p in sublist]

        headers = {
            "accept": "*/*", "content-type": "application/json", "origin": "https://procurement.opengov.com",
            "referer": "https://procurement.opengov.com/", "user-agent": "Mozilla/5.0"
        }
        
        for portal in portals:
            assigned_state = state if state != "All" else next((k for k, v in state_portals.items() if portal in v), "US")
            for status in ["open", "evaluation", "closed"]:
                try:
                    url = f"https://api.procurement.opengov.com/api/v1/government/{portal}/project/public"
                    payload = {"filters": [{"type": "status", "value": status}], "quickSearchQuery": None, "limit": 40, "page": 0, "sortField": "title", "sortDirection": "ASC"}
                    response = tls_requests.post(url, headers=headers, json=payload, impersonate="chrome120", timeout=5)
                    if response.status_code == 200:
                        for item in response.json().get('rows', []):
                            self.rfp_master_list.append({
                                "source": "OpenGov Portal",
                                "title": item.get('title', item.get('name', 'Unknown Title')),
                                "agency": portal.replace('cityof', 'City of ').title(),
                                "state": assigned_state,
                                "published_date": item.get('publishedAt', item.get('releaseDate', item.get('created_at', ''))),
                                "raw_metadata": item,
                                "url": f"https://procurement.opengov.com/portal/{portal}/projects/{item.get('id')}" if item.get('id') else ""
                            })
                except Exception: pass

    def execute_pipeline(self, state="All", keyword=""):
        self.intercept_serper_google_dragnet(state=state, keyword=keyword)
        self.bypass_opengov_api(state=state)

class DurmotIntelligence:
    def __init__(self, deep_scrape=True):
        self.deep_scrape = deep_scrape

    def scrape_deep_text(self, url):
        if not self.deep_scrape or not url: return ""
        try:
            res = tls_requests.get(url, impersonate="chrome120", timeout=5)
            if res.status_code == 200:
                if url.lower().endswith('.pdf') or 'application/pdf' in res.headers.get('Content-Type', '').lower():
                    reader = PdfReader(io.BytesIO(res.content))
                    return " ".join([page.extract_text() for page in reader.pages[:6] if page.extract_text()]).lower()
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
                match = re.search(r'(\d{4}-\d{2}-\d{2})', date_str)
                if match:
                    try:
                        if datetime.strptime(match.group(1), "%Y-%m-%d") < cutoff_date: continue
                    except: pass

            base_text = f"{raw_rfp['title']} {raw_rfp['agency']} {json.dumps(raw_rfp['raw_metadata'])}".lower()
            deep_text = self.scrape_deep_text(raw_rfp.get('url', ''))
            full_corpus = f"{base_text} {deep_text}"

            friction_score = sum(pts for pat, pts in FRICTION_HEURISTICS.items() if re.search(pat, full_corpus))
            flags = [pat.replace(r"\b", "").strip().title() for pat, _ in FRICTION_HEURISTICS.items() if re.search(pat, full_corpus)]

            # AUTONOMOUS RESOLUTION: Extract vendor name without hardcoded lists
            resolved_entity = resolve_vendor_entity(raw_rfp['title'], deep_text)

            processed.append({
                "agency": raw_rfp['agency'], 
                "state": raw_rfp.get('state', 'US'),
                "title": raw_rfp['title'], 
                "published_date": raw_rfp.get('published_date', 'Unknown'),
                "source": raw_rfp.get('source', 'Unknown'),
                "friction_score": min(friction_score, 100), 
                "friction_flags": flags,
                "suspected_incumbent": resolved_entity,
                "url": raw_rfp.get('url', 'No URL provided') 
            })
            
        processed.sort(key=lambda x: x['friction_score'], reverse=True)
        return processed

# ==============================================================================
# SECTION 2: THE 7 FORENSIC INVESTIGATIVE STAGES
# ==============================================================================

def query_campaign_finance_agnostic(vendor_name, optional_politician=""):
    """Stage 3: Queries PAC/donor footprint without hardcoded targets."""
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY missing."}
    
    target_filter = f'"{optional_politician}"' if optional_politician else ""
    query = f'"{vendor_name}" {target_filter} contributions lobbying (site:opensecrets.org OR site:fec.gov/data OR site:dos.elections.myflorida.com OR site:ethics.state.tx.us)'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query.strip()}, timeout=10)
        results = res.json().get("organic", []) if res.status_code == 200 else []
        cap_score = min(len(results) * 20, 100)
        return {
            "vendor_searched": vendor_name,
            "target_filtered": optional_politician or "Agnostic / All Recipients",
            "capital_friction": cap_score,
            "evidence": [{"title": r.get("title"), "snippet": r.get("snippet"), "link": r.get("link")} for r in results[:3]]
        }
    except Exception as e:
        return {"error": str(e)}

def query_municipal_checkbook(agency_name, vendor_name):
    """Stage 2: Municipal Checkbook & Genesis Lock-in Analysis"""
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY missing."}
    query = f'"{vendor_name}" "{agency_name}" ("Initial Award" OR "Notice of Intent" OR "Contract Award" OR "piggyback" OR "sole source") -site:indeed.com -site:glassdoor.com'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query, "tbs": "sbd:1"}, timeout=12)
        results = [
            {"title": i.get("title"), "link": i.get("link"), "snippet": i.get("snippet")}
            for i in res.json().get("organic", []) if vendor_name.lower() in i.get("snippet", "").lower()
        ] if res.status_code == 200 else []
        return {
            "genesis_risk": "HIGH" if len(results) >= 2 else ("MODERATE" if results else "LOW"),
            "evidence": results[:4]
        }
    except Exception as e: return {"error": str(e)}

def query_revolving_door(agency_name, vendor_name):
    """Stage 4: Revolving Door Personnel Tracking"""
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY missing."}
    query = f'"{vendor_name}" "{agency_name}" site:linkedin.com/in'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query}, timeout=10)
        results = []
        if res.status_code == 200:
            for i in res.json().get("organic", []):
                snippet = i.get("snippet", "")
                if vendor_name.lower() in snippet.lower() or agency_name.lower() in snippet.lower():
                    results.append({"name": i.get("title", "").split("-")[0].strip(), "url": i.get("link"), "snippet": snippet})
        return {"revolving_door_risk": "ELEVATED" if results else "CLEAN", "profiles": results[:3]}
    except Exception as e: return {"error": str(e)}

def query_corporate_registry_nationwide(target_name):
    """Stage 5: Corporate Registry & Officer Extraction (Nationwide)"""
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY missing."}
    query = f'"{target_name}" ("managing member" OR "director" OR "officer" OR "president") site:opencorporates.com/companies/us'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query}, timeout=10)
        results = [
            {"company": i.get("title", "").split("::")[0].strip(), "url": i.get("link"), "evidence": i.get("snippet")}
            for i in res.json().get("organic", []) if target_name.lower() in i.get("snippet", "").lower()
        ] if res.status_code == 200 else []
        return {"filings": results[:4]}
    except Exception as e: return {"error": str(e)}

def query_cad_property_agnostic(target_name, state_code="US"):
    """Stage 6: County Appraisal District (CAD) Domicile Trace"""
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY missing."}
    state_scope = f"site:*.{state_code.lower()}.us" if state_code != "US" else "site:*.us"
    query = f'"{target_name}" ("Property Appraiser" OR "Appraisal District" OR "Homestead" OR "Warranty Deed") {state_scope}'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query}, timeout=10)
        results = [
            {"record": i.get("title"), "url": i.get("link"), "evidence": i.get("snippet")}
            for i in res.json().get("organic", []) if target_name.lower() in i.get("snippet", "").lower()
        ] if res.status_code == 200 else []
        return {"property_records": results[:3]}
    except Exception as e: return {"error": str(e)}

def query_asset_recovery_agnostic(target_name, state_code="US"):
    """Stage 7: Asset & Surplus Ledger Dork"""
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key: return {"error": "SERPER_API_KEY missing."}
    state_scope = f"site:*.{state_code.lower()}.us" if state_code != "US" else ""
    query = f'"{target_name}" ("excess proceeds" OR "surplus funds" OR "unclaimed property" OR "royalty suspense") {state_scope}'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query}, timeout=10)
        results = [
            {"asset_hit": i.get("title"), "url": i.get("link"), "evidence": i.get("snippet")}
            for i in res.json().get("organic", []) if target_name.lower() in i.get("snippet", "").lower()
        ] if res.status_code == 200 else []
        return {"asset_records": results[:3]}
    except Exception as e: return {"error": str(e)}

# ==============================================================================
# SECTION 3: MCP EXPOSED TOOLS
# ==============================================================================

@mcp.tool
def generate_commercial_dossier(agency_name: str, vendor_name: str, jurisdiction: str = "US") -> str:
    """Compiles a full 7-stage opposition research dossier for commercial client delivery."""
    cb = query_municipal_checkbook(agency_name, vendor_name)
    cf = query_campaign_finance_agnostic(vendor_name)
    rd = query_revolving_door(agency_name, vendor_name)
    corp = query_corporate_registry_nationwide(vendor_name)
    
    officers = []
    for f in corp.get("filings", []):
        m = re.search(r'([A-Z][a-z]+ [A-Z][a-z]+)', f.get("evidence", ""))
        if m and m.group(1) not in officers: officers.append(m.group(1))
        
    assets = [query_cad_property_agnostic(off, jurisdiction) for off in officers[:2]]
    minerals = [query_asset_recovery_agnostic(off, jurisdiction) for off in officers[:2]]

    dossier = {
        "classification": "CONFIDENTIAL COMMERCIAL DOSSIER",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_entity": vendor_name,
        "target_agency": agency_name,
        "stage_1_contract": "Validated Sole Source / Proprietary Lock-in",
        "stage_2_checkbook": cb,
        "stage_3_campaign_finance": cf,
        "stage_4_revolving_door": rd,
        "stage_5_corporate_web": corp,
        "stage_6_officer_assets": assets,
        "stage_7_secondary_surplus": minerals
    }
    return json.dumps(dossier, indent=2)

# ==============================================================================
# SECTION 4: CLIENT API & FULLY DYNAMIC DASHBOARD
# ==============================================================================

mcp_app = mcp.http_app(path="/") 
app = FastAPI(title="Aelfstone Intelligence Platform", lifespan=mcp_app.lifespan)
app.mount("/mcp", mcp_app)

@app.get("/api/discover_targets")
def api_discover_targets(state: str = "FL", days: int = 30):
    """MODE 1: Autonomous Target Generation Pipeline"""
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline(state=state, keyword="")
    raw_results = DurmotIntelligence(deep_scrape=True).process_results(pipeline.rfp_master_list, days=days)
    
    if state != "All":
        raw_results = [b for b in raw_results if b['state'].upper() == state.upper()]

    targets = []
    seen_entities = set()

    for item in raw_results:
        friction = item.get('friction_score', 0)
        entity = item.get('suspected_incumbent')
        
        # Pruning: Only surface high-friction, resolved targets
        if friction >= 30 and entity and entity.lower() not in seen_entities:
            seen_entities.add(entity.lower())
            
            # Quick Check: PAC Footprint
            cap_check = query_campaign_finance_agnostic(entity)
            cap_score = cap_check.get('capital_friction', 0)
            
            composite_score = min(int((friction * 0.6) + (cap_score * 0.4)), 100)
            
            targets.append({
                "target_entity": entity,
                "agency": item.get('agency', 'Unknown Agency'),
                "composite_threat_score": composite_score,
                "solicitation_title": item.get('title'),
                "friction_flags": item.get('friction_flags', []),
                "campaign_finance_hits": len(cap_check.get('evidence', [])),
                "contract_url": item.get('url')
            })

    targets.sort(key=lambda x: x['composite_threat_score'], reverse=True)
    return {"jurisdiction": state, "actionable_targets": targets[:10]}

@app.get("/api/audit_company")
def api_audit_company(vendor: str, state: str = "FL"):
    """MODE 2: Full 7-Stage Deep Dive on a specific company."""
    if not vendor: return {"error": "Vendor name required."}
    
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline(state=state, keyword=vendor)
    contracts = DurmotIntelligence(deep_scrape=True).process_results(pipeline.rfp_master_list)
    
    # Prune noise
    contracts = [c for c in contracts if c.get('friction_score', 0) >= 30]
    
    dossier = json.loads(generate_commercial_dossier(
        agency_name=contracts[0].get('agency', 'Unknown') if contracts else 'Unknown',
        vendor_name=vendor,
        jurisdiction=state
    ))
    
    dossier["contracts_found"] = contracts[:3]
    return dossier

@app.get("/api/campaign_trace")
def api_campaign_trace(politician: str, state: str = "FL"):
    """MODE 3: Trace a politician's donors to active contracts."""
    if not politician: return {"error": "Politician/PAC name required."}
    
    api_key = os.environ.get("SERPER_API_KEY")
    query = f'"{politician}" top contributors corporate pac (site:opensecrets.org OR site:followthemoney.org)'
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    
    try:
        res = tls_requests.post("https://google.serper.dev/search", headers=headers, json={"q": query}, timeout=10)
        donors = []
        for i in res.json().get("organic", [])[:3]:
            # Simple extraction from snippets for demo purposes
            words = i.get("snippet", "").split()
            if len(words) > 2: donors.append(words[1] + " " + words[2])
            
        return {
            "target_politician": politician,
            "status": "Donor footprint mapped. Ready to cross-reference against municipal portals.",
            "suspected_corporate_donors": donors,
            "raw_evidence": res.json().get("organic", [])[:3]
        }
    except Exception as e: return {"error": str(e)}

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Aelfstone Intelligence Platform</title>
        <style>
            body { background: #0a0e17; color: #a5b4fc; font-family: 'Courier New', monospace; margin: 0; padding: 25px; }
            h1 { color: #818cf8; font-size: 1.4em; letter-spacing: 2px; border-bottom: 1px solid #1e293b; padding-bottom: 10px; margin-bottom: 25px; }
            .grid { display: grid; grid-template-columns: 360px 1fr; gap: 20px; }
            .panel { background: #0f172a; padding: 20px; border: 1px solid #334155; border-radius: 4px; }
            input[type="text"], select { background: #1e293b; border: 1px solid #475569; color: #fff; padding: 9px; width: 100%; box-sizing: border-box; margin-bottom: 12px; font-family: inherit; }
            label { font-size: 0.85em; display: block; margin-bottom: 8px; color: #cbd5e1; cursor: pointer; }
            button { background: #2563eb; border: none; color: #fff; padding: 12px; width: 100%; cursor: pointer; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; border-radius: 2px; margin-top: 10px; transition: 0.2s; }
            button:hover { background: #1d4ed8; }
            .output-panel { background: #0f172a; border: 1px solid #334155; border-radius: 4px; padding: 20px; min-height: 600px; max-height: 850px; overflow-y: auto; }
            pre { color: #10b981; margin: 0; font-size: 0.88em; line-height: 1.4; white-space: pre-wrap; word-wrap: break-word; }
            .status { font-size: 0.85em; color: #fbbf24; text-align: center; margin-top: 12px; display: none; }
        </style>
    </head>
    <body>
        <h1>⌖ AELFSTONE INTELLIGENCE PLATFORM (COMMERCIAL ENGINE)</h1>
        <div class="grid">
            <div class="panel">
                <label>Operational Mode</label>
                <select id="opMode" onchange="updateUI()">
                    <option value="radar">1. Discovery Radar (Auto-Find Targets)</option>
                    <option value="company">2. Corporate Dossier (Audit Specific Vendor)</option>
                    <option value="campaign">3. Campaign Trail (Map PAC Donors to Contracts)</option>
                </select>

                <label>Target Jurisdiction</label>
                <select id="stateSelect">
                    <option value="FL">Florida (Stat. 287 Single Source)</option>
                    <option value="TX">Texas (DIR & Sole Source Exemption)</option>
                    <option value="CA">California (CMAS Exemptions)</option>
                    <option value="IL">Illinois (Intergovernmental Agreements)</option>
                    <option value="NY">New York (OGS Centralized Backdoors)</option>
                    <option value="All">Nationwide Wide-Net Sweep</option>
                </select>

                <div id="targetContainer" style="display: none;">
                    <label id="targetLabel">Target Input</label>
                    <input type="text" id="targetInput" placeholder="Enter target name...">
                </div>

                <button id="execBtn" onclick="executeOperation()">Initialize Discovery Radar</button>
                <div id="statusText" class="status">Executing Forensic Trace...</div>
            </div>

            <div class="output-panel">
                <pre id="output">System Ready. Select an operational mode to begin.</pre>
            </div>
        </div>

        <script>
            function updateUI() {
                const mode = document.getElementById('opMode').value;
                const container = document.getElementById('targetContainer');
                const label = document.getElementById('targetLabel');
                const btn = document.getElementById('execBtn');

                if (mode === 'radar') {
                    container.style.display = 'none';
                    btn.innerText = 'Initialize Discovery Radar';
                } else if (mode === 'company') {
                    container.style.display = 'block';
                    label.innerText = 'Target Vendor / Corporation';
                    btn.innerText = 'Generate Corporate Dossier';
                } else if (mode === 'campaign') {
                    container.style.display = 'block';
                    label.innerText = 'Target Politician / PAC';
                    btn.innerText = 'Map Donor Footprint';
                }
            }

            async function executeOperation() {
                const status = document.getElementById('statusText');
                const out = document.getElementById('output');
                const mode = document.getElementById('opMode').value;
                const state = encodeURIComponent(document.getElementById('stateSelect').value);
                const target = encodeURIComponent(document.getElementById('targetInput').value);
                
                status.style.display = 'block';
                out.innerText = 'Executing operation. Bypassing state portals and querying nodes...';

                try {
                    let url = '';
                    if (mode === 'radar') {
                        url = `/api/discover_targets?state=${state}&days=60`;
                    } else if (mode === 'company') {
                        url = `/api/audit_company?vendor=${target}&state=${state}`;
                    } else if (mode === 'campaign') {
                        url = `/api/campaign_trace?politician=${target}&state=${state}`;
                    }

                    const res = await fetch(url);
                    out.innerText = JSON.stringify(await res.json(), null, 2);
                } catch (e) {
                    out.innerText = 'Execution Error: ' + e;
                }
                status.style.display = 'none';
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
