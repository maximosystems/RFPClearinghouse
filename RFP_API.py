import os
import re
import json
import requests
from flask import Flask

app = Flask(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Durmot X-Ray Diagnostic</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #0d1117; color: #c9d1d9; margin: 0; padding: 20px; }
        .btn { display: inline-block; background-color: #238636; color: white; padding: 12px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; margin-bottom: 20px; cursor: pointer; border: none; font-size: 16px;}
        .btn:hover { background-color: #2ea043; }
        pre { background-color: #161b22; padding: 15px; border-radius: 6px; border-left: 4px solid #f85149; white-space: pre-wrap; word-wrap: break-word; font-size: 13px;}
    </style>
</head>
<body>
    <h1>API X-Ray Diagnostic</h1>
    <p>Click the button below to ping the servers and dump their exact raw responses.</p>
    <button class="btn" onclick="runXRay()">Fire X-Ray Ping</button>
    <pre id="output">Waiting for ping...</pre>

    <script>
        function runXRay() {
            const out = document.getElementById('output');
            out.innerText = "Pinging servers... Please wait.";
            fetch('/xray')
                .then(res => res.text())
                .then(text => { out.innerText = text; })
                .catch(err => { out.innerText = "Fetch Error: " + err; });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    return DASHBOARD_HTML

@app.route('/xray')
def xray_ping():
    results = []

    # --- 1. DEMANDSTAR X-RAY ---
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

    ds_payload = {
        "bidName": "software",
        "showBids": "externalBids",
        "includeExternalBids": "true",
        "bidStatus": "AC",
        "sortBy": "broadCastDate",
        "sortOrder": "DESC",
        "page": 1,
        "limit": 10
    }
    
    try:
        res = requests.post(url, headers=headers, json=ds_payload, timeout=10)
        results.append(f"=== DEMANDSTAR ===\nSTATUS: {res.status_code}\nRESPONSE BODY:\n{res.text[:1500]}")
    except Exception as e:
        results.append(f"=== DEMANDSTAR ===\nERROR: {e}")

    # --- 2. OPENGOV X-RAY (Orlando) ---
    og_url = "https://api.procurement.opengov.com/api/v1/government/cityoforlando/project/public"
    og_headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0"
    }
    og_payload = {
        "filters": [{"type": "status", "value": "active"}],
        "limit": 10,
        "page": 1
    }
    
    try:
        res = requests.post(og_url, headers=og_headers, json=og_payload, timeout=10)
        results.append(f"=== OPENGOV (Orlando) ===\nSTATUS: {res.status_code}\nRESPONSE BODY:\n{res.text[:1500]}")
    except Exception as e:
        results.append(f"=== OPENGOV ===\nERROR: {e}")

    return "\n\n----------------------------------------\n\n".join(results)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
