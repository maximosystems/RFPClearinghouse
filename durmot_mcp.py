import sys
import os
import re
import io
import json
import sqlite3
import logging
import requests
import urllib.parse
from datetime import datetime
from dateutil import parser
from bs4 import BeautifulSoup
from pypdf import PdfReader

# FastMCP SDK
from fastmcp import FastMCP

# OPSEC CRITICAL: All logs must go to stderr. MCP uses stdout for JSON-RPC data transfer.
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr 
)

mcp = FastMCP("Durmot Lead & Forensic Engine")
DB_PATH = "durmot_forensic.db"

# ==============================================================================
# SECTION 1: GOVTECH SCRAPING & FRICTION ENGINE
# ==============================================================================

class RFPDataIngestion:
    def __init__(self):
        self.rfp_master_list = []

    def intercept_demandstar_xhr(self):
        logging.info("Intercepting Primary Nodes (Ghost Mode)...")
        url = "https://api.demandstar.com/contents/content/v1/bids/search"
        raw_token = os.environ.get("DEMANDSTAR_TOKEN", "")
        auth_token = re.sub(r'[\r\n]+', '', raw_token).strip()
        
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://www.demandstar.com",
            "referer": "https://www.demandstar.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        if auth_token:
            if not auth_token.lower().startswith("bearer ") and not auth_token.startswith("ey"):
                headers["cookie"] = auth_token
            else:
                headers["authorization"] = auth_token if auth_token.startswith("Bearer ") else f"Bearer {auth_token}"

        search_terms = ["software", "erp", "system", "technology", "billing", "implementation", "cloud"]
        
        for term in search_terms:
            payload = {
                "bidName": term,
                "showBids": "externalBids",
                "includeExternalBids": "true",
                "bidStatus": "AC",
                "sortBy": "broadCastDate",
                "sortOrder": "DESC",
                "page": 1,
                "limit": 50
            }
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=12)
                if response.status_code == 200:
                    data = response.json()
                    bids = data.get('result', []) if isinstance(data, dict) else data
                    for item in bids:
                        self.rfp_master_list.append({
                            "source": "Public-Notice-Network", 
                            "title": item.get('bidName', 'Unknown Title'),
                            "agency": item.get('agency', 'Unknown Agency'),
                            "published_date": item.get('broadCastDate', ''),
                            "raw_metadata": item,
                            "url": f"https://www.demandstar.com/app/bids/{item.get('bidId', '')}"
                        })
            except Exception:
                pass

    def bypass_opengov_api(self):
        logging.info("Intercepting Secondary Nodes...")
        florida_portals = ["orlando", "citrusfl", "cityofgainesville"]
        headers = {
            "accept": "application/json, text/plain, */*",
            "origin": "https://procurement.opengov.com",
            "user-agent": "Mozilla/5.0"
        }
        
        for portal in florida_portals:
            url = f"https://api.procurement.opengov.com/api/v1/government/{portal}/project/public"
            payload = {"filters": [{"type": "status", "value": "active"}], "limit": 50, "page": 1}
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    projects = data.get('data', []) if isinstance(data, dict) else data
                    for item in projects:
                        self.rfp_master_list.append({
                            "source": "Onvia-Synced-Node", 
                            "title": item.get('title', item.get('name', 'Unknown Title')),
                            "agency": portal.replace('cityof', 'City of ').title(),
                            "published_date": item.get('publishedAt', item.get('releaseDate', '')),
                            "raw_metadata": item,
                            "url": f"https://procurement.opengov.com/portal/{portal}/projects/{item.get('id')}" if item.get('id') else ""
                        })
            except Exception:
                pass

    def execute_pipeline(self):
        self.intercept_demandstar_xhr()
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
            r"\bsole source\b": 40,
            r"\bproprietary\b": 30,
            r"\bbrand name only\b": 35,
            r"\bincumbent\b": 20,
            r"\bmandatory pre-bid\b": 25,
            r"\bno substitutions\b": 30
        }

    def scrape_deep_text(self, url):
        if not url: return ""
        try:
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
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
                
        rfp['friction_score'] = min(friction_score, 100)
        rfp['friction_flags'] = friction_flags
        rfp['raw_metadata']['durmot_stack_matches'] = list(set(stack_matches)) 
        return rfp

    def process_results(self, rfp_list):
        unique_rfps = {item['url']: item for item in rfp_list}.values()
        processed = []
        for raw_rfp in unique_rfps:
            rfp = self.score_and_flag(raw_rfp)
            if not rfp: continue
            safe_query = urllib.parse.quote_plus(f"{rfp['agency']} {rfp['title']} RFP")
            processed.append({
                "agency": rfp['agency'],
                "title": rfp['title'],
                "friction_score": rfp['friction_score'],
                "friction_flags": rfp['friction_flags'],
                "tech_stack_hits": rfp['raw_metadata'].get('durmot_stack_matches', []),
                "url": f"https://www.google.com/search?q={safe_query}" 
            })
        processed.sort(key=lambda x: x['friction_score'])
        return processed

# ==============================================================================
# SECTION 2: FORENSIC TRIAD ENGINE (LOCAL SQL QUERIES)
# ==============================================================================

def query_db(query, params=()):
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

# ==============================================================================
# SECTION 3: MCP EXPOSED TOOLS
# ==============================================================================

@mcp.tool
def get_clean_leads() -> str:
    """
    Scrapes live municipal notices across Florida, applies the proprietary 
    Friction Score to filter out rigged bids, and returns zero-friction Prime Leads.
    """
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline()
    intelligence = DurmotIntelligence()
    results = intelligence.process_results(pipeline.rfp_master_list)
    prime = [b for b in results if b['friction_score'] == 0]
    return json.dumps(prime if prime else {"status": "No zero-friction Prime Leads found today."}, indent=2)

@mcp.tool
def run_friction_audit(agency_keyword: str) -> str:
    """
    Forensically audits active procurement notices for a specific agency keyword 
    (e.g., 'Orlando', 'Citrus') to expose incumbent traps, sole-source flags, and lock-in language.
    """
    pipeline = RFPDataIngestion()
    pipeline.execute_pipeline()
    intelligence = DurmotIntelligence()
    results = intelligence.process_results(pipeline.rfp_master_list)
    filtered = [b for b in results if agency_keyword.lower() in b['agency'].lower()]
    return json.dumps(filtered if filtered else {"status": f"No active bids found matching '{agency_keyword}'."}, indent=2)

@mcp.tool
def audit_vendor_pay_to_play(vendor_keyword: str) -> str:
    """
    Forensic Triad Tool: Cross-references Florida Sunbiz corporate ownership records 
    against state PAC/campaign finance contributions to detect kickback pathways and pay-to-play anomalies.
    """
    if not os.path.exists(DB_PATH):
        return json.dumps({
            "error": "Forensic database not detected. Run forensic_ingestion.py to populate state records."
        })

    # Search corporate registry for the vendor entity and its officers
    entity_sql = """
        SELECT document_number, entity_name, registered_agent_name, officer_name, status
        FROM florida_entities
        WHERE entity_name LIKE ? OR officer_name LIKE ?
        LIMIT 10
    """
    entities = query_db(entity_sql, (f"%{vendor_keyword}%", f"%{vendor_keyword}%"))

    if not entities:
        return json.dumps({"status": f"No corporate records found on Sunbiz matching '{vendor_keyword}'."})

    report = []
    for ent in entities:
        officer = ent.get("officer_name") or ent.get("registered_agent_name")
        donations = []
        if officer:
            # Cross-reference the executive against the campaign donations table
            donation_sql = """
                SELECT contributor_name, amount, date, recipient_pac, election_year
                FROM campaign_donations
                WHERE contributor_name LIKE ?
                ORDER BY amount DESC
                LIMIT 15
            """
            donations = query_db(donation_sql, (f"%{officer}%",))

        report.append({
            "entity_name": ent.get("entity_name"),
            "status": ent.get("status"),
            "key_officer": officer,
            "pac_contributions_detected": len(donations),
            "donations": donations
        })

    return json.dumps(report, indent=2)

if __name__ == "__main__":
    mcp.run()
