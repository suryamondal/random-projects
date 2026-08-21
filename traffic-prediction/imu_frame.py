#!/usr/bin/env python3
"""Derive the vehicle axes from a phone IMU recording, in phone coordinates.

A phone wedged in a door pocket sits at an arbitrary angle, so its x/y/z mean
nothing on their own. Two physical references recover the vehicle frame without
any assumption about how the phone was placed:

  z (up)      the accelerometer's median reading at rest IS the up direction —
              at rest it senses the reaction to gravity, magnitude ~9.8.
  y (forward) during STRAIGHT-LINE BRAKING the horizontal acceleration points
              backwards along the vehicle axis, so forward is its negative.
              Braking is selected from GPS deceleration, and "straight" from a
              small yaw rate (gyro projected on z), so corners cannot pollute it.
  x (lateral) the cross product y x z, then the frame is orthonormalised.

Writes data/<stem>_frame.json with the rotation matrix R whose ROWS are the
vehicle x/y/z in phone coordinates, so a_vehicle = R @ a_phone.

Two validations are printed and stored, and both should be checked before
trusting a frame:
  * longitudinal channel vs GPS acceleration  (expect r > ~0.7)
  * lateral channel vs yaw_rate x speed       (expect |r| > ~0.5; a NEGATIVE r
    just means the sensor's yaw sign is opposite, not that the frame is wrong —
    negate x if you want positive lateral in a right turn)

Usage:
    python3 imu_frame.py sensors/<recording>.zip
"""

import argparse
import io
import json
import os
import zipfile

import numpy as np

import analyze_imu as ai

DIR = os.path.dirname(os.path.abspath(__file__))


def gyro(path, t):
    """Gyroscope resampled onto the accelerometer timebase (rad/s)."""
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            f = io.TextIOWrapper(z.open("Gyroscope.csv"))
            g = np.genfromtxt(f, delimiter=",", names=True)
    else:
        g = np.genfromtxt(os.path.join(path, "Gyroscope.csv"),
                          delimiter=",", names=True)
    return np.vstack([np.interp(t, g["seconds_elapsed"], g[c]) for c in "xyz"])


def derive(path, min_decel=0.8, max_yaw=0.05, min_kmh=15.0):
    loc, imu = ai.load(path)
    t, A = imu["t"], imu["A"]
    fs = 1 / np.median(np.diff(t))

    g0 = np.median(A, axis=1)
    z_up = g0 / np.linalg.norm(g0)

    dyn = A - g0[:, None]
    horiz = dyn - z_up[:, None] * (z_up[:, None] * dyn).sum(0)
    yaw = (gyro(path, t) * z_up[:, None]).sum(0)

    v = np.interp(t, loc["t"], np.convolve(loc["kmh"], np.ones(3) / 3, mode="same"))
    ag = np.interp(t, loc["t"],
                   np.gradient(np.convolve(loc["kmh"] / 3.6, np.ones(3) / 3,
                                           mode="same"), loc["t"]))
    k = int(0.5 * fs)
    ker = np.ones(k) / k
    hs = np.vstack([np.convolve(h, ker, mode="same") for h in horiz])
    yaw_s = np.convolve(np.abs(yaw), ker, mode="same")

    sel = (v > min_kmh) & (ag < -min_decel) & (yaw_s < max_yaw)
    if sel.sum() < 200:
        raise SystemExit(f"only {sel.sum()} straight-braking samples; "
                         "loosen --min-decel or record a longer drive")
    back = hs[:, sel].mean(axis=1)
    y_fwd = -back / np.linalg.norm(back)
    y_fwd = y_fwd - (y_fwd @ z_up) * z_up
    y_fwd /= np.linalg.norm(y_fwd)
    x_lat = np.cross(y_fwd, z_up)
    x_lat /= np.linalg.norm(x_lat)
    R = np.vstack([x_lat, y_fwd, z_up])

    lon = np.convolve((dyn * y_fwd[:, None]).sum(0), ker, mode="same")
    lat = np.convolve((dyn * x_lat[:, None]).sum(0), ker, mode="same")
    cent = np.convolve(yaw * v / 3.6, ker, mode="same")
    mv = v > 10
    return dict(R=R.tolist(), g_mag=float(np.linalg.norm(g0)),
                n_brake_samples=int(sel.sum()),
                brake_seconds=float(sel.sum() / fs),
                r_longitudinal=float(np.corrcoef(lon[mv], ag[mv])[0, 1]),
                r_lateral=float(np.corrcoef(lat[mv], cent[mv])[0, 1]),
                det=float(np.linalg.det(R)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rec")
    ap.add_argument("--min-decel", type=float, default=0.8,
                    help="GPS deceleration (m/s^2) that counts as braking")
    ap.add_argument("--max-yaw", type=float, default=0.05,
                    help="max |yaw rate| (rad/s) for 'straight' (default ~3 deg/s)")
    args = ap.parse_args()
    out = derive(args.rec, args.min_decel, args.max_yaw)
    R = np.array(out["R"])
    print(f"|g| = {out['g_mag']:.3f} m/s2    straight-braking used: "
          f"{out['n_brake_samples']} samples ({out['brake_seconds']:.0f} s)")
    for row, nm in zip(R, ("x lateral", "y forward", "z up      ")):
        print(f"  {nm}  [{row[0]:+.4f} {row[1]:+.4f} {row[2]:+.4f}]")
    print(f"  det = {out['det']:+.6f}   (+1 = proper right-handed rotation)")
    print(f"validation: r(longitudinal, GPS accel) = {out['r_longitudinal']:+.3f}"
          f"   r(lateral, yaw x speed) = {out['r_lateral']:+.3f}")
    stem = os.path.splitext(os.path.basename(args.rec.rstrip("/")))[0]
    os.makedirs(os.path.join(DIR, "data"), exist_ok=True)
    p = os.path.join(DIR, "data", f"{stem}_frame.json")
    json.dump(out, open(p, "w"), indent=2)
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
