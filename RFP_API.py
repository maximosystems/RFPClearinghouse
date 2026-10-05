import os
import re
import json
import logging
import requests
import psycopg2
from psycopg2.extras import Json
from datetime import datetime

# Configure logging for Railway/Durmot monitoring
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RFPDataIngestion:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*'
        }
        self.rfp_master_list = []

    def scrape_florida_clearinghouse(self, keyword="Information technology"):
        logging.info("Starting Florida Clearinghouse Scrape...")
        url = "https://floridapublicnotices.com/" 
        headers = {
            "accept": "application/hal+json",
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
        }
        payload = {
            "counties": [],
            "date-range--end-date": None,
            "date-range--start-date": None,
            "keywords": keyword,
            "offset": None,
            "paper": "-1",
            "sort-by": None,
            "limit": 100 
        }
        try:
            response = requests.post(url, headers=headers, json=payload)
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
                self.rfp_master_list.append({
                    "source": "FloridaPublicNotices",
                    "title": item.get('title', item.get('notice_title', 'Unknown Title')),
                    "agency": item.get('county', 'Unknown County'),
                    "published_date": item.get('date', item.get('publish_date', '')),
                    "raw_metadata": item,
                    "url": f"https://floridapublicnotices.com/notice/{item.get('id', '')}" if item.get('id') else ''
                })
            logging.info(f"Florida Clearinghouse extraction successful. Found {len(notices)} notices.")
        except Exception as e:
            logging.error(f"Failed to scrape Florida Clearinghouse: {e}")

    def intercept_demandstar_xhr(self):
        logging.info("Intercepting DemandStar XHR Feed...")
        url = "https://api.demandstar.com/contents/content/v1/bids/search"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "cookie": "_gcl_au=1.1.1200877539.1791220009; _gid=GA1.2.1930483286.1791220009; amp_53320e=x2XnAzd9U-xg3vBfOidt-w...1k46gggi8.1k46ggi7q.0.0.0; amp_53320e_demandstar.com=x2XnAzd9U-xg3vBfOidt-w...1k46gggi8.1k46ggi9g.0.0.0; _ga=GA1.2.30132793.1791220009; DemandStarToken=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1cyI6IjE5NDk3NTMiLCJtaSI6IjIzNzc4MDIiLCJwbWlkIjoiMCIsImZuIjoiTWF4IiwibG4iOiJDYXN0YW5lZGEiLCJtcyI6IkFDIiwibXQiOiJTUyIsIm1ncnRkIjoiVHJ1ZSIsImxrZCI6IkZhbHNlIiwibG0iOiIwIiwidW4iOiJNYXhDYXN0YW5lZGFJSUlAZ21haWwuY29tIiwidXQiOiJEUyIsImVtbCI6Im1heGNhc3RhbmVkYWlpaUBnbWFpbC5jb20iLCJwcm1zIjoiIDIsIDMsIDE0LCAxNSIsIm1sIjoiMiw0IiwibWMiOiJUcnVlIiwiZm1pIjoiMCIsImxsIjoiMTEvOC8yMDI0IDQ6NDg6MzkgUE0iLCJtY2QiOiIyLzYvMjAxOSA0OjUzOjAwIFBNIiwiYWNkIjoiMTAvNS8yMDI2IDU6MTI6MTAgUE0iLCJkbiI6IiIsInB0IjoiQUciLCJ0bSI6ImxpZ2h0X0RTIiwiaWF0IjoiMTc5MTIyMDMzMCIsIm1ibCI6IkZhbHNlIiwianRpIjoiN2EyNWNiZTEtMDg2Yi00MmE1LThmNGItODIxN2IyY2MyYjI1IiwibmJmIjoxNzkxMjIwMzMwLCJleHAiOjE3OTEzMDY3MzAsImlzcyI6IkRlbWFuZHN0YXIgQ29ycG9yYXRpb24ifQ.pO8a3RkafaN4nlYH5S-JsT3Zfm3ql3rwVFnC_kStRfk; MEMBERID=2377802; __cf_bm=kqKHYt34heN1e6tNQu7jxUeZTIk_uWZLNWlY4ZXthwc-1791221976.0147386-1.0.1.1-Gt7Xn4lBJvVwksIoiVRWtgDYKU_eUGwINlQJZMD783Kpb_dLGMuQIVo6JGX5HSIOpx0y0MdQqGoUG_2aLvUANLRky2nLXEA49i4zPmHzqLh6hrDvAPPBHFLLlp.b6TdA; _ga_QLPM2XWL45=GS2.1.s1791220009$o1$g1$t1791222383$j57$l0$h0; _gat_UA-177609458-1=1",
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
            response = requests.post(url, headers=headers, json=payload)
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
                "sortField": "proposalDeadline
