import os
import re
import io
import json
import logging
import requests
import threading
from datetime import datetime
from dateutil import parser
from bs4 import BeautifulSoup
from pypdf import PdfReader
from flask import Flask, render_template_string, jsonify

# Configure logging for Railway/Durmot monitoring
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- FILE-BASED CACHE (Shared across Gunicorn workers) ---
CACHE_FILE = "durmot_cache.json"

def get_state():
    if not os.path.exists(CACHE_FILE):
        return {"status": "Awaiting initial scrape. Click 'Trigger Scraping Pipeline' to begin.", "bids": []}
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {"status": "Error reading cache.", "bids": []}

def set_state(status, bids=None):
    state = get_state()
    state['status'] = status
    if bids is not None:
        state['bids'] = bids
    with open(CACHE_FILE, 'w') as f:
        json.dump(state, f)

class RFPDataIngestion:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*'
        }
        self.rfp_master_list = []

    def intercept_demandstar_xhr(self):
        logging.info("Intercepting DemandStar XHR Feed (Unrestricted Firehose)...")
        url = "https://api.demandstar.com/contents/content/v1/bids/search"
        
        raw_token = os.environ.get("DEMANDSTAR_TOKEN", "")
        auth_token = re.sub(r'[\r\n]+', '', raw_token).strip()
        
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://www.demandstar.com",
            "referer": "https://www.demandstar.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
        }
        
        if auth_token:
            if not auth_token.lower().startswith("bearer ") and not auth_token.startswith("ey"):
                headers["cookie"] = auth_token
            else:
                headers["authorization"] = auth_token if auth_token.startswith("Bearer ") else f"Bearer {auth_token}"

        # FIXED PAYLOAD: Restored externalBids to bypass the empty subscription list
        payload = {
            "showBids": "externalBids",
            "includeExternalBids": "true",
            "bidStatus": "AC",
            "sortBy": "broadCastDate",
            "sortOrder": "DESC",
            "page": 1,
            "limit": 300
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code == 200:
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
                logging.info(f"DemandStar extraction successful. Pulled {len(bids)} raw nationwide bids.")
            else:
                logging.warning(f"DemandStar returned status code {response.status_code}")
        except Exception as e:
            logging.error(f"Failed to query DemandStar: {e}")

    def bypass_opengov_api(self):
        logging.info("Bypassing OpenGov Public APIs...")
        # Replaced dead 404 portals with known active Florida portals
        florida_portals = [
            "orlando", "citrusfl", "cityofgainesville", 
            "marionfl", "alachuacounty"
        ]
        
        headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": "https://procurement.opengov.com",
            "referer": "https://procurement.opengov.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
        }
        
        for portal in florida_portals:
            url = f"https://api.procurement.opengov.com/api/v1/government/{portal}/project/public"
            # FIXED PAYLOAD: Restored sort parameters so OpenGov stops returning empty arrays
            payload = {
                "filters": [{"type": "status", "value": "active"}],
                "limit": 100,
                "page": 1,
                "sortField": "proposalDeadline",
                "sortDirection": "DESC"
            }
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=10)
                if response.status_code == 200:
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
                    logging.info(f"OpenGov extraction for {portal}: Pulled {len(projects)} records.")
                else:
                    logging.warning(f"OpenGov {portal} returned {response.status_code}")
            except Exception as e:
                logging.warning(f"OpenGov portal {portal} query bypassed: {e}")

    def execute_pipeline(self):
        self.intercept_demandstar_xhr()
        self.bypass_opengov_api()
        logging.info(f"Pipeline complete. Ingested {len(self.rfp_master_list)} total raw records.")
        return json.dumps(self.rfp_master_list, indent=4)


class DurmotIntelligence:
    def __init__(self):
        self.disqualify_keywords = [
            # Hard Assets & Infrastructure
            r"\bwater treatment plant\b", r"\bnanofiltration\b", r"\blift station\b",
            r"\bpump station\b", r"\bwater main\b", r"\bsewer line\b", r"\bpipeline\b",
            r"\bvalve replacement\b", r"\bchemical feed\b", r"\bfiltration system\b",
            r"\bdirectional boring\b", r"\btrenching\b", r"\bconcrete\b", r"\basphalt\b",
            r"\bgenerator\b", r"\bmeters?\s+(?:replacement|installation|supply)\b",
            r"\bdrainage\b", r"\bwind mitigation\b", r"\bcabbage palm\b", r"\bremoval project\b",
            
            # Architecture, Engineering & Construction (AEC)
            r"\bdesign-build\b", r"\barchitecture\b", r"\bengineering services\b", 
            r"\bconstruction manager\b", r"\bgeneral contractor\b", r"\bgmp\b",
            r"\bhvac\b", r"\blighting project\b", r"\btelecommunications\b", r"\bantennas?\b",
            
            # Real Estate & Municipal Noise
            r"\bzoning\b", r"\bredevelopment\b", r"\breal property\b", r"\bucc sale\b",
            r"\bauction\b", r"\bforeclosure\b", r"\bbcc meeting\b", r"\bboard meeting\b",
            r"\bpublic hearing\b", r"\btax deed\b", r"\bfictitious name\b", r"\bsidewalk\b",
            r"\bpark\b", r"\bballfield\b", r"\broofing\b", r"\bpaving\b", r"\bpetition to vacate\b",
            r"\bdissolution of marriage\b", r"\btrim\s*-\s*budget\b", r"\btrim budget\b",
            r"\bbudget summary\b", r"\bvalue adjustment board\b", r"\bbanking services\b",
            r"\bcommunity development district\b", r"\bsports complex\b", r"\bstadium\b",
            r"\bsummons by publication\b", r"\bprobate\b", r"\bestate of\b", 
            r"\btermination of parental rights\b", r"\blost property\b",
            
            # Water Districts & State Agency Action Noise
            r"\benvironmental resource permit\b", r"\bswfwmd\b", r"\bsjrwmd\b",
            r"\bsfwmd\b", r"\bnwfwmd\b", r"\bsrwmd\b", r"\bwater management district\b",
            r"\bnotice of final agency action\b", r"\bnotice of intended agency action\b"
        ]
        
        self.target_tech_stack = [
            r"\benterprise resource planning\b", 
            r"\bcis\b", r"\bcustomer information system\b", r"\butility billing\b",
            r"\bmeter to cash\b", r"\bmdm\b", r"\bmeter data management\b",
            r"\bami\b", r"\bamr\b", r"\beam\b", r"\benterprise asset management\b",
            r"\bcrm\b", r"\btyler\b", r"\bincode\b", r"\bmunis\b", r"\bcayenta\b",
            r"\bcentralsquare\b", r"\bopengov\b", r"\boracle cc&b\b", r"\boracle c2m\b",
            r"\bsap utilities\b", r"\bpower bi\b", r"\bbusiness process re-?engineering\b", r"\bbpr\b",
            r"\bowner'?s representative\b", r"\bsoftware selection\b",
            r"\brfp development\b", r"\bimplementation management\b",
            r"\bstaff augmentation\b", r"\bqa oversight\b", r"\biv&v\b",
            r"\bawwa\b", r"\bg480\b"
        ]
        
        self.diversity_keywords = [
            r"\bmbwe\b", r"\bmbe\b", r"\bcbe\b", r"\bdbe\b", r"\bsbe\b",
            r"\bminority business\b", r"\bdisadvantaged business\b",
            r"\bsubcontracting goal\b"
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
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, headers=headers, timeout=8)
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
        base_search_text = f"{rfp['title']} {rfp['agency']} {json.dumps(rfp['raw_metadata'])}".lower()
        
        stack_matches = []
        for kw in self.target_tech_stack:
            if re.search(kw, base_search_text):
                stack_matches.append(kw.replace(r"\b", "").strip().upper())
                
        if not stack_matches:
            if not re.search(r'\b(software|system|erp|technology|billing|platform|cloud)\b', base_search_text):
                return None

        deep_text = self.scrape_deep_text(rfp.get('url', ''))
        search_text = f"{base_search_text} {deep_text}"
        
        for pattern in self.disqualify_keywords:
            if re.search(pattern, search_text):
                return None  
        
        friction_score = 0
        friction_flags = []
        
        if any(re.search(kw, search_text) for kw in self.diversity_keywords):
            friction_flags.append("MBWE/CBE Set-Aside")
        
        for pattern, points in self.friction_heuristics.items():
            if re.search(pattern, search_text):
                friction_score += points
                friction_flags.append(pattern.replace(r"\b", "").strip().title())
                
        temporal_score, temporal_flag = self.evaluate_temporal_anomaly(rfp)
        if temporal_flag:
            friction_score += temporal_score
            friction_flags.append(temporal_flag)
                
        for kw in self.target_tech_stack:
            if re.search(kw, search_text) and kw.replace(r"\b", "").strip().upper() not in stack_matches:
                stack_matches.append(kw.replace(r"\b", "").strip().upper())
                
        friction_score = min(friction_score, 100)
        
        rfp['friction_score'] = friction_score
        rfp['friction_flags'] = friction_flags
        rfp['raw_metadata']['durmot_stack_matches'] = list(set(stack_matches)) 
        return rfp

    def process_results(self, rfp_list):
        logging.info("Processing and filtering intelligence data in memory...")
        
        unique_rfps = {item['title']: item for item in rfp_list}.values()
        
        processed_bids = []
        dropped_count = 0
        for raw_rfp in unique_rfps:
            rfp = self.score_and_flag(raw_rfp)
            
            if not rfp:
                dropped_count += 1
                continue
                
            processed_bids.append({
                "agency": rfp['agency'],
                "title": rfp['title'],
                "friction_score": rfp['friction_score'],
                "friction_flags": rfp['friction_flags'],
                "tech_stack_hits": rfp['raw_metadata'].get('durmot_stack_matches', []),
                "url": rfp['url']
            })
            
        processed_bids.sort(key=lambda x: x['friction_score'])
        
        final_status = f"Last run successful. Qualified: {len(processed_bids)} RFPs | Disqualified Non-IT/Noise: {dropped_count} notices."
        set_state(final_status, processed_bids)
        logging.info(final_status)


# --- FLASK DASHBOARD SERVER ---
app = Flask(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Durmot Lead Engine - Open IT Procurement</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #0d1117; color: #c9d1d9; margin: 0; padding: 20px; }
        h1 { border-bottom: 1px solid #30363d; padding-bottom: 10px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; background-color: #161b22; border-radius: 6px; overflow: hidden; table-layout: fixed; }
        th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #30363d; word-wrap: break-word; }
        th { background-color: #21262d; font-weight: bold; }
        th:nth-child(1) { width: 15%; }
        th:nth-child(2) { width: 35%; }
        th:nth-child(3) { width: 10%; }
        th:nth-child(4) { width: 20%; }
        th:nth-child(5) { width: 10%; }
        th:nth-child(6) { width: 10%; }
        tr:hover { background-color: #30363d; }
        a { color: #58a6ff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .score { font-weight: bold; }
        .score-high { color: #f85149; } 
        .score-low { color: #3fb950; }  
        .badge { background-color: #b31d28; color: white; padding: 3px 8px; border-radius: 12px; font-size: 11px; margin-right: 4px; display: inline-block; margin-bottom: 3px; }
        .badge-tech { background-color: #1f6feb; }
        .badge-clean { background-color: #238636; }
        .btn { display: inline-block; background-color: #238636; color: white; padding: 10px 15px; text-decoration: none; border-radius: 6px; font-weight: bold; margin-bottom: 5px; cursor: pointer; border: none; font-size: 14px;}
        .btn:hover { background-color: #2ea043; }
        .status-box { background-color: #21262d; padding: 10px; border-radius: 6px; border-left: 4px solid #58a6ff; margin-bottom: 20px; font-size: 14px; }
    </style>
    <script>
        function startPolling() {
            const btn = document.getElementById('scrape-btn');
            const statusText = document.getElementById('status-text');
            
            btn.innerText = "Scraping in progress... Please wait.";
            btn.style.pointerEvents = "none";
            btn.style.opacity = "0.6";
            
            const pollInterval = setInterval(() => {
                fetch('/status')
                    .then(res => res.json())
                    .then(data => {
                        statusText.innerHTML = "<strong>Status:</strong> " + data.status;
                        if (!data.status.includes("Scraping in progress")) {
                            clearInterval(pollInterval);
                            btn.innerText = "Refresh Complete! Reloading Data...";
                            window.location.reload();
                        }
                    });
            }, 5000);
        }

        function triggerScrape() {
            fetch('/run-scraper')
                .then(response => response.json())
                .then(data => {
                    startPolling();
                });
        }

        window.onload = function() {
            const currentStatus = document.getElementById('status-text').innerText;
            if (currentStatus.includes("Scraping in progress")) {
                startPolling();
            }
        };
    </script>
</head>
<body>
    <h1>Durmot Lead Engine - Open IT Procurement</h1>
    <button id="scrape-btn" class="btn" onclick="triggerScrape()">Pull Latest SaaS & IT Leads</button>
    
    <div class="status-box" id="status-text">
        <strong>Status:</strong> {{ status }}
    </div>
    
    <table>
        <tr>
            <th>Agency</th>
            <th>RFP Title</th>
            <th>Friction Score</th>
            <th>Market Opportunity / Risk Flags</th>
            <th>Tech Stack Matches</th>
            <th>Link</th>
        </tr>
        {% for row in bids %}
        <tr>
            <td>{{ row.agency }}</td>
            <td>{{ row.title }}</td>
            <td class="score {% if row.friction_score == 0 %}score-low{% else %}score-high{% endif %}">{{ row.friction_score }}</td>
            <td>
                {% if row.friction_score == 0 %}
                    <span class="badge badge-clean">Prime Lead - Open Bid</span>
                {% endif %}
                {% for flag in row.friction_flags %}
                    <span class="badge" {% if flag == 'MBWE/CBE Set-Aside' %}style="background-color: #8957e5;"{% endif %}>{{ flag }}</span>
                {% endfor %}
            </td>
            <td>
                {% for tech in row.tech_stack_hits %}
                    <span class="badge badge-tech">{{ tech }}</span>
                {% endfor %}
            </td>
            <td><a href="{{ row.url }}" target="_blank">View RFP</a></td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""

@app.route('/')
def dashboard():
    state = get_state()
    return render_template_string(DASHBOARD_HTML, bids=state['bids'], status=state['status'])

@app.route('/run-scraper')
def trigger_scraper():
    state = get_state()
    if "Scraping in progress" in state['status']:
        return jsonify({"status": "already running"})
        
    set_state("Scraping in progress... Fetching OpenGov and DemandStar feeds.")
    
    def run_pipeline():
        try:
            pipeline = RFPDataIngestion()
            rfp_json_string = pipeline.execute_pipeline()
            master_rfp_list = json.loads(rfp_json_string)
            intelligence_engine = DurmotIntelligence()
            intelligence_engine.process_results(master_rfp_list)
        except Exception as e:
            set_state(f"Error during scraping: {e}")
            logging.error(f"Background scraping failed: {e}")
            
    thread = threading.Thread(target=run_pipeline)
    thread.start()
    return jsonify({"status": "started"})

@app.route('/status')
def get_status():
    state = get_state()
    return jsonify({"status": state['status']})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
