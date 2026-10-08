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

# OPSEC CRITICAL: All logs must go to stderr. 
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
                response = tls_requests.post(url, headers=headers, json=payload, impersonate="chrome120", timeout=12)
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
                response = tls_requests.post(url, headers=headers, json=payload, impersonate="chrome120", timeout=10)
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
# SECTION 2: FORENSIC TRIAD (OPENSECRETS & OPEN DATA OSINT)
# ==============================================================================

def query_opensecrets_api(vendor_name):
    """Hits the OpenSecrets REST API to find PAC and lobbying totals."""
    api_key = os.environ.get("OPENSECRETS_API_KEY")
    if not api_key:
        return {"error": "OPENSECRETS_API_KEY environment variable is not set. Please add it to your Railway config."}

    logging.info(f"Querying OpenSecrets API for: {vendor_name}")
    try:
        # Step 1: Find the Organization ID
        org_search_url = f"http://www.opensecrets.org/api/?method=getOrgs&org={urllib.parse.quote(vendor_name)}&apikey={api_key}&output=json"
        res = tls_requests.get(org_search_url, timeout=10)
        
        if res.status_code != 200:
            return {"error": f"OpenSecrets API returned status {res.status_code}"}
            
        data = res.json()
        orgs = data.get('response', {}).get('organization', [])
        
        if not orgs:
            return {"status": f"No OpenSecrets profile found for '{vendor_name}'."}

        # OpenSecrets returns a dict if there's only 1 match, or a list for multiple matches
        if isinstance(orgs, dict):
            orgs = [orgs]

        top_org = orgs[0].get('@attributes', {})
        org_id = top_org.get('orgid')
        org_name = top_org.get('orgname')

        if not org_id:
            return {"error": "Failed to extract Organization ID from OpenSecrets."}

        # Step 2: Retrieve the Organization Summary using the ID
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
        logging.error(f"OpenSecrets query failed: {e}")
        return {"error": f"API request failed: {str(e)}"}

def query_municipal_checkbook(agency_name, vendor_name):
    """
    OSINT checkbook scanner. Bypasses the need for 400 different city API endpoints 
    by querying indexed municipal records, council minutes, and PDF agendas for the 
    vendor name cross-referenced with 'Change Order' or 'Amendment'.
    """
    logging.info(f"Scanning open checkbooks and council minutes for: {vendor_name} at {agency_name}")
    
    # Construct a highly targeted dork query
    safe_query = urllib.parse.quote_plus(f'"{vendor_name}" "{agency_name}" "change order" OR "amendment" OR "contingency" OR "increase"')
    search_url = f"https://html.duckduckgo.com/html/?q={safe_query}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        res = tls_requests.get(search_url, headers=headers, impersonate="chrome120", timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        results = []
        for a in soup.find_all('a', class_='result__snippet'):
            snippet = a.text.strip()
            # Verify the snippet actually contains evidence of our trap
            if vendor_name.lower() in snippet.lower() and any(kw in snippet.lower() for kw in ['change order', 'amend', 'increase']):
                results.append(snippet)
                
        if not results:
            return {"status": f"No public change orders or budget increases found for {vendor_name} at {agency_name}."}
            
        # If we find 2 or more indexed change orders in the top results, it's a massive red flag.
        risk_flag = "HIGH (Multiple historical budget expansions detected)" if len(results) >= 2 else "MODERATE"
        
        return {
            "agency_investigated": agency_name,
            "vendor_investigated": vendor_name,
            "bleed_ratio_risk": risk_flag,
            "public_record_evidence": results[:5]
        }
    except Exception as e:
        logging.error(f"Checkbook OSINT query failed: {e}")
        return {"error": f"OSINT search failed: {str(e)}"}


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
def audit_vendor_lobbying(vendor_name: str) -> str:
    """
    Forensic Tool: Queries the OpenSecrets API to reveal a vendor's federal and state PAC 
    contributions, soft money, and lobbying expenditures to detect influence peddling.
    """
    report = query_opensecrets_api(vendor_name)
    return json.dumps([report], indent=2)

@mcp.tool
def audit_vendor_checkbook(agency_name: str, vendor_name: str) -> str:
    """
    Forensic Tool: Searches public municipal records, city council minutes, and transparency 
    portals to detect the 'Low-Bid / High-Change-Order' trap for a specific vendor at a specific agency.
    """
    report = query_municipal_checkbook(agency_name, vendor_name)
    return json.dumps([report], indent=2)

if __name__ == "__main__":
    # Expose the server using Server-Sent Events (SSE) so clients can connect over the internet via Railway.
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport='sse', host='0.0.0.0', port=port)
