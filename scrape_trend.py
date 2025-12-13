
import requests
import csv
import time
import os

# Constants
BASE_URL = "https://trend.kerala.nic.in/includes"
SV_AJAX_URL = f"{BASE_URL}/stateView2_ajax.php"
LB_AJAX_URL = f"{BASE_URL}/lb_ajax2.php"

# District Codes
DISTRICTS = {
    'D01001': 'Thiruvananthapuram',
    'D02001': 'Kollam',
    'D03001': 'Pathanamthitta',
    'D04001': 'Alappuzha',
    'D05001': 'Kottayam',
    'D06001': 'Idukki',
    'D07001': 'Ernakulam',
    'D08001': 'Thrissur',
    'D09001': 'Palakkad',
    'D10001': 'Malappuram',
    'D11001': 'Kozhikode',
    'D12001': 'Wayanad',
    'D13001': 'Kannur',
    'D14001': 'Kasaragod'
}

# Local Body Types
LB_TYPES = {
    'G': 'Grama Panchayat',
    'B': 'Block Panchayat',
    'D': 'District Panchayat',
    'M': 'Municipality',
    'C': 'Corporation'
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
}

OUTPUT_FILE = "trend_election_data_2025.csv"

import concurrent.futures
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Setup Retries
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http = requests.Session()
http.mount("https://", adapter)
http.mount("http://", adapter)

def fetch_with_retry(url, payload):
    try:
        response = http.post(url, data=payload, headers=HEADERS, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Request failed for {url}: {e}")
        return None

def fetch_local_bodies(district_code, lb_type_char):
    req_type = lb_type_char
    if lb_type_char == 'G': req_type = 'P'
    if lb_type_char == 'M': req_type = 'C' 
    
    payload = {
        '_p': 'dv',
        '_l': req_type,
        '_d': district_code,
        '_s': 'L'
    }
    
    data = fetch_with_retry(SV_AJAX_URL, payload)
    if data and 'payload' in data:
        return data['payload']
    return []

def fetch_wards(lb_code, lb_type_request_param):
    payload = {
        '_p': 'wv',
        '_w': lb_code,
        '_t': lb_type_request_param,
        '_s': 'L'
    }
    data = fetch_with_retry(LB_AJAX_URL, payload)
    if data and 'payload' in data:
        return data['payload']
    return []

def process_lb_task(args):
    """
    Helper function to process a single LB.
    args: (d_name, req_type, lb_info)
    """
    d_name, req_type, lb = args
    rows = []
    
    try:
        lb_code = lb[0]
        lb_name = lb[1]
        
        # Determine explicit LB Type from Code
        lb_type_name = "Unknown"
        if lb_code.startswith('G'): lb_type_name = "Grama Panchayat"
        elif lb_code.startswith('B'): lb_type_name = "Block Panchayat"
        elif lb_code.startswith('D'): lb_type_name = "District Panchayat"
        elif lb_code.startswith('M'): lb_type_name = "Municipality"
        elif lb_code.startswith('C'): lb_type_name = "Corporation"
        
        wards = fetch_wards(lb_code, req_type)
        
        for w in wards:
            full_ward_id = w[0]
            ward_no = full_ward_id[6:9] if len(full_ward_id) >= 9 else full_ward_id
            party = w[1]
            if not party: party = "Ind/Other"
            
            candidate_name = w[3]
            votes = w[4]
            ward_name = w[5]
            status_flag = w[6]
            rival_name = w[8]
            rival_votes = w[9]
            
            status = "Won" if status_flag == 'Y' else "Leading"
            
            rows.append([
                d_name, lb_type_name, lb_code, lb_name,
                ward_no, ward_name,
                candidate_name, party, votes, status,
                rival_name, rival_votes
            ])
            
    except Exception as e:
        print(f"Error processing LB {lb[1] if len(lb)>1 else 'Unknown'}: {e}")
        
    return rows

def main():
    # Write CSV Header
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow([
            'District', 'LB_Type', 'LB_Code', 'LB_Name', 
            'Ward_No', 'Ward_Name', 
            'Candidate_Name', 'Party', 'Votes', 'Status',
            'Rival_Name', 'Rival_Votes'
        ])

    all_lb_tasks = []

    print("Fetching Local Body lists...")
    for d_code, d_name in DISTRICTS.items():
        print(f"  District: {d_name}")
        for req_type in ['P', 'B', 'D', 'C']:
            lbs = fetch_local_bodies(d_code, req_type)
            print(f"    Type {req_type}: {len(lbs) if lbs else 0} LBs found")
            if not lbs:
                continue
            for lb in lbs:
                all_lb_tasks.append((d_name, req_type, lb))
    
    print(f"Total Local Bodies to scrape: {len(all_lb_tasks)}")
    
    print("Starting parallel scrape (max_workers=5)...")
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # Map returns in order, but we can iterate as completed or just map
        results = executor.map(process_lb_task, all_lb_tasks)
        
        with open(OUTPUT_FILE, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            count = 0
            for rows in results:
                if rows:
                    writer.writerows(rows)
                count += 1
                if count % 100 == 0:
                    print(f"  Processed {count}/{len(all_lb_tasks)} LBs...")

    end_time = time.time()
    print(f"Scraping completed in {end_time - start_time:.2f} seconds.")

if __name__ == "__main__":
    main()
