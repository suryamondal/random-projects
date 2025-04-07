#!/usr/bin/env python3

import itertools
import subprocess
import argparse
import shlex
from datetime import datetime

# Constants for PAN generation
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"
TYPE_CHAR = "P"              # 'P' for individual PAN holder
FIXED_DIGITS = "268"
CHECK_CHAR = "K"

# Generate PANs of format: AAAPX268K
def generate_individual_pan_parts():
    for l1, l2, l3 in itertools.product(LETTERS, repeat=3):  # AAA to ZZZ
        for surname_letter in LETTERS:  # A to Z
            for first_digit in DIGITS:  # A to Z
                yield f"{l1}{l2}{l3}{TYPE_CHAR}{surname_letter}{first_digit}{FIXED_DIGITS}{CHECK_CHAR}"

# Write combinations to file
def write_pan_wordlist(filename):
    with open(filename, 'w') as file:
        for pan in generate_individual_pan_parts():
            file.write(pan + '\n')

# Run pdfcrack with the generated wordlist
def run_pdfcrack(passfile, pdf_file, stdout_log, stderr_log):
    cmd = ['pdfcrack', '-f', pdf_file, '-w', passfile]
    print(datetime.now().strftime("\033[33m[%Y-%m-%d %H:%M:%S]\033[0m"), shlex.join(cmd))
    with open(stdout_log, 'w') as stdout_file, open(stderr_log, 'w') as stderr_file:
        subprocess.run(cmd, check=True, stdout=stdout_file, stderr=stderr_file)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate-strings", action="store_true", help="Generate PAN-based password list")
    parser.add_argument("--crack-pdf", type=str, help="PDF file to crack")
    parser.add_argument("--wordlist", type=str, default="pan_passlist.txt", help="Output wordlist filename")
    parser.add_argument("--stdout-log", type=str, default="pdfcrack_out.log")
    parser.add_argument("--stderr-log", type=str, default="pdfcrack_err.log")
    args = parser.parse_args()

    if args.generate_strings:
        print("[+] Generating individual PAN password wordlist...")
        write_pan_wordlist(args.wordlist)
        print(f"[+] Done. Wordlist saved to {args.wordlist}")

    if args.crack_pdf:
        print(f"[+] Attempting to crack PDF: {args.crack_pdf}")
        run_pdfcrack(args.wordlist, args.crack_pdf, args.stdout_log, args.stderr_log)
        print("[+] Finished PDF cracking attempt.")
