# YouTube Views Logger

This repository logs the view counts of selected YouTube videos over time and generates plots to visualize the trends. It's useful for tracking video performance, research, or archiving purposes.

---------------------------------------------------------------------

Project Structure:

.
├── data/             # Directory to store CSV logs of view data
├── grep_script.py    # Script to periodically execute log_data.py
├── log_data.py       # Script that logs views of selected YouTube videos
├── plots/            # Directory to save generated plots
├── plot_views.C      # ROOT macro for plotting view trends
├── run_plot.py       # Wrapper script to generate plots and compile PDF
└── README.md         # This file

---------------------------------------------------------------------

How It Works:

1. Logging Views:
   - `log_data.py` contains a list of YouTube video IDs or URLs.
   - It fetches the current view count and saves it to a CSV file in `data/`.

2. Scheduling Logs:
   - Use `grep_script.py` to run `log_data.py` at regular intervals (e.g., using cron).
   - This builds a time series of views over time.

3. Plotting:
   - `run_plot.py` reads a list of tags, runs `plot_views.C` for each, and creates plots.
   - All plots are saved in `plots/` and combined into a single PDF report.

---------------------------------------------------------------------

Setup Instructions:

1. Requirements:
   - Python 3.x
   - ROOT (https://root.cern/)

2. Clone the Repository:
   $ git clone https://github.com/yourusername/youtube-views-logger.git
   $ cd youtube-views-logger

3. Install Dependencies (if needed):
   $ pip install -r requirements.txt

---------------------------------------------------------------------

Usage:

1. Manually Log Data:
   $ python3 grep_script.py

3. Generate Plots:
   $ python3 run_plot.py

   This will:
   - Generate plots for each tag
   - Save them in the `plots/` directory
   - Create a combined PDF of all plots

---------------------------------------------------------------------

Customization:

- Modify the list of videos in `log_data.py`.
- Edit the tags in `run_plot.py` to group plots by video.
- Make sure `plot_views.C` works with your ROOT setup.

---------------------------------------------------------------------

License:

MIT License. See the LICENSE file for more information.

---------------------------------------------------------------------
