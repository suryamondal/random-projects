import basf2 as b2
import gpxpy
import gpxpy.gpx
import argparse
import json
import datetime

import ROOT
# from ROOT import TH1F

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--input-gpx", type=str, default="test.json",
                    help="names of input GPX file(s) in json set.")
args = parser.parse_args()
b2.B2INFO(f"Steering file args = {args}")


def parse_gpx(file_paths):
    timeStamps = []
    distances = []

    for file_path in file_paths:
        with open(file_path, 'r') as gpx_file:
            gpx = gpxpy.parse(gpx_file)

        # Extract time and calculate cumulative distance
        prev_point = None
        total_distance = 0

        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    if prev_point:
                        # Calculate distance in meters
                        total_distance += point.distance_3d(prev_point)
                    if point.time:
                        distances.append(total_distance / 1000)  # km
                        timeStamps.append(int(point.time.timestamp()))  # round to sec
                    prev_point = point

    if not timeStamps:
        return [], []

    # Align distances at each second (padding with last known value)
    start_time = min(timeStamps)
    end_time = max(timeStamps)

    timeStampsEachSecond = []
    distancesEachSecond = []

    last_distance = 0.0
    idx = 0
    n = len(timeStamps)

    for t in range(start_time, end_time + 1):
        # Advance index while there are new measurements
        while idx < n and timeStamps[idx] == t:
            last_distance = distances[idx]
            idx += 1

        # Store padded value
        timeStampsEachSecond.append(t)  # relative seconds
        distancesEachSecond.append(last_distance)
        # print(timeStampsEachSecond[-1], distancesEachSecond[-1])

    return timeStampsEachSecond, distancesEachSecond


with open(args.input_gpx, "r") as f:
    input_json = json.load(f)
track_list = input_json["Tracks"]

mg = ROOT.TMultiGraph()

dataPointsToPlot = []
first_dt = None
for track in track_list:
    dataPointsToPlot.append(parse_gpx(sorted(track)))
    if not dataPointsToPlot[0]:
        continue
    first_time = datetime.datetime.fromtimestamp(dataPointsToPlot[-1][0][0])
    if not first_dt or first_dt > first_time:
        first_dt = first_time
first_midnight = first_dt.replace(hour=0, minute=0, second=0, microsecond=0)

gcnt = 1
for timeStampsEachSecond, distancesEachSecond in dataPointsToPlot:
    if not timeStampsEachSecond:
        continue

    # Convert to C-style arrays
    n = len(timeStampsEachSecond)
    g = ROOT.TGraph(n)
    g.SetMarkerStyle(20)
    g.SetMarkerSize(0)
    g.SetMarkerColor(gcnt)
    g.SetLineWidth(2)
    g.SetLineColor(gcnt)
    gcnt += 1

    # get midnight of first timestamp
    this_first_dt = datetime.datetime.fromtimestamp(timeStampsEachSecond[0])
    this_midnight = this_first_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    this_midnight_ts = int(this_midnight.timestamp())

    # fill the graph
    for i in range(n):
        sec_of_day = timeStampsEachSecond[i] - this_midnight_ts + int(first_midnight.timestamp())
        g.SetPoint(i, sec_of_day, distancesEachSecond[i])

    mg.Add(g, "L")

mg.SetNameTitle("marey", "marey")
mg.Draw("A")
xaxis = mg.GetXaxis()
xaxis.SetTimeDisplay(1)
xaxis.SetTimeFormat("%H:%M:%S")
mg.SaveAs("test.root")
