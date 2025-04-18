import requests
import re
import json
import csv
import time
from datetime import datetime, timedelta
import pytz
import argparse
from yt_dlp import YoutubeDL

# List of verified videos and their tags
VIDEOS = [
    {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "tag": "Classic_Rickroll"},
    {"url": "https://www.youtube.com/watch?v=ZyhrYis509A", "tag": "Aqua_Barbie"},
    {"url": "https://www.youtube.com/watch?v=_cr46G2K5Fo", "tag": "Veritasium_Broke_Math"},
    {"url": "https://www.youtube.com/watch?v=qJZ1Ez28C-A", "tag": "Veritasium_Strange_Trust_Quantum"},
    {"url": "https://www.youtube.com/watch?v=lcjdwSY2AzM", "tag": "Veritasium_Mistake_Einstein"},
    {"url": "https://www.youtube.com/watch?v=iUn5F52SNuY", "tag": "Dhruv_Rathee_Trump_Tariff"},
    {"url": "https://www.youtube.com/watch?v=6y5hGiqd9rA", "tag": "Dhruv_Rathee_Milky_Way"},
    {"url": "https://www.youtube.com/watch?v=k2xudgpVExw", "tag": "Shyam_Sharma_National_Herald"},
    {"url": "https://www.youtube.com/watch?v=cvjA-jXk94o", "tag": "Linus_Tech_Malaysia_Tech_Mall"},
    {"url": "https://www.youtube.com/watch?v=MZE99-Be_Gk", "tag": "Linus_Tech_Dell_Hung_Up"},
    {"url": "https://www.youtube.com/watch?v=TD_RYb7m4Pw", "tag": "Linus_Tech_Clean_Pool"},
    {"url": "https://www.youtube.com/watch?v=6RiYXI1Tfu4", "tag": "Tom_Schott_Aerial_Ropeway"},
]

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--write", action="store_true",
                    help="Write to csv file if true")
args = parser.parse_args()


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}


def extract_video_stats(url):
    try:
        with YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            views = info.get("view_count", 0)
            return {"views": views}
    except Exception as e:
        print(f"Error fetching stats for {url}: {e}")
        return None

def log_data(write=False):
    """Fetches and logs data for all videos."""
    for video in VIDEOS:
        timestamp = datetime.now(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
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


log_data(args.write)
