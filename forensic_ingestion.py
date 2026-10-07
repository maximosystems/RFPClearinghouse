import os
import paramiko
import requests
import io
import csv
import logging
import psycopg2
import zipfile
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
        
        # Stream B: Campaign Finance Table
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

    def ingest_sunbiz_sftp(self):
        """Streams the massive state corporate registry directly into Postgres using Secure FTP."""
        logging.info("Connecting to Florida Division of Corporations SFTP...")
        sftp_host = "sftp.floridados.gov"
        
        try:
            # Initialize Secure SSH Transport
            transport = paramiko.Transport((sftp_host, 22))
            transport.connect(username="Public", password="PubAccess1845!")
            sftp = paramiko.SFTPClient.from_transport(transport)
            
            # The state stores the full active registry as a ZIP file in the quarterly folder
            sftp.chdir('/Public/doc/quarterly/cor/') 
            target_file = 'cordata.zip'
            
            logging.info(f"Target locked: {target_file}. Downloading master archive to container...")
            local_zip = '/app/cordata.zip'
            
            # Download the zip file to the Railway container's ephemeral disk
            sftp.get(target_file, local_zip)
            
            conn = self.get_connection()
            cursor = conn.cursor()
            
            insert_query = """
                INSERT INTO florida_entities (document_number, entity_name, registered_agent_name, officer_name, status)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (document_number) DO NOTHING
            """
            
            batch_data = []
            
            # Extract and parse the split text files directly from the ZIP
            with zipfile.ZipFile(local_zip, 'r') as z:
                txt_files = [f for f in z.namelist() if f.endswith('.txt')]
                for txt_file in txt_files:
                    logging.info(f"Parsing extracted file: {txt_file}...")
                    with z.open(txt_file) as f:
                        for raw_line in f:
                            # Decode from binary to handle legacy character sets in state databases
                            line = raw_line.decode('latin-1', errors='ignore')
                            
                            if len(line) < 100: continue
                            doc_num = line[0:12].strip()
                            entity_name = line[12:204].strip()
                            status = line[204:205].strip() 
                            reg_agent = line[213:255].strip()
                            officer = line[514:556].strip() 
                            
                            batch_data.append((doc_num, entity_name, reg_agent, officer, status))
                            
                            if len(batch_data) >= 5000:
                                execute_batch(cursor, insert_query, batch_data)
                                conn.commit()
                                batch_data.clear()
            
            if batch_data:
                execute_batch(cursor, insert_query, batch_data)
                conn.commit()

            conn.close()
            sftp.close()
            transport.close()
            
            # Clean up the zip file to free up Railway server space
            if os.path.exists(local_zip):
                os.remove(local_zip)
                
            logging.info("Statewide Corporate Registry successfully staged in Postgres.")
            
        except Exception as e:
            logging.error(f"Sunbiz SFTP Ingestion failed: {e}")

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
                    
                    contributor = row[3].strip()
                    date = row[0].strip()
                    amount_str = row[1].replace('$', '').replace(',', '').strip()
                    amount = float(amount_str) if amount_str else 0.0
                    pac = row[9].strip()
                    
                    batch_data.append((contributor, amount, date, pac, election_year))
                
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
        engine.ingest_sunbiz_sftp()
        # engine.ingest_campaign_finance("2024")
