import subprocess
import os
import glob
import shlex

# List of IPL teams you want to loop over
teams = [
    # "Royal Challengers Bengaluru",
    # "Punjab Kings",
    "Mumbai Indians",
    "Chennai Super Kings",
    # "Sunrisers Hyderabad",
    # "Rajasthan Royals",
    # "Lucknow Super Giants",
    # "Delhi Capitals",
    # "Gujarat Titans"
]

def run_plot_for_team(team_name):
    print(f"🔄 Running for team: {team_name}")
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
        cmd = [
            "pdfjam",
            "--nup", "2x1",
            "--landscape",
            bat_pdf,
            bowl_pdf,
            "-o", output_pdf
        ]
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

def main():
    # Make sure output directory exists
    if not os.path.exists("plots"):
        os.makedirs("plots")

    for team in teams:
        run_plot_for_team(team)
        stitch_pdfs_for_team(team)

if __name__ == "__main__":
    main()
