import subprocess
import sys

players = [
    "Philip Salt",
    "Virat Kohli",
    "Mayank Agarawal",
    "Rajat Patidar",
    "Liam Livingstone",
    "Jitesh Sharma",
    "Romario Shepherd",
    "Krunal Pandya",
    "Bhuvneshwar Kumar",
    "Yash Dayal",
    "Josh Hazlewood",
    "Priyansh Arya",
    "Josh Inglis",
    "Shreyas Iyer",
    "Nehal Wadhera",
    "Shashank Singh",
    "Marcus Stoinis",
    "Azmatullah Omarzai",
    "Kyle Jamieson",
    "Vijaykumar Vyshak",
    "Arshdeep Singh",
    "Yuzvendra Chahal",
    "Suyash Sharma",
    "Rasikh Dar Salam",
    "Manoj Bhandage",
    "Tim Seifert",
    "Swapnil Singh",
    "Prabhsimran Singh",
    "Xavier Bartlett",
    "Harpreet Brar",
    "Suryansh Shedge",
    "Praveen Dubey"
]

def run_plot_for_players(players):
    # Format players list to C++ initializer list with double quotes
    cpp_players = ",".join([f'"{p}"' for p in players])  # "A","B","C"
    macro = f'plot_stats.C({{{cpp_players}}})'  # e.g. plot_stats.C({"A","B","C"})
    cmd = ['root', '-l', '-b', '-q', macro]
    
    # print(f"▶️ Running: {' '.join(cmd)}")
    sys.exit(subprocess.run(cmd).returncode)

run_plot_for_players(players)
