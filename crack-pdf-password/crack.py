#!/usr/bin/env python3

## Use
## ./generate_pass.py --generate-strings --crack-pdf 9129477180931072024.pdf --start-year 1985 --end-year 2005

import itertools
from datetime import datetime, timedelta
import concurrent.futures
import os
import subprocess
import signal
import sys
import argparse
import shlex

num_processors = os.cpu_count()

# Generate list of strings from 00000 to 99999
def generate_first_part():
    return [f"{i:05}" for i in range(100000)]

# Generate all valid dates from 01/01/1985 to 31/12/2005 in DDMMYY format
def generate_dates(start_date, end_date):
    date_list = []
    current_date = start_date
    while current_date <= end_date:
        date_list.append(current_date.strftime("%d%m%y"))
        current_date += timedelta(days=1)
    return date_list

# Write to file
def write_to_file(filename, data):
    with open(filename, 'w') as file:
        for item in data:
            file.write(f"{item}\n")

# Main function to generate all combinations
def generate_all_strings(start_date, end_date, filename):
    first_part = generate_first_part()
    second_part = generate_dates(start_date, end_date)
    all_combinations = (f"{fp}{dp}" for fp, dp in itertools.product(first_part, second_part))
    write_to_file(filename, all_combinations)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrent-jobs", type=int, help="Number of maximum concurrent jobs.", default=num_processors)
    parser.add_argument("--generate-strings", action="store_true", help="generate passwords")
    parser.add_argument("--crack-pdf", type=str, help="crack pdf", default=None)
    parser.add_argument("--start-year", type=int, help="Start year.", default=1985)
    parser.add_argument("--end-year", type=int, help="End year.", default=1985)
    
    args = parser.parse_args()

    # Define a function to execute a system command
    def run_command_anal(cmd):
        stdout_log = cmd[-3]
        stderr_log = cmd[-2]
        passfile = cmd[-4]
        year = cmd[-1]
        basfcmd = cmd[:-3]
        print(datetime.now().strftime("\033[33m[%Y-%m-%d %H:%M:%S]\033[0m"),
              shlex.join(basfcmd), "1>", stdout_log, "2>", stderr_log, year)
        if args.generate_strings:
            generate_all_strings(datetime(year, 1, 1), datetime(year, 12, 31), passfile)
        if args.crack_pdf:
            with open(stdout_log, 'w') as stdout_file, open(stderr_log, 'w') as stderr_file:
                subprocess.run(basfcmd, check=True, stdout=stdout_file, stderr=stderr_file)

    # list of jobs
    commandsAnal = []

    for year in range(args.start_year, args.end_year + 1, 1):
        passfile = f"generated_strings_{year}.txt"
        logout = f"generated_strings_{year}_out.log"
        logerr = f"generated_strings_{year}_err.log"
        cmd = ['pdfcrack', '-f', args.crack_pdf, '-w', passfile, logout, logerr, year]
        commandsAnal += [cmd]

    # Number of concurrent jobs
    max_concurrent_jobs = min(args.concurrent_jobs, num_processors)

    # Use ThreadPoolExecutor to manage the execution of commands
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent_jobs) as executor:
        futures = [executor.submit(run_command_anal, cmd) for cmd in commandsAnal]
        concurrent.futures.wait(futures)
