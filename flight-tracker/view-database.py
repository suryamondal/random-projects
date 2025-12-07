#!/usr/bin/env python3
import argparse
import sqlite3
import os

DATABASE_DIR = "database"
DB_FILE = os.path.join(DATABASE_DIR, "flights.db")

def list_aircraft(limit):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    query = "SELECT registration, operator, type FROM aircraft ORDER BY registration"
    if limit:
        query += f" LIMIT {limit}"
    for row in cur.execute(query):
        reg, op, typ = row
        print(f"{reg:10}  {op or '-':15}  {typ or '-'}")
    conn.close()

def list_flights(reg, limit):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    query = """
        SELECT date, flight, from_airport, to_airport, std, atd, status
        FROM flights
        WHERE registration=?
        ORDER BY date
    """
    if limit:
        query += f" LIMIT {limit}"

    cur.execute(query, (reg,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print(f"No flights found for {reg}")
        return

    print(f"Flights for {reg}:\n")
    for (date, flight, from_air, to_air, std, atd, status) in rows:
        print(f"{date:12}  {flight:8}  {from_air:20} → {to_air:20}  STD {std or '-'} ATD {atd or '-'}  {status}")

def main():
    parser = argparse.ArgumentParser(description="View contents of flights.db")

    sub = parser.add_subparsers(dest="mode", required=True)

    p1 = sub.add_parser("aircraft", help="List aircraft in DB")
    p1.add_argument("--limit", type=int, default=None)

    p2 = sub.add_parser("flights", help="List flights for a registration")
    p2.add_argument("registration")
    p2.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()

    if not os.path.exists(DB_FILE):
        print(f"Database not found: {DB_FILE}")
        return

    if args.mode == "aircraft":
        list_aircraft(args.limit)

    elif args.mode == "flights":
        reg = args.registration.upper()
        list_flights(reg, args.limit)

if __name__ == "__main__":
    main()
