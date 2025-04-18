import subprocess
import requests
import re
import json
import csv
import time
from datetime import datetime, timedelta
import pytz
import os

ACQUISITION_INTERVAL = 5        # MINUTES

def log_data(write=True):
    try:
        subprocess.run(["python3", "log_data.py", '--write'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed running log_data.py: {e}")

def wait_till_next_quarter():
    """Waits until the next acquisition."""
    now = datetime.now(pytz.utc)
    quarter = int(now.minute / ACQUISITION_INTERVAL)
    this_quarter_time = now.replace(minute=quarter * ACQUISITION_INTERVAL, second=0, microsecond=0)
    next_quarter_time = this_quarter_time + timedelta(minutes=ACQUISITION_INTERVAL)
    sleep_seconds = (next_quarter_time - now).total_seconds()
    print(f"Next data acquisition will happen at {next_quarter_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    return sleep_seconds

if not os.path.exists("data"):
    os.makedirs("data")
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
