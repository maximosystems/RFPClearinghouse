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
        # self.intercept_demandstar_xhr() # Disabled until valid session cookie is provided
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
