#!/usr/bin/env python3
import os
import json
import subprocess
import time
from pathlib import Path

# Paths
CONFIG_JSON = Path(__file__).resolve().parent / "config.json"
NETWORK_DIR = Path("/etc/systemd/network")

def run(cmd):
    """Run shell commands safely."""
    print(f"→ {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Command failed: {e}")

def remove_old_dummies():
    """Remove all dummy interfaces currently existing."""
    print("\n🧹 Removing old dummy interfaces...")
    try:
        output = subprocess.check_output(["ip", "-o", "link", "show"], text=True)
        for line in output.splitlines():
            if "dummy" in line:
                iface = line.split(":")[1].strip()
                print(f"  - Deleting {iface}")
                subprocess.run(["sudo", "ip", "link", "del", iface], stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("⚠️ Could not list dummy interfaces, continuing...")

def ensure_module_loaded():
    """Load dummy module if not already loaded."""
    print("\n📦 Loading dummy kernel module...")
    subprocess.run(["sudo", "modprobe", "dummy"])
    # Make persistent
    with open("/etc/modules", "r+") as f:
        lines = f.read().splitlines()
        if "dummy" not in lines:
            f.write("\ndummy\n")
            print("✅ Added 'dummy' to /etc/modules for persistence")

def create_dummy_files(configs):
    """Generate .netdev and .network files for each dummy interface."""
    print("\n🛠️ Creating systemd-networkd configs...")
    NETWORK_DIR.mkdir(parents=True, exist_ok=True)

    for link in configs:
        iface = link.get("interface", "")
        ip = link.get("ip", "")
        netmask = link.get("netmask", "255.255.255.0")

        # Calculate CIDR prefix (simple)
        prefix = sum([bin(int(x)).count("1") for x in netmask.split(".")])

        netdev_file = NETWORK_DIR / f"10-{iface}.netdev"
        network_file = NETWORK_DIR / f"10-{iface}.network"

        print(f"  - Creating {iface} ({ip}/{prefix})")

        netdev_file.write_text(f"[NetDev]\nName={iface}\nKind=dummy\n")
        network_file.write_text(
            f"[Match]\nName={iface}\n\n[Network]\nAddress={ip}/{prefix}\n"
        )

def restart_networkd():
    print("\n🔁 Restarting systemd-networkd...")
    subprocess.run(["sudo", "systemctl", "restart", "systemd-networkd"])
    time.sleep(3)
    print("✅ Restarted successfully")

def main():
    print("🚀 Dummy Interface Setup\n")

    if not CONFIG_JSON.exists():
        print(f"❌ config.json not found at {CONFIG_JSON}")
        return

    with open(CONFIG_JSON) as f:
        configs = json.load(f)

    ensure_module_loaded()
    remove_old_dummies()
    create_dummy_files(configs)
    restart_networkd()

    print("\n✅ All dummy interfaces created successfully.")
    print("💡 You can check them using: ip link show | grep dummy")

if __name__ == "__main__":
    main()
