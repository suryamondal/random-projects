import subprocess
import os
import glob
import shlex

# List of IPL teams you want to loop over
teams = [
    # "Royal Challengers Bengaluru",
    # "Punjab Kings",
    # "Mumbai Indians",
    # "Sunrisers Hyderabad",
    # "Chennai Super Kings",
    # "Rajasthan Royals",
    # "Lucknow Super Giants",
    "Delhi Capitals",
    # "Gujarat Titans",
    "Kolkata Knight Riders"
]

def run_plot_for_team(team_name):
    print(f"\n\n\n🔄 Running for team: {team_name}")
    cmd = f'root -l -q \'plot_stats.C("{team_name}")\''
    subprocess.run(cmd, shell=True)

def stitch_pdfs_for_team(team_name):
    plot_dir = "plots"
    bat_pdf = os.path.join(plot_dir, f"{team_name} Bat.pdf")
    bowl_pdf = os.path.join(plot_dir, f"{team_name} Bowl.pdf")
    output_pdf = os.path.join(plot_dir, f"{team_name}.pdf")
    cropped_pdf = os.path.join(plot_dir, f"{team_name}_cropped.pdf")
    if os.path.exists(bat_pdf) and os.path.exists(bowl_pdf):
        print(f"🧵 Stitching PDFs for: {team_name}")
        cmd = ["pdfjam", "--nup", "1x2", "--landscape", bat_pdf, bowl_pdf, "-o", output_pdf]
        subprocess.run(cmd)
        print(f"✂️ Cropping PDF for: {team_name}")
        crop_cmd = ["pdfcrop", output_pdf, cropped_pdf]
        subprocess.run(crop_cmd)
        # Replace original with cropped version
        os.replace(cropped_pdf, output_pdf)
        # Remove the Bat and Bowl PDFs
        print(f"🧹 Cleaning up: {team_name} Bat/Bowl PDFs")
        os.remove(bat_pdf)
        os.remove(bowl_pdf)
    else:
        print(f"⚠️ Missing Bat or Bowl PDF for {team_name}")

def stitch_pair(team1, team2):
    plot_dir = "plots"
    team1_pdf = os.path.join(plot_dir, f"{team1}.pdf")
    team2_pdf = os.path.join(plot_dir, f"{team2}.pdf")
    combined_pdf = os.path.join(plot_dir, f"{team1} - {team2}.pdf")
    temp_combined = os.path.join(plot_dir, f"{team1} - {team2}_temp.pdf")
    if os.path.exists(team1_pdf) and os.path.exists(team2_pdf):
        print(f"📎 Combining: {team1} + {team2}")
        cmd = ["pdfjam", "--nup", "2x1", team1_pdf, team2_pdf, "-o", temp_combined]
        subprocess.run(cmd)
        print(f"✂️ Cropping combined PDF for: {team1}-{team2}")
        crop_cmd = ["pdfcrop", temp_combined, combined_pdf]
        subprocess.run(crop_cmd)
        os.remove(temp_combined)
        os.remove(team1_pdf)
        os.remove(team2_pdf)
    else:
        print(f"⚠️ Missing final PDFs for {team1} or {team2}")

def stitch_pdfs_for_team_modes(team_name):
    plot_dir = "plots"
    bat_pdf = os.path.join(plot_dir, f"{team_name} Bat Modes.pdf")
    bowl_pdf = os.path.join(plot_dir, f"{team_name} Bowl Modes.pdf")
    output_pdf = os.path.join(plot_dir, f"{team_name} Modes.pdf")
    cropped_pdf = os.path.join(plot_dir, f"{team_name} Modes_cropped.pdf")
    if os.path.exists(bat_pdf) and os.path.exists(bowl_pdf):
        print(f"🧵 Stitching PDFs for: {team_name}")
        cmd = ["pdfjam", "--nup", "1x2", "--landscape", bat_pdf, bowl_pdf, "-o", output_pdf]
        subprocess.run(cmd)
        print(f"✂️ Cropping PDF for: {team_name}")
        crop_cmd = ["pdfcrop", output_pdf, cropped_pdf]
        subprocess.run(crop_cmd)
        # Replace original with cropped version
        os.replace(cropped_pdf, output_pdf)
        # Remove the Bat and Bowl PDFs
        print(f"🧹 Cleaning up: {team_name} Bat/Bowl PDFs")
        os.remove(bat_pdf)
        os.remove(bowl_pdf)
    else:
        print(f"⚠️ Missing Bat or Bowl PDF for {team_name}")

def stitch_pair_modes(team1, team2):
    plot_dir = "plots"
    team1_pdf = os.path.join(plot_dir, f"{team1} Modes.pdf")
    team2_pdf = os.path.join(plot_dir, f"{team2} Modes.pdf")
    combined_pdf = os.path.join(plot_dir, f"{team1} - {team2} - Modes.pdf")
    temp_combined = os.path.join(plot_dir, f"{team1} - {team2} Modes_temp.pdf")
    if os.path.exists(team1_pdf) and os.path.exists(team2_pdf):
        print(f"📎 Combining: {team1} + {team2}")
        cmd = ["pdfjam", "--nup", "2x1", team1_pdf, team2_pdf, "-o", temp_combined]
        subprocess.run(cmd)
        print(f"✂️ Cropping combined PDF for: {team1}-{team2}")
        crop_cmd = ["pdfcrop", temp_combined, combined_pdf]
        subprocess.run(crop_cmd)
        os.remove(temp_combined)
        os.remove(team1_pdf)
        os.remove(team2_pdf)
    else:
        print(f"⚠️ Missing final PDFs for {team1} or {team2}")

def main():
    # Make sure output directory exists
    if not os.path.exists("plots"):
        os.makedirs("plots")

    for team in teams:
        run_plot_for_team(team)
        stitch_pdfs_for_team(team)
        stitch_pdfs_for_team_modes(team)

    for i in range(0, len(teams) - 1, 2):
        team1 = teams[i]
        team2 = teams[i + 1]
        stitch_pair(team1, team2)
        stitch_pair_modes(team1, team2)

if __name__ == "__main__":
    main()
