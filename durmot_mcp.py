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
        # NEW: The engine will actively hunt for these entities in the deep text
        self.known_vendors = [
            "Tyler Technologies", "CentralSquare", "Oracle", "Workday", 
            "OpenGov", "Munis", "CivicPlus", "Accela", "Superion"
        ]

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

        # NEW: Extract the suspected incumbent from the text
        suspected_vendors = [vendor for vendor in self.known_vendors if vendor.lower() in search_text]
                
        rfp['friction_score'] = min(friction_score, 100)
        rfp['friction_flags'] = friction_flags
        rfp['raw_metadata']['durmot_stack_matches'] = list(set(stack_matches)) 
        
        # NEW: Attach the suspect directly to the payload
        rfp['suspected_incumbent'] = suspected_vendors[0] if suspected_vendors else None
        
        return rfp

    def process_results(self, rfp_list):
        unique_rfps = {item['url']: item for item in rfp_list}.values()
        processed = []
        for raw_rfp in unique_rfps:
            rfp = self.score_and_flag(raw_rfp)
            if not rfp: continue
            
            # NEW: We format the payload to explicitly guide Claude's next action
            processed.append({
                "agency": rfp['agency'],
                "title": rfp['title'],
                "friction_score": rfp['friction_score'],
                "friction_flags": rfp['friction_flags'],
                "suspected_incumbent": rfp['suspected_incumbent'],
                "ai_next_action_prompt": f"If suspected_incumbent is not null, run audit_vendor_checkbook for '{rfp['agency']}' and '{rfp['suspected_incumbent']}'." if rfp['suspected_incumbent'] else "No clear incumbent identified.",
                "url": rfp.get('url', 'No URL provided') 
            })
            
        processed.sort(key=lambda x: x['friction_score'], reverse=True)
        return processed
