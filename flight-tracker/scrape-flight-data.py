import argparse
import os
import re
import json
import requests
from bs4 import BeautifulSoup

def extract_dispatcher_json(html):
    """
    Extract the JSON object assigned to 'window.dispatcher' in the HTML.
    """
    # Regex to extract: window.dispatcher = {...};
    pattern = r"window\.dispatcher\s*=\s*(\{.*?\});"
    match = re.search(pattern, html, re.DOTALL)

    if not match:
        return None

    json_text = match.group(1)

    # Ensure valid JSON (remove trailing semicolon if needed)
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        # Try fixing common issues
        try:
            return json.loads(json_text.rstrip(";"))
        except:
            return None


def fetch_aircraft_info(registration):
    """
    Fetch the aircraft info page and extract JSON.
    """
    url = f"https://www.flightradar24.com/data/aircraft/{registration.lower()}"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    print(f"Fetching: {url}")
    resp = requests.get(url, headers=headers)

    if resp.status_code != 200:
        print(f"Failed to fetch {registration}: HTTP {resp.status_code}")
        return None

    data = extract_dispatcher_json(resp.text)

    if data is None:
        print(f"Could not extract JSON for {registration}")
    
    return data


def main():
    parser = argparse.ArgumentParser(description="Fetch FR24 aircraft JSON.")
    parser.add_argument(
        "-r", "--registrations",
        nargs="+",
        required=True,
        help="List of aircraft registration numbers (e.g., VT-IFM VT-IFL)"
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Output directory to store JSON files"
    )

    args = parser.parse_args()

    # Ensure output directory exists
    os.makedirs(args.output, exist_ok=True)

    for reg in args.registrations:
        data = fetch_aircraft_info(reg)

        if data is None:
            continue

        out_path = os.path.join(args.output, f"{reg.upper()}.json")

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
