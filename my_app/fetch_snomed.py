import os

import requests

# Replace with your UMLS API Key
UMLS_API_KEY = os.environ.get("UMLS_API_KEY")

# Function to get Authentication Ticket Granting Ticket (TGT)
def get_tgt(api_key):
    url = "https://utslogin.nlm.nih.gov/cas/v1/api-key"
    response = requests.post(url, data={"apikey": api_key})
    if response.status_code == 201:
        tgt_url = response.headers["Location"]
        return tgt_url
    else:
        raise Exception("Failed to get TGT. Check API Key.")

# Function to get a Service Ticket (ST)
def get_service_ticket(tgt_url):
    response = requests.post(tgt_url, data={"service": "http://umlsks.nlm.nih.gov"})
    if response.status_code == 200:
        return response.text
    else:
        raise Exception("Failed to get Service Ticket.")

# Function to convert ICD-10 to SNOMED CT
def icd10_to_snomed(icd10_code, search_query):
    try:
        tgt_url = get_tgt(UMLS_API_KEY)
        service_ticket = get_service_ticket(tgt_url)

        url = f"https://uts-ws.nlm.nih.gov/rest/crosswalk/current/source/ICD10CM/{icd10_code}?targetSource=SNOMEDCT_US&ticket={service_ticket}"
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()
            snomed_mappings = data.get("result", [])

            if snomed_mappings:
                # print(f"ICD-10 Code: {icd10_code}")
                # for mapping in snomed_mappings:
                    # print(f"- SNOMED CT Code: {mapping['ui']} | Name: {mapping['name']}")

                return snomed_mappings[0]['ui']

            # else:
                # print(f"No SNOMED CT mapping found for ICD-10 code {icd10_code}")
                # search_concept(search_query)
        else:
            print("Error fetching SNOMED mappings.")

    except Exception as e:
        print(f"Error: {e}")

# Example Usage
# icd10_code = "E11.9"  # Replace with your ICD-10 code
# icd10_to_snomed(icd10_code)

def search_concept(query):
    try:
        url = f"https://uts-ws.nlm.nih.gov/rest/search/current?apiKey={UMLS_API_KEY}&string={query}"
        response = requests.request("GET", url)
        print(response.json())
    except Exception as e:
        print(f"Error: {e}")
