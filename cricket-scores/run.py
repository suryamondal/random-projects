import subprocess
import os

# List of IPL teams you want to loop over
teams = [
    "Royal Challengers Bengaluru",
    "Punjab Kings",
    # "Mumbai Indians",
    # "Sunrisers Hyderabad",
    # "Rajasthan Royals",
    # "Delhi Capitals"
]

def run_plot_for_team(team_name):
    print(f"🔄 Running for team: {team_name}")
    cmd = f'root -l -q \'plot_stats.C("{team_name}")\''
    subprocess.run(cmd, shell=True)

def main():
    # Make sure output directory exists
    if not os.path.exists("plots"):
        os.makedirs("plots")

    for team in teams:
        run_plot_for_team(team)

if __name__ == "__main__":
    main()
