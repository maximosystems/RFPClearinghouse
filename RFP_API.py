import os
import re
import psycopg2
from psycopg2.extras import Json

class DurmotIntelligence:
    def __init__(self, db_url):
        self.db_url = db_url
        
        # Piggyback / Cooperative Purchasing Keywords
        self.piggyback_keywords = [
            r"\bpiggyback\b", r"\bcooperative purchasing\b", r"\bomnia\b", 
            r"\bsourcewell\b", r"\bnaspo\b", r"\bstate term contract\b", r"\bgsa\b"
        ]
        
        # Wired Bid / Restrictive Language Heuristics
        self.wired_heuristics = {
            r"\bsole source\b": 40,
            r"\bproprietary\b": 30,
            r"\bbrand name only\b": 35,
            r"\bincumbent\b": 20,
            r"\bmandatory pre-bid\b": 25,
            r"\bno substitutions\b": 30
        }

    def score_and_flag(self, rfp):
        """Analyzes the RFP text payload to generate intelligence scores."""
        # Dump the entire payload (title, agency, and raw metadata) into a single lowercase string for analysis
        search_text = f"{rfp['title']} {rfp['agency']} {json.dumps(rfp['raw_metadata'])}".lower()
        
        # 1. Piggyback Detection
        is_piggyback = any(re.search(kw, search_text) for kw in self.piggyback_keywords)
        
        # 2. Wired Bid Scoring
        wired_score = 0
        wired_flags = []
        
        for pattern, points in self.wired_heuristics.items():
            if re.search(pattern, search_text):
                wired_score += points
                wired_flags.append(pattern.replace(r"\b", "").strip().title())
                
        # Cap the score at 100
        wired_score = min(wired_score, 100)
        
        rfp['is_piggyback'] = is_piggyback
        rfp['wired_score'] = wired_score
        rfp['wired_flags'] = wired_flags
        return rfp

    def insert_to_postgres(self, rfp_list):
        """Scores the RFPs and inserts them into the Railway PostgreSQL database."""
        logging.info("Connecting to PostgreSQL to insert intelligence data...")
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            
            inserted_count = 0
            for raw_rfp in rfp_list:
                # Run the RFP through the intelligence scoring logic
                rfp = self.score_and_flag(raw_rfp)
                
                # Insert statement with ON CONFLICT to avoid duplicate ingestion
                insert_query = """
                    INSERT INTO durmot_rfp_intelligence 
                    (source, agency, title, published_date, url, is_piggyback, wired_score, wired_flags, raw_metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO NOTHING;
                """
                
                # Handle varying date formats by falling back to None if empty
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
            logging.info(f"Database insertion complete. Added {inserted_count} new RFPs.")
            
        except Exception as e:
            logging.error(f"PostgreSQL Insertion Failed: {e}")

# --- UPDATE YOUR MAIN EXECUTION BLOCK ---
if __name__ == "__main__":
    # 1. Run the existing ingestion pipeline
    pipeline = RFPDataIngestion()
    rfp_json_string = pipeline.execute_pipeline()
    master_rfp_list = json.loads(rfp_json_string)
    
    # 2. Run the intelligence and database insertion layer
    # Grab your Postgres connection string from Railway's environment variables
    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost:5432/durmot")
    
    intelligence_engine = DurmotIntelligence(DATABASE_URL)
    intelligence_engine.insert_to_postgres(master_rfp_list)
