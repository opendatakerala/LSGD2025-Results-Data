import requests
import csv
import time
import os
import concurrent.futures
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
}

OUTPUT_FILE = "trend_detailed_results_2025.csv"

# Setup Retries
retry_strategy = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http = requests.Session()
http.mount("https://", adapter)
http.mount("http://", adapter)

def fetch_with_retry(url, payload):
    try:
        response = http.post(url, data=payload, headers=HEADERS, timeout=20)
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

def fetch_candidate_details(ward_code, lb_type_request_param):
    """
    Fetches detailed candidate list for a ward.
    _p: 'can'
    _w: Ward Code
    _t: LB Type Request Param
    _s: 'L'
    """
    payload = {
        '_p': 'can',
        '_w': ward_code,
        '_t': lb_type_request_param,
        '_s': 'L'
    }
    data = fetch_with_retry(LB_AJAX_URL, payload)
    # Payload analysis from JS: v[0]=Party, v[1]=Code, v[2]=FirstName, v[3]=SecondName?, v[4]=Votes (Total?), v[5]=Leading?, v[6]=Won?
    if data and 'payload' in data:
        return data['payload']
    return []

def process_lb_task(args):
    """
    Helper function to process a single LB and its wards.
    args: (d_name, req_type, lb_info)
    """
    d_name, req_type, lb = args
    rows = []
    
    try:
        lb_code = lb[0]
        lb_name = lb[1]
        
        lb_type_name = "Unknown"
        if lb_code.startswith('G'): lb_type_name = "Grama Panchayat"
        elif lb_code.startswith('B'): lb_type_name = "Block Panchayat"
        elif lb_code.startswith('D'): lb_type_name = "District Panchayat"
        elif lb_code.startswith('M'): lb_type_name = "Municipality"
        elif lb_code.startswith('C'): lb_type_name = "Corporation"
        
        wards = fetch_wards(lb_code, req_type)
        if not wards:
            pass # No wards found for this LB
            
        for w in wards:
            # Info from Ward List (Higher level)
            full_ward_id = w[0] # This serves as the 'ward code' for the next call
            ward_no = full_ward_id[6:9] if len(full_ward_id) >= 9 else full_ward_id
            ward_name = w[5]
            
            # Fetch Candidates for this Ward
            candidates = fetch_candidate_details(full_ward_id, req_type)
            
            for c in candidates:
                # Based on JS createTable for 'can' view:
                # trObj.append($('<td />').html(v[0])); // Party (if empty -> invalid?)
                # trObj.append($('<td />').html(v[1])); // Code
                # trObj.append($('<td />').html(v[2] + ' ' + v[3])); // Name
                # v[6]==='Y' && v[5]==='1' -> Won
                # v[5]=='1' -> Leading
                # trObj.append($('<td />').html(v[4])); // Total Votes
                
                c_party = c[0]
                if not c_party: c_party = "Ind/Other"
                
                c_code = c[1]
                c_name = f"{c[2]} {c[3]}".strip()
                c_votes = c[4]
                
                is_leading = (c[5] == "1")
                is_won = (c[6] == "Y")
                
                c_status = "Lost"
                if is_won: c_status = "Won"
                elif is_leading: c_status = "Leading"
                
                rows.append([
                    d_name, lb_type_name, lb_code, lb_name,
                    ward_no, ward_name,
                    c_code, c_name, c_party, c_votes, c_status
                ])
            
            # Sleep slightly between wards to be polite within the LB task
            time.sleep(0.05)
            
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
            'Candidate_Code', 'Candidate_Name', 'Party', 'Votes', 'Status'
        ])

    all_lb_tasks = []

    print("Fetching Local Body lists...")
    for d_code, d_name in DISTRICTS.items():
        print(f"  District: {d_name}")
        for req_type in ['P', 'B', 'D', 'C']:
            lbs = fetch_local_bodies(d_code, req_type)
            for lb in lbs:
                all_lb_tasks.append((d_name, req_type, lb))
    
    print(f"Total Local Bodies to scrape: {len(all_lb_tasks)}")
    
    # Use conservative concurrency for detailed scrape as it makes MANY more requests per LB
    print("Starting detailed scrape (max_workers=5)...")
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(process_lb_task, all_lb_tasks)
        
        with open(OUTPUT_FILE, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            count = 0
            for rows in results:
                if rows:
                    writer.writerows(rows)
                count += 1
                if count % 10 == 0: # More frequent updates since tasks are heavier
                    print(f"  Processed {count}/{len(all_lb_tasks)} LBs...")

    end_time = time.time()
    print(f"Detailed scraping completed in {end_time - start_time:.2f} seconds.")

if __name__ == "__main__":
    main()
