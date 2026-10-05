import requests
import json
import logging
from datetime import datetime

# Configure logging for Railway/Durmot monitoring
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RFPDataIngestion:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*'
        }
        self.rfp_master_list = []

    def scrape_florida_clearinghouse(self, keyword="Information Technology"):
        """
        Target: FloridaPublicNotices.com AJAX/POST Search
        Replicates the exact XHR POST request triggered when a user searches the database.
        """
        logging.info("Starting Florida Clearinghouse Scrape...")
        
        # NOTE: Update this URL with the exact AJAX endpoint from your browser's network tab
        url = "https://floridapublicnotices.com/api/search" 
        
        payload = {
            "search_term": keyword,
            "category": "Bids",
            "date_range": "35_days"
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            data = response.json()
            
            for item in data.get('results', []):
                self.rfp_master_list.append({
                    "source": "FloridaPublicNotices",
                    "title": item.get('title', 'Unknown Title'),
                    "agency": item.get('county', 'Unknown County'),
                    "published_date": item.get('date', ''),
                    "raw_metadata": item,
                    "url": item.get('url', '')
                })
        except Exception as e:
            logging.error(f"Failed to scrape Florida Clearinghouse: {e}")

    def intercept_demandstar_xhr(self, state="FL"):
        """
        Target: DemandStar Backend Search API
        Bypasses the UI by hitting the unauthenticated JSON endpoint feeding their frontend.
        """
        logging.info("Intercepting DemandStar XHR Feed...")
        
        # NOTE: Right-click the DemandStar search XHR request in dev tools and paste the URL here
        url = f"https://network.demandstar.com/api/bids/search?state={state}&status=active"
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            
            for item in data.get('bids', []):
                self.rfp_master_list.append({
                    "source": "DemandStar",
                    "title": item.get('bidName', 'Unknown Title'),
                    "agency": item.get('agencyName', 'Unknown Agency'),
                    "published_date": item.get('broadcastDate', ''),
                    "raw_metadata": item,
                    "url": f"https://network.demandstar.com/bids/{item.get('id')}"
                })
        except Exception as e:
            logging.error(f"Failed to intercept DemandStar: {e}")

    def bypass_opengov_api(self):
        """
        Target: OpenGov / ProcureNow Public Vendor Portals
        Loops through unauthenticated JSON feeds for known Florida county portals.
        """
        logging.info("Bypassing OpenGov Public APIs...")
        
        # List of targeted Florida county OpenGov portal slugs
        florida_portals = ["marioncountyfl", "alachuacounty", "cityoforlando"] 
        
        for portal in florida_portals:
            # This is the standard unauthenticated public endpoint architecture for OpenGov
            url = f"https://procurement.opengov.com/api/public/projects?portal={portal}"
            
            try:
                response = requests.get(url, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                
                for item in data:
                    self.rfp_master_list.append({
                        "source": f"OpenGov-{portal}",
                        "title": item.get('title', 'Unknown Title'),
                        "agency": portal,
                        "published_date": item.get('publishedAt', ''),
                        "raw_metadata": item,
                        "url": f"https://procurement.opengov.com/portal/{portal}/projects/{item.get('id')}"
                    })
            except Exception as e:
                logging.error(f"Failed to fetch OpenGov portal {portal}: {e}")

    def execute_pipeline(self):
        """
        Executes all three ingestion methods and returns the normalized master list.
        """
        self.scrape_florida_clearinghouse()
        self.intercept_demandstar_xhr()
        self.bypass_opengov_api()
        
        logging.info(f"Pipeline complete. Ingested {len(self.rfp_master_list)} total RFPs.")
        return json.dumps(self.rfp_master_list, indent=4)

if __name__ == "__main__":
    # Test the ingestion script locally
    pipeline = RFPDataIngestion()
    rfp_json = pipeline.execute_pipeline()
    
    # Save the output to ensure the schema is exactly what Durmot expects
    with open("live_rfp_feed.json", "w") as f:
        f.write(rfp_json)
    
    print("Scraping complete. Results saved to live_rfp_feed.json.")
