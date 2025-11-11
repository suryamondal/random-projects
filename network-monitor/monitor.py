import os
import json
import time
import subprocess
import sqlite3
import requests
import configparser
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_JSON = os.path.join(BASE_DIR, "config.json")
CONFIG_INI = os.path.join(BASE_DIR, "config.ini")
DB_PATH = os.path.join(BASE_DIR, "fibre_data.db")

def load_config():
    with open(CONFIG_JSON) as f:
        ip_configs = json.load(f)
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_INI)
    return ip_configs, cfg

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        link_name TEXT,
        avg_ping REAL,
        success INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    return conn

def set_network(ip, netmask, gateway, dns, interface):
    # Reset and apply IP configuration using dhcpcd or ip
    subprocess.run(["sudo", "dhcpcd", "-k", interface], stderr=subprocess.DEVNULL)
    time.sleep(2)
    subprocess.run(["sudo", "ip", "addr", "flush", "dev", interface])
    subprocess.run(["sudo", "ip", "addr", "add", f"{ip}/{netmask}", "dev", interface])
    subprocess.run(["sudo", "ip", "route", "add", "default", "via", gateway])
    with open("/etc/resolv.conf", "w") as dnsfile:
        dnsfile.write(f"nameserver {dns}\n")
    time.sleep(5)

def ping_host(host, count, timeout):
    try:
        output = subprocess.check_output(
            ["ping", "-c", str(count), "-W", str(timeout), host],
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        for line in output.split("\n"):
            if "avg" in line:
                avg = line.split("/")[4]
                return float(avg)
        return None
    except subprocess.CalledProcessError:
        return None

def send_telegram(bot_token, chat_id, message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": message})

def main():
    conn = init_db()
    last_summary = datetime.now()

    while True:
        ip_configs, cfg = load_config()
        bot_token = cfg["telegram"]["bot_token"]
        chat_id = cfg["telegram"]["chat_id"]
        host = cfg["monitor"]["ping_host"]
        ping_count = int(cfg["monitor"]["ping_count"])
        timeout = int(cfg["monitor"]["ping_timeout"])
        threshold = float(cfg["monitor"]["latency_threshold"])
        cycle_delay = int(cfg["monitor"]["cycle_delay"])
        summary_interval = int(cfg["monitor"]["summary_interval"])
        interface = cfg["monitor"]["interface"]

        for link in ip_configs:
            name = link["name"]
            set_network(link["ip"], link["netmask"], link["gateway"], link["dns"], interface)
            avg = ping_host(host, ping_count, timeout)
            success = 1 if avg else 0

            conn.execute("INSERT INTO results (link_name, avg_ping, success) VALUES (?, ?, ?)", (name, avg or 0, success))
            conn.commit()

            if not success:
                send_telegram(bot_token, chat_id, f"⚠️ {name} failed to reach {host}")
            elif avg > threshold:
                send_telegram(bot_token, chat_id, f"⚠️ {name} latency high: {avg:.2f} ms")

        if datetime.now() - last_summary > timedelta(seconds=summary_interval):
            cur = conn.execute("SELECT link_name, AVG(avg_ping), SUM(success), COUNT(*) FROM results WHERE timestamp > datetime('now','-30 minutes') GROUP BY link_name")
            msg = "📊 *30-Minute Summary:*\n"
            for row in cur.fetchall():
                name, avg, ok, total = row
                msg += f"{name}: {avg:.1f} ms avg ({ok}/{total} ok)\n"
            send_telegram(bot_token, chat_id, msg)
            last_summary = datetime.now()

        time.sleep(cycle_delay)

if __name__ == "__main__":
    main()
