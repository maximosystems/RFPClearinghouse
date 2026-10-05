import os
import re
import io
import json
import logging
import requests
import threading
import psycopg2
from psycopg2.extras import Json
from datetime import datetime
from dateutil import parser
from bs4 import BeautifulSoup
from pypdf import PdfReader
from flask import Flask, render_template_string

# Configure logging for Railway/Durmot monitoring
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RFPDataIngestion:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*'
        }
        self.rfp_master_list = []

    def scrape_florida_clearinghouse(self, keywords=None):
        if keywords is None:
            # Query targeted IT implementation terms instead of generic 'Information'
            keywords = ["software implementation", "system integration", "SaaS"]
            
        logging.info("Starting Florida Clearinghouse Scrape...")
        url = "https://floridapublicnotices.com/" 
        headers = {
            "accept": "application/hal+json",
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
        }

        for kw in keywords:
            payload = {
                "counties": [],
                "date-range--end-date": None,
                "date-range--start-date": None,
                "keywords": kw,
                "offset": None,
                "paper": "-1",
                "sort-by": None,
                "limit": 100 
            }
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                notices = []
                if isinstance(data, list):
                    notices = data
                elif isinstance(data, dict):
                    for key in ['results', 'data', 'notices', 'items']:
                        if key in data and isinstance(data[key], list):
                            notices = data[key]
                            break
                    if not notices and '_embedded' in data and isinstance(data['_embedded'], dict):
                        nested_lists = [v for v in data['_embedded'].values() if isinstance(v, list)]
                        if nested_lists:
                            notices = nested_lists[0]

                for item in notices:
                    agency = item.get('city', item.get('paper', 'Florida Public Notice'))
                    
                    # Clean and clamp lengthy public notice text to keep table layout tight
                    raw_title = item.get('notice', 'Unknown Title')
                    title = (raw_title[:120] + '...') if len(raw_title) > 120 else raw_title
                    
                    notice_date = item.get('date', '')
                    pdf_link = item.get('_links', {}).get('media', {}).get('href', '')
                    final_url = pdf_link if pdf_link else f"https://floridapublicnotices.com/notice/{item.get('id', '')}"
                    
                    self.rfp_master_list.append({
                        "source": "FloridaPublicNotices",
                        "title": title,
                        "agency": agency,
                        "published_date": notice_date,
                        "raw_metadata": item,
                        "url": final_url
                    })
                logging.info(f"Florida Clearinghouse extraction for '{kw}' complete. Found {len(notices)} notices.")
            except Exception as e:
                logging.error(f"Failed to scrape Florida Clearinghouse for '{kw}': {e}")

    def intercept_demandstar_xhr(self):
        logging.info("Intercepting DemandStar XHR Feed...")
        url = "https://api.demandstar.com/contents/content/v1/bids/search"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://www.demandstar.com",
            "referer": "https://www.demandstar.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
        }
        payload = {
            "showBids": "externalBids",
            "bidStatus": "AC",
            "includeExternalBids": "true",
            "sortBy": "broadCastDate",
            "sortOrder": "DESC",
            "commodityExists": True
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            bids = data.get('data', []) if isinstance(data, dict) else data
            
            for item in bids:
                self.rfp_master_list.append({
                    "source": "DemandStar",
                    "title": item.get('bidName', 'Unknown Title'),
                    "agency": item.get('agencyName', 'Unknown Agency'),
                    "published_date": item.get('broadCastDate', ''),
                    "raw_metadata": item,
                    "url": f"https://www.demandstar.com/app/bids/{item.get('id', '')}"
                })
            logging.info(f"DemandStar extraction successful. Found {len(bids)} bids.")
        except Exception as e:
            logging.error(f"Failed to intercept DemandStar: {e}")

    def bypass_opengov_api(self):
        logging.info("Bypassing OpenGov Public APIs...")
        florida_portals = ["orlando", "citrusfl"] 
        headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": "https://procurement.opengov.com",
            "referer": "https://procurement.opengov.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
        }
        for portal in florida_portals:
            url = f"https://api.procurement.opengov.com/api/v1/government/{portal}/project/public"
            payload = {
                "filters": [{"type": "status", "value": "all"}],
                "quickSearchQuery": None,
                "limit": 100,
                "page": 1,
                "sortField": "proposalDeadline",
                "sortDirection": "DESC"
            }
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=10)
                response.raise_for_status()
                data = response.json()
                projects = data.get('data', []) if isinstance(data, dict) else data
                
                for item in projects:
                    self.rfp_master_list.append({
                        "source": f"OpenGov-{portal}",
                        "title": item.get('title', item.get('name', 'Unknown Title')),
                        "agency": portal,
                        "published_date": item.get('publishedAt', item.get('releaseDate', '')),
                        "raw_metadata": item,
                        "url": f"https://procurement.opengov.com/portal/{portal}/projects/{item.get('id')}" if item.get('id') else f"https://procurement.opengov.com/portal/{portal}"
                    })
                logging.info(f"OpenGov extraction successful for {portal}. Found {len(projects)} bids.")
            except Exception as e:
                logging.error(f"Failed to fetch OpenGov portal {portal}: {e}")

    def execute_pipeline(self):
        self.scrape_florida_clearinghouse()
        self.intercept_demandstar_xhr()
        self.bypass_opengov_api()
        logging.info(f"Pipeline complete. Ingested {len(self.rfp_master_list)} total raw records.")
        return json.dumps(self.rfp_master_list, indent=4)


class DurmotIntelligence:
    def __init__(self, db_url):
        self.db_url = db_url
        
        # Disqualification: Exclude land, civil, auction, meeting, and zoning notices
        self.disqualify_keywords = [
            r"\bzoning\b", r"\bredevelopment\b", r"\breal property\b", 
            r"\bland development\b", r"\bucc sale\b", r"\bauction\b", 
            r"\bforeclosure\b", r"\bbcc meeting\b", r"\bboard meeting\b",
            r"\bpublic hearing\b", r"\bordinance\b", r"\bvariance\b",
            r"\bcomprehensive plan\b", r"\baffordable housing\b", r"\blien\b",
            r"\bconstruction\b", r"\broofing\b", r"\bpaving\b", r"\bdemolition\b"
        ]
        
        # Cooperative purchasing heuristics
        self.piggyback_keywords = [
            r"\bpiggyback\b", r"\bcooperative purchasing\b", r"\bomnia\b", 
            r"\bsourcewell\b", r"\bnaspo\b", r"\bstate term contract\b", r"\bgsa\b"
        ]
        
        # Rigged / wired heuristics
        self.wired_heuristics = {
            r"\bsole source\b": 40,
            r"\bproprietary\b": 30,
            r"\bbrand name only\b": 35,
            r"\bincumbent\b": 20,
            r"\bmandatory pre-bid\b": 25,
            r"\bno substitutions\b": 30
        }
        
        # Dedicated IT Implementation Stack
        self.target_tech_stack = [
            r"\bsoftware implementation\b", r"\bsaas implementation\b",
            r"\bsystem integration\b", r"\bsystems integration\b",
            r"\bpower bi\b", r"\bserverless\b", r"\btyler technologies\b",
            r"\bcjis\b", r"\bgoogle atom\b", r"\baws\b", r"\bdocker\b",
            r"\bpostgresql\b", r"\bpython\b", r"\beam\b", r"\bgis\b",
            r"\bsaas\b", r"\berp\b", r"\bcloud migration\b",
            r"\betl\b", r"\bapi integration\b"
        ]

    def scrape_deep_text(self, url):
        if not url: return ""
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                if url.lower().endswith('.pdf') or 'application/pdf' in res.headers.get('Content-Type', '').lower():
                    reader = PdfReader(io.BytesIO(res.content))
                    text = ""
                    for page in reader.pages[:15]:
                        extracted = page.extract_text()
                        if extracted:
                            text += extracted + " "
                    return text.lower()
                else:
                    soup = BeautifulSoup(res.text, 'html.parser')
                    return soup.get_text(separator=' ', strip=True).lower()
        except Exception:
            pass
        return ""

    def evaluate_temporal_anomaly(self, rfp):
        pub_date_str = rfp.get('published_date')
        deadline_str = None
        
        if "OpenGov" in rfp['source']:
            deadline_str = rfp['raw_metadata'].get('proposalDeadline')
        elif rfp['source'] == "DemandStar":
            deadline_str = rfp['raw_metadata'].get('dueDate')
            
        if pub_date_str and deadline_str:
            try:
                pub_date = parser.parse(pub_date_str).replace(tzinfo=None)
                deadline = parser.parse(deadline_str).replace(tzinfo=None)
                
                delta_days = (deadline - pub_date).days
                if 0 <= delta_days < 14:
                    return 35, f"Suspiciously Short Deadline ({delta_days} Days)"
            except Exception:
                pass
        return 0, None

    def score_and_flag(self, rfp):
        deep_text = self.scrape_deep_text(rfp.get('url', ''))
        search_text = f"{rfp['title']} {rfp['agency']} {json.dumps(rfp['raw_metadata'])} {deep_text}".lower()
        
        # Discard non-IT solicitations immediately
        for pattern in self.disqualify_keywords:
            if re.search(pattern, search_text):
                return None  # Dropped from ingestion
                
        is_piggyback = any(re.search(kw, search_text) for kw in self.piggyback_keywords)
        
        wired_score = 0
        wired_flags = []
        
        for pattern, points in self.wired_heuristics.items():
            if re.search(pattern, search_text):
                wired_score += points
                wired_flags.append(pattern.replace(r"\b", "").strip().title())
                
        temporal_score, temporal_flag = self.evaluate_temporal_anomaly(rfp)
        if temporal_flag:
            wired_score += temporal_score
            wired_flags.append(temporal_flag)
                
        stack_matches = []
        for kw in self.target_tech_stack:
            if re.search(kw, search_text):
                stack_matches.append(kw.replace(r"\b", "").strip().upper())
                
        wired_score = min(wired_score, 100)
        
        rfp['is_piggyback'] = is_piggyback
        rfp['wired_score'] = wired_score
        rfp['wired_flags'] = wired_flags
        rfp['raw_metadata']['durmot_stack_matches'] = list(set(stack_matches)) 
        return rfp

    def insert_to_postgres(self, rfp_list):
        logging.info("Connecting to PostgreSQL to filter and insert intelligence data...")
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            inserted_count = 0
            dropped_count = 0
            for raw_rfp in rfp_list:
                rfp = self.score_and_flag(raw_rfp)
                
                # Skip records dropped by the disqualification filter
                if not rfp:
                    dropped_count += 1
                    continue
                
                insert_query = """
                    INSERT INTO durmot_rfp_intelligence 
                    (source, agency, title, published_date, url, is_piggyback, wired_score, wired_flags, raw_metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO NOTHING;
                """
                
                pub_date = rfp['published_date'] if rfp['published_date'] else None
                
                cursor.execute(insert_query, (
                    rfp['source'],
                    rfp['agency'],
                    rfp['title'],
                    pub_date,
                    rfp['url'],
                    rfp['is_piggyback'],
                    rfp['wired_score'],
                    rfp['wired_flags'],
                    Json(rfp['raw_metadata'])
                ))
                
                if cursor.rowcount > 0:
                    inserted_count += 1
                    
            conn.commit()
            cursor.close()
            conn.close()
            logging.info(f"Database insertion complete. Qualified: {inserted_count} RFPs | Disqualified non-IT: {dropped_count} notices.")
            
        except Exception as e:
            logging.error(f"PostgreSQL Insertion Failed: {e}")


# --- FLASK DASHBOARD SERVER ---
app = Flask(__name__)
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost:5432/durmot")

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Durmot Intelligence Dashboard</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #0d1117; color: #c9d1d9; margin: 0; padding: 20px; }
        h1 { border-bottom: 1px solid #30363d; padding-bottom: 10px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; background-color: #161b22; border-radius: 6px; overflow: hidden; table-layout: fixed; }
        th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #30363d; word-wrap: break-word; }
        th { background-color: #21262d; font-weight: bold; }
        th:nth-child(1) { width: 15%; }
        th:nth-child(2) { width: 35%; }
        th:nth-child(3) { width: 10%; }
        th:nth-child(4) { width: 15%; }
        th:nth-child(5) { width: 15%; }
        th:nth-child(6) { width: 10%; }
        tr:hover { background-color: #30363d; }
        a { color: #58a6ff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .score { font-weight: bold; }
        .score-high { color: #f85149; }
        .score-low { color: #3fb950; }
        .badge { background-color: #b31d28; color: white; padding: 3px 8px; border-radius: 12px; font-size: 11px; margin-right: 4px; display: inline-block; margin-bottom: 3px; }
        .badge-tech { background-color: #1f6feb; }
        .btn { display: inline-block; background-color: #238636; color: white; padding: 10px 15px; text-decoration: none; border-radius: 6px; font-weight: bold; margin-bottom: 20px; }
        .btn:hover { background-color: #2ea043; }
    </style>
</head>
<body>
    <h1>Durmot Intelligence Engine - Enterprise IT & Implementations</h1>
    <a href="/run-scraper" class="btn">Trigger Scraping Pipeline</a>
    
    <table>
        <tr>
            <th>Agency</th>
            <th>RFP Title</th>
            <th>Wired Score</th>
            <th>Risk Flags</th>
            <th>Tech Stack Matches</th>
            <th>Link</th>
        </tr>
        {% for row in bids %}
        <tr>
            <td>{{ row[0] }}</td>
            <td>{{ row[1] }}</td>
            <td class="score {% if row[3] > 30 %}score-high{% else %}score-low{% endif %}">{{ row[3] }}</td>
            <td>
                {% for flag in row[4] %}
                    <span class="badge">{{ flag }}</span>
                {% endfor %}
            </td>
            <td>
                {% for tech in row[5] %}
                    <span class="badge badge-tech">{{ tech }}</span>
                {% endfor %}
            </td>
            <td><a href="{{ row[6] }}" target="_blank">View RFP</a></td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""

@app.route('/')
def dashboard():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        query = """
            SELECT 
                agency, 
                title, 
                is_piggyback,
                wired_score,
                COALESCE(wired_flags, '{}') AS wired_flags,
                COALESCE(raw_metadata->'durmot_stack_matches', '[]') AS tech_stack_hits,
                url
            FROM durmot_rfp_intelligence 
            ORDER BY wired_score DESC, ingested_at DESC
            LIMIT 200;
        """
        cursor.execute(query)
        bids = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template_string(DASHBOARD_HTML, bids=bids)
    except Exception as e:
        return f"<h3 style='color:red;'>Database Error: {e}</h3>"

@app.route('/run-scraper')
def trigger_scraper():
    def run_pipeline():
        try:
            pipeline = RFPDataIngestion()
            rfp_json_string = pipeline.execute_pipeline()
            master_rfp_list = json.loads(rfp_json_string)
            intelligence_engine = DurmotIntelligence(DATABASE_URL)
            intelligence_engine.insert_to_postgres(master_rfp_list)
        except Exception as e:
            logging.error(f"Background scraping failed: {e}")
            
    thread = threading.Thread(target=run_pipeline)
    thread.start()
    return "<h3>Pipeline triggered in the background! <a href='/'>Return to Dashboard</a></h3>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
