import requests
import re
import json
import csv
import time
from datetime import datetime, timedelta
import pytz

ACQUISITION_INTERVAL = 5        # MINUTES

# List of videos and their tags
# List of verified videos and their tags
VIDEOS = [
    {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "tag": "Classic_Rickroll"},
    {"url": "https://www.youtube.com/watch?v=ZyhrYis509A", "tag": "Aqua_Barbie"},
    {"url": "https://www.youtube.com/watch?v=_cr46G2K5Fo", "tag": "Veritasium_Broke_Math"},
    {"url": "https://www.youtube.com/watch?v=qJZ1Ez28C-A", "tag": "Veritasium_Strange_Trust_Quantum"},
    {"url": "https://www.youtube.com/watch?v=lcjdwSY2AzM", "tag": "Veritasium_Mistake_Einstein"},
    {"url": "https://www.youtube.com/watch?v=iUn5F52SNuY", "tag": "Dhruv_Rathee_Trump_Tariff"},
    {"url": "https://www.youtube.com/watch?v=k2xudgpVExw", "tag": "Shyam_Sharma_National_Herald"},
    {"url": "https://www.youtube.com/watch?v=cvjA-jXk94o", "tag": "Linus_Tech_Malaysia_Tech_Mall"},
    {"url": "https://www.youtube.com/watch?v=MZE99-Be_Gk", "tag": "Linus_Tech_Dell_Hung_Up"},
    {"url": "https://www.youtube.com/watch?v=6RiYXI1Tfu4", "tag": "Tom_Schott_Aerial_Ropeway"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

def extract_video_stats(url):
    """Fetches view count from YouTube video page."""
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"Failed to fetch {url}")
        return None
    html = response.text
    # Try to extract player response JSON
    match = re.search(r'var ytInitialPlayerResponse = ({.*?});', html)
    if not match:
        print(f"Could not find player response for {url}")
        return None
    try:
        data = json.loads(match.group(1))
        video_details = data.get("videoDetails", {})
        views = int(video_details.get("viewCount", 0))
        return {"views": views}
    except Exception as e:
        print(f"Error parsing data: {e}")
        return None

def wait_till_next_quarter():
    """Waits until the next acquisition."""
    now = datetime.now(pytz.utc)
    quarter = int(now.minute / ACQUISITION_INTERVAL)
    this_quarter_time = now.replace(minute=quarter * ACQUISITION_INTERVAL, second=0, microsecond=0)
    next_quarter_time = this_quarter_time + timedelta(minutes=ACQUISITION_INTERVAL)
    sleep_seconds = (next_quarter_time - now).total_seconds()
    print(f"Next data acquisition will happen at {next_quarter_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    return sleep_seconds

def log_data(write=False):
    """Fetches and logs data for all videos."""
    timestamp = datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
    for video in VIDEOS:
        # Define the CSV file for each tag
        csv_file = f"data/{video['tag']}_views.csv"
        # Fetch stats for the video
        stats = extract_video_stats(video["url"])
        # If stats are found, write them to the corresponding CSV file
        if stats:
            if write:
                with open(csv_file, "a", newline='') as csvfile:
                    writer = csv.writer(csvfile)
                    # Initialize the CSV with headers if the file doesn't exist
                    if csvfile.tell() == 0:
                        writer.writerow(["timestamp", "tag", "views"])
                    writer.writerow([timestamp, video["tag"], stats["views"]])
            print(f"[{timestamp}] {video['tag']} - Views: {stats['views']}")
        else:
            print(f"[{timestamp}] Failed to retrieve stats for {video['tag']}")

# Run the tracker every n minutes at the quarter-hour marks
print("Starting YouTube tracker. Press Ctrl+C to stop.")
try:
    log_data(False)
    while True:
        # Sleep until the next quarter-hour mark
        sleep_time = wait_till_next_quarter()
        time.sleep(sleep_time)
        # log data
        log_data(True)
except KeyboardInterrupt:
    print("Tracking stopped.")
