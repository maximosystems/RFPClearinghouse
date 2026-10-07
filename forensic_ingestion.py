import os
import ftplib
import requests
import io
import csv
import logging
import psycopg2
from psycopg2.extras import execute_batch

# Route logs to stderr to protect the future MCP stdio transport
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ForensicDataIngestion:
    def __init__(self):
        # Railway automatically injects DATABASE_URL into the environment
        self.db_url = os.environ.get("DATABASE_URL")
        if not self.db_url:
            logging.error("CRITICAL: DATABASE_URL not found. Are you running this inside Railway?")
            return
        self.setup_database()

    def get_connection(self):
        return psycopg2.connect(self.db_url)

    def setup_database(self):
        """Creates the Postgres schema for the Triad data."""
        logging.info("Initializing Postgres Forensic Triad Database...")
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Stream C: Sunbiz Entities Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS florida_entities (
                document_number VARCHAR(20) PRIMARY KEY,
                entity_name TEXT,
                registered_agent_name TEXT,
                officer_name TEXT,
                status TEXT
            )
        ''')
        
        # Stream B: Campaign Finance Table (Note the Postgres 'SERIAL' datatype)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS campaign_donations (
                id SERIAL PRIMARY KEY,
                contributor_name TEXT,
                amount NUMERIC,
                date TEXT,
                recipient_pac TEXT,
                election_year TEXT
            )
        ''')
        conn.commit()
        conn.close()
        logging.info("Postgres schema fully synced.")

    def ingest_sunbiz_ftp(self):
        """Streams the massive state corporate registry directly into Postgres without overloading RAM."""
        logging.info("Connecting to Florida Division of Corporations FTP...")
        ftp_host = "sftp.floridados.gov"
        
        try:
            ftp = ftplib.FTP(ftp_host)
            ftp.login("Public", "PubAccess1845!")
            ftp.cwd("/public/doc/corp/") 
            
            # The state routinely drops the active corporations list as a .txt file (e.g. cor20240101.txt)
            files = ftp.nlst()
            target_file = next((f for f in files if 'cor' in f.lower() and f.endswith('.txt')), None)
            
            if not target_file:
                logging.warning("Quarterly dump not found. Check state upload schedule.")
                ftp.quit()
                return

            logging.info(f"Target locked: {target_file}. Commencing streamed bulk extraction...")
            
            conn = self.get_connection()
            cursor = conn.cursor()
            
            insert_query = """
                INSERT INTO florida_entities (document_number, entity_name, registered_agent_name, officer_name, status)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (document_number) DO NOTHING
            """
            
            batch_data = []
            
            # Callback function to process the text file line-by-line as it downloads
            def process_line(line):
                # NOTE: Sunbiz text files are fixed-width. 
                # These slice indices are approximate based on standard FL corporate file definitions.
                # You may need to tune these slices according to the official state data dictionary.
                if len(line) < 100: return
                doc_num = line[0:12].strip()
                entity_name = line[12:204].strip()
                status = line[204:205].strip() 
                reg_agent = line[213:255].strip()
                officer = line[514:556].strip() # Often the first principal/officer block
                
                batch_data.append((doc_num, entity_name, reg_agent, officer, status))
                
                # Flush to Postgres every 5,000 records to keep RAM usage near zero
                if len(batch_data) >= 5000:
                    execute_batch(cursor, insert_query, batch_data)
                    conn.commit()
                    batch_data.clear()

            # Stream the file directly from the state FTP into the process_line callback
            ftp.retrlines(f'RETR {target_file}', process_line)
            
            # Catch any remaining records in the final batch
            if batch_data:
                execute_batch(cursor, insert_query, batch_data)
                conn.commit()

            conn.close()
            ftp.quit()
            logging.info("Statewide Corporate Registry successfully staged in Postgres.")
            
        except Exception as e:
            logging.error(f"Sunbiz Ingestion failed: {e}")

    def ingest_campaign_finance(self, election_year="2024"):
        """Intercepts the raw donation CSV and bulk-inserts it into Postgres."""
        logging.info(f"Targeting Campaign Finance Database for {election_year}...")
        url = "https://dos.elections.myflorida.com/campaign-finance/contributions/"
        
        payload = {
            "election_year": election_year,
            "search_type": "All",
            "format": "csv",
            "submit": "Submit"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://dos.elections.myflorida.com/campaign-finance/contributions/"
        }
        
        try:
            response = requests.post(url, data=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                logging.info("Payload intercepted. Parsing CSV stream...")
                
                csv_data = response.text
                reader = csv.reader(io.StringIO(csv_data))
                
                # Skip the state's header row
                next(reader, None) 
                
                conn = self.get_connection()
                cursor = conn.cursor()
                
                insert_query = """
                    INSERT INTO campaign_donations (contributor_name, amount, date, recipient_pac, election_year)
                    VALUES (%s, %s, %s, %s, %s)
                """
                
                batch_data = []
                for row in reader:
                    if len(row) < 10: continue
                    
                    # Columns vary by state export, typical index maps:
                    contributor = row[3].strip()
                    date = row[0].strip()
                    amount_str = row[1].replace('$', '').replace(',', '').strip()
                    amount = float(amount_str) if amount_str else 0.0
                    pac = row[9].strip() # Recipient Candidate/PAC
                    
                    batch_data.append((contributor, amount, date, pac, election_year))
                
                # Execute the bulk insert
                execute_batch(cursor, insert_query, batch_data)
                conn.commit()
                conn.close()
                
                logging.info(f"Ingested statewide political donations for {election_year}.")
            else:
                logging.error(f"Division of Elections returned status {response.status_code}")
        except Exception as e:
            logging.error(f"Campaign Finance Ingestion failed: {e}")

if __name__ == "__main__":
    engine = ForensicDataIngestion()
    if engine.db_url:
        # engine.ingest_sunbiz_ftp()
        engine.ingest_campaign_finance("2024")
