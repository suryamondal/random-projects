import subprocess
import os
import glob

tags = [
    "Classic_Cickroll",
    "Aqua_Barbie",
    "Veritasium_Broke_Math",
    "Veritasium_Strange_Trust_Quantum",
    "Veritasium_Mistake_Einstein",
    "Dhruv_Rathee_Trump_Tariff",
    "Linus_Tech_Malaysia_Tech_Mall",
    "Tom_Schott_Aerial_Ropeway"
]


def run_merge():
    print("🔄 Running pdftk")
    output_file = 'plots/all.pdf'
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
