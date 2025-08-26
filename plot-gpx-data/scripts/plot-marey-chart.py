import basf2 as b2
import gpxpy
import gpxpy.gpx
import argparse

# from ROOT import TH1F

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--input-gpx", type=str, nargs="+",
                    default=["text.gpx"], help="input GPX file(s)")
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
        print(timeStampsEachSecond[-1], distancesEachSecond[-1])

    return timeStampsEachSecond, distancesEachSecond


parse_gpx(sorted(args.input_gpx))
