#!/usr/bin/env python3
import os
import json
import sqlite3
from datetime import datetime
import shutil

DATA_DIR = "database/data"
# -----------------------------
# Database directory + file
# -----------------------------
DATABASE_DIR = "database"
DB_FILE = os.path.join(DATABASE_DIR, "flights.db")

# Ensure directory exists
if not os.path.exists(DATABASE_DIR):
    os.makedirs(DATABASE_DIR)
    print(f"[INFO] Created directory: {DATABASE_DIR}")

# -----------------------------
# Backup DB before modifying
# -----------------------------
def backup_database():
    if not os.path.exists(DB_FILE):
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"flights.db.backup_{ts}"
    backup_path = os.path.join(DATABASE_DIR, backup_name)
    shutil.copy2(DB_FILE, backup_path)
    print(f"[BACKUP] Created {backup_path}")

# -----------------------------
# Safe update logic helpers
# -----------------------------
def safe_update(existing, new):
    """
    Returns new value only if:
    - existing is None or empty
    - new is not None or empty
    """
    if (existing is None or existing == "") and (new not in [None, ""]):
        return new
    return existing

# -----------------------------
# Initialize schema
# -----------------------------
def init_db(conn):
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS aircraft (
            registration TEXT PRIMARY KEY,
            operator TEXT,
            type TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS flights (
            registration TEXT,
            date TEXT,
            flight TEXT,
            from_airport TEXT,
            to_airport TEXT,
            flight_time TEXT,
            std TEXT,
            atd TEXT,
            sta TEXT,
            status TEXT,
            UNIQUE(registration, date, flight)
        )
    """)

    conn.commit()

# -----------------------------
# Update aircraft table
# -----------------------------
def update_aircraft(conn, reg, operator, type_):
    cur = conn.cursor()

    cur.execute("SELECT operator, type FROM aircraft WHERE registration=?", (reg,))
    row = cur.fetchone()

    if row is None:
        # insert new
        cur.execute(
            "INSERT INTO aircraft (registration, operator, type) VALUES (?, ?, ?)",
            (reg, operator, type_)
        )
    else:
        existing_operator, existing_type = row
        new_operator = safe_update(existing_operator, operator)
        new_type = safe_update(existing_type, type_)

        cur.execute(
            "UPDATE aircraft SET operator=?, type=? WHERE registration=?",
            (new_operator, new_type, reg)
        )

    conn.commit()

# -----------------------------
# Update flight history table
# -----------------------------
def update_flights(conn, reg, flights):
    cur = conn.cursor()

    for f in flights:
        date = f.get("date")
        flight = f.get("flight")

        # Try to insert
        try:
            cur.execute("""
                INSERT INTO flights (
                    registration, date, flight, from_airport, to_airport,
                    flight_time, std, atd, sta, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                reg, date, flight,
                f.get("from"), f.get("to"),
                f.get("flight_time"),
                f.get("std"),
                f.get("atd"),
                f.get("sta"),
                f.get("status")
            ))
        except sqlite3.IntegrityError:
            # Exists → update only missing fields
            cur.execute("""
                SELECT from_airport, to_airport, flight_time, std, atd, sta, status
                FROM flights WHERE registration=? AND date=? AND flight=?
            """, (reg, date, flight))

            row = cur.fetchone()
            if not row:
                continue

            (ex_from, ex_to, ex_time, ex_std, ex_atd, ex_sta, ex_status) = row

            new_from = safe_update(ex_from, f.get("from"))
            new_to = safe_update(ex_to, f.get("to"))
            new_time = safe_update(ex_time, f.get("flight_time"))
            new_std = safe_update(ex_std, f.get("std"))
            new_atd = safe_update(ex_atd, f.get("atd"))
            new_sta = safe_update(ex_sta, f.get("sta"))
            new_status = safe_update(ex_status, f.get("status"))

            cur.execute("""
                UPDATE flights
                SET from_airport=?, to_airport=?, flight_time=?, std=?, atd=?, sta=?, status=?
                WHERE registration=? AND date=? AND flight=?
            """, (
                new_from, new_to, new_time, new_std, new_atd, new_sta, new_status,
                reg, date, flight
            ))

    conn.commit()

# -----------------------------
# Load all JSON files & update DB
# -----------------------------
def main():
    backup_database()

    conn = sqlite3.connect(DB_FILE)
    init_db(conn)

    files = sorted(os.listdir(DATA_DIR))

    print(f"[INFO] Found {len(files)} files to process.")

    for file in files:
        if not file.endswith(".json"):
            continue

        path = os.path.join(DATA_DIR, file)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        reg = data["registration"]
        operator = data.get("operator")
        type_ = data.get("type")
        flights = data.get("flight_history", [])

        print(f"[UPDATE] {reg} (flights: {len(flights)})")

        update_aircraft(conn, reg, operator, type_)
        update_flights(conn, reg, flights)

    conn.close()
    print("[DONE] Database updated successfully.")

if __name__ == "__main__":
    main()
