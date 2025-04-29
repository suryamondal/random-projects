import subprocess
import os
import glob

tags = [
    "Aqua_Barbie",
    "Classic_Rickroll",
    "Dhruv_Rathee_Milky_Way",
    "Dhruv_Rathee_Trump_Tariff",
    "Linus_Tech_Clean_Pool",
    "Linus_Tech_Cool_both_Side",
    "Linus_Tech_Dell_Hung_Up",
    "Linus_Tech_Malaysia_Tech_Mall",
    "Shyam_Sharma_National_Herald",
    "Tom_Schott_Aerial_Ropeway",
    "Veritasium_Broke_Math",
    "Veritasium_Mistake_Einstein",
    "Veritasium_Strange_Trust_Quantum"
]


def run_merge():
    print("🔄 Running pdftk")
    output_file = 'plots/all-views.pdf'
    if os.path.exists(output_file):
        os.remove(output_file)
    pdfs = sorted(glob.glob('plots/*.pdf'))
    cmd = ['pdftk'] + pdfs + ['cat', 'output', output_file]
    subprocess.run(cmd)

def run_plot_for_tag(tag):
    print(f"🔄 Running for: {tag}")
    cmd = f'root -l -q \'plot_views.C("{tag}")\''
    subprocess.run(cmd, shell=True)

def main():
    if not os.path.exists("plots"):
        os.makedirs("plots")

    for tag in tags:
        run_plot_for_tag(tag)

    run_merge()

if __name__ == "__main__":
    main()
