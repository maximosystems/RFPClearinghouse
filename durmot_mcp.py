import sys
import os
import re
import io
import csv
import json
import logging
import random
import urllib.parse
from datetime import datetime
from dateutil import parser
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
# SECTION 2: LIVE FORENSIC TRIAD (API & SCRAPING ENGINE)
# ==============================================================================

def live_sunbiz_scrape(vendor_keyword):
    """Scrapes the live Florida Sunbiz directory, maintaining sessions to bypass Cloudflare."""
    logging.info(f"Initiating live Sunbiz scrape for: {vendor_keyword}")
    safe_keyword = urllib.parse.quote(vendor_keyword)
    search_url = f"https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults?inquiryType=EntityName&searchTerm={safe_keyword}"
    
    headers = {
        "Referer": "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName",
        "Accept-Language": "en-US,en;q=0.9"
    }

    try:
        # 1. Single stealth request. No warmup ping to avoid triggering speed limits.
        res = tls_requests.get(search_url, headers=headers, impersonate="chrome120", timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        detail_link = soup.find('a', href=re.compile(r'SearchResultDetail', re.IGNORECASE))
        
        if not detail_link:
            page_title = soup.title.string.strip() if soup.title else "No Title"
            logging.error(f"HTML Parse Failed. Sunbiz returned page title: {page_title}")
            return {"status": f"No active corporate records found on Sunbiz matching '{vendor_keyword}'."}
            
        entity_name = detail_link.text.strip()
        detail_url = f"https://search.sunbiz.org{detail_link['href']}"
        
        # 2. Second stealth request to the specific entity
        detail_res = tls_requests.get(detail_url, headers=headers, impersonate="chrome120", timeout=15)
        detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
        
        officers = []
        for div in detail_soup.find_all('div', class_='detailSection'):
            raw_text = div.get_text(separator='\n', strip=True).upper()
            
            if any(kw in raw_text for kw in ['OFFICER', 'DIRECTOR', 'MANAGER', 'MEMBER', 'AUTHORIZED', 'AGENT']):
                for line in raw_text.split('\n'):
                    line = line.strip()
                    if line and len(line.split()) >= 2 and not any(c.isdigit() for c in line):
                        ignore_words = {
                            'TITLE', 'NAME', 'ADDRESS', 'DETAIL', 'REGISTERED', 'AGENT', 
                            'FLORIDA', 'LLC', 'INC', 'ST', 'AVE', 'BLVD', 'RD', 'LN', 'WAY', 
                            'CT', 'DR', 'STE', 'APT', 'DEPT', 'RM', 'STREET', 'AVENUE', 
                            'BOULEVARD', 'ROAD', 'LANE', 'COURT', 'DRIVE', 'SUITE', 'ROOM', 
                            'UNIT', 'PO', 'BOX', 'CORP', 'CORPORATION', 'COMPANY', 'MANAGEMENT', 
                            'CITY', 'STATE', 'ZIP', 'CODE', 'VIEW', 'IMAGE', 'PDF', 'FORMAT',
                            'PLLC', 'LAW', 'PA', 'FIRM', 'GROUP', 'HOLDINGS', 'TRUST'
                        }
                        line_words = set(re.sub(r'[^A-Z\s]', '', line).split())
                        
                        if not line_words.intersection(ignore_words):
                            if line not in officers:
                                officers.append(line)
                                
        if not officers:
            officers = ["(Officers could not be parsed dynamically - Check Sunbiz URL)"]

        return {
            "entity_name": entity_name,
            "sunbiz_url": detail_url,
            "officers": officers[:5] 
        }
    except Exception as e:
        logging.error(f"Sunbiz extraction failed: {e}")
        return {"error": f"Live scraping failed: {str(e)}"}

def live_campaign_finance_query(search_term, is_entity=False):
    """Intercepts the live Division of Elections API to track political donations."""
    logging.info(f"Querying Division of Elections for: {search_term}")
    url = "https://dos.elections.myflorida.com/campaign-finance/contributions/"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    if is_entity:
        first_name = ""
        # Remove INC, LLC, etc from the search target so the DB finds it
        last_name = search_term.replace('INC.', '').replace('LLC', '').split(',')[0].strip()
    else:
        if ',' in search_term:
            last_name = search_term.split(',')[0].strip()
            first_name = search_term.split(',')[1].strip().split()[0]
        else:
            parts = search_term.split()
            if len(parts) < 2: return []
            first_name = parts[0]
            last_name = parts[-1]

    # CRITICAL FIX: The Florida Database uses ConFName and ConLName, not First_Name/Last_Name
    payload = {
        "election_year": "All",
        "search_type": "All",
        "format": "csv",
        "ConFName": first_name,
        "ConLName": last_name,
        "submit": "Submit"
    }
    
    donations = []
    try:
        res = tls_requests.post(url, data=payload, headers=headers, impersonate="chrome120", timeout=15)
        if res.status_code == 200:
            reader = csv.reader(io.StringIO(res.text))
            next(reader, None) # Skip the CSV header
            
            for row in reader:
                if len(row) < 10: continue
                amount_str = row[1].replace('$', '').replace(',', '').strip()
                amount = float(amount_str) if amount_str else 0.0
                donations.append({
                    "date": row[0].strip(),
                    "amount": amount,
                    "recipient_pac": row[9].strip(),
                    "election_year": row[10].strip() if len(row) > 10 else "N/A"
                })
    except Exception as e:
        logging.error(f"Elections API query failed for {search_term}: {e}")
        pass
    
    donations.sort(key=lambda x: x['amount'], reverse=True)
    return donations[:15]

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
    Forensic Triad Tool (Lightweight): Cross-references live Florida Sunbiz ownership records 
    against live state PAC/campaign finance contributions to detect pay-to-play anomalies.
    Requires no database.
    """
    sunbiz_data = live_sunbiz_scrape(vendor_keyword)
    
    if "status" in sunbiz_data or "error" in sunbiz_data:
        return json.dumps([sunbiz_data], indent=2)
    
    entity_name = sunbiz_data["entity_name"]
    officers = sunbiz_data["officers"]
    
    report = {
        "vendor_keyword_searched": vendor_keyword,
        "entity_found": entity_name,
        "sunbiz_source_url": sunbiz_data["sunbiz_url"],
        "officers_investigated": officers,
        "political_donations_found": []
    }
    
    # 1. Investigate the Corporate Entity Itself
    entity_donations = live_campaign_finance_query(entity_name, is_entity=True)
    if entity_donations:
        report["political_donations_found"].append({
            "target": f"{entity_name} (Corporate Account)",
            "total_contributions_found": len(entity_donations),
            "top_donations": entity_donations
        })
    
    # 2. Investigate the Human Officers
    for officer in officers:
        if "(Officers" in officer: continue
        donations = live_campaign_finance_query(officer, is_entity=False)
        if donations:
            report["political_donations_found"].append({
                "target": officer,
                "total_contributions_found": len(donations),
                "top_donations": donations
            })
            
    return json.dumps([report], indent=2)

if __name__ == "__main__":
    # Expose the server using Server-Sent Events (SSE) so clients can connect over the internet via Railway.
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport='sse', host='0.0.0.0', port=port)
