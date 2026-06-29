#!/usr/bin/env python3
"""
Select N of the 24 hours that best span the day's variability, so a POD basis built
from those hours interpolates the rest accurately (PODI).

Feature per hour: [wind speed, cos(dir), sin(dir), total_CO, total_NOx], each
normalised to [0,1]. Selection = greedy farthest-point sampling (maximin): seed with
the hour farthest from the mean, then repeatedly add the hour whose minimum distance
to the already-chosen set is largest -> maximal coverage of the feature space.

Inputs (repo root): wind_data/wind_velocity_time.csv (u,v rows x 24),
traffic/emission_factor_per_segment_{CO,NOx}.csv (196 x 24).

Usage:
  python3 select_hours.py --n 10
  python3 select_hours.py --n 10 --out ../workflow/selected_hours.txt
"""
import argparse, csv, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))   # tools live in cases/tools


def read_wind(p):
    data = {}
    for r in csv.reader(open(p)):
        if r and r[0].strip().lower() in ("u", "v"):
            data[r[0].strip().lower()] = [float(x) for x in r[1:] if x.strip() != ""]
    return data["u"], data["v"]


def hourly_totals(p):
    rows = list(csv.reader(open(p)))
    data = [[float(x) for x in r] for r in rows[1:] if r and r[0] != ""]
    ncol = len(data[0])
    return [sum(row[h] for row in data) for h in range(ncol)]  # total per hour


def normalise(col):
    lo, hi = min(col), max(col)
    rng = (hi - lo) or 1.0
    return [(x - lo) / rng for x in col]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--wind", default=os.path.join(ROOT, "wind_data", "wind_velocity_time.csv"))
    ap.add_argument("--co", default=os.path.join(ROOT, "traffic", "emission_factor_per_segment_CO.csv"))
    ap.add_argument("--nox", default=os.path.join(ROOT, "traffic", "emission_factor_per_segment_NOx.csv"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    u, v = read_wind(a.wind)
    nh = len(u)
    co = hourly_totals(a.co); nox = hourly_totals(a.nox)
    assert len(co) == nh and len(nox) == nh, "hour count mismatch wind vs emissions"

    spd = [math.hypot(u[h], v[h]) for h in range(nh)]
    ang = [math.atan2(v[h], u[h]) for h in range(nh)]
    cosd = [math.cos(x) for x in ang]
    sind = [math.sin(x) for x in ang]
    feats = list(zip(normalise(spd), normalise(cosd), normalise(sind),
                     normalise(co), normalise(nox)))

    def d2(i, j):
        return sum((feats[i][k] - feats[j][k]) ** 2 for k in range(len(feats[0])))

    # seed: hour farthest from the mean
    mean = [sum(f[k] for f in feats) / nh for k in range(len(feats[0]))]
    seed = max(range(nh), key=lambda i: sum((feats[i][k] - mean[k]) ** 2 for k in range(len(mean))))
    chosen = [seed]
    while len(chosen) < min(a.n, nh):
        nxt = max((i for i in range(nh) if i not in chosen),
                  key=lambda i: min(d2(i, c) for c in chosen))
        chosen.append(nxt)
    chosen.sort()

    print("# selected %d of %d hours (maximin over wind speed/dir + CO/NOx totals)" % (len(chosen), nh))
    print("# idx  speed  dir_deg   totCO     totNOx")
    for h in chosen:
        print("  %2d  %6.3f  %6.1f  %.4g  %.4g" % (h, spd[h], math.degrees(ang[h]) % 360, co[h], nox[h]))
    print("HOURS=" + ",".join(str(h) for h in chosen))
    if a.out:
        with open(a.out, "w") as f:
            f.write(",".join(str(h) for h in chosen) + "\n")
        print("wrote", a.out)


if __name__ == "__main__":
    main()
