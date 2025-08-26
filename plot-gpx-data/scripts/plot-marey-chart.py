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
    # Parse the GPX file

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
                    distances.append(total_distance / 1000)  # Convert to kilometers
                    timeStamps.append(point.time.timestamp())
                    prev_point = point

    timeStampsEachSecond = []
    distancesEachSecond = []

    return timeStampsEachSecond, distancesEachSecond

parse_gpx(args.input_gpx)
