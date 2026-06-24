#!/usr/bin/env python3
"""
Inject the hourly reference wind into a simpleFoam case's 0/U.

The provided wind (wind_data/wind_velocity_time.csv) is one spatially-uniform
(u, v) per hour, 24 bins running 07:00 -> 07:00. It is a horizontal vector, so
in the recentred frame it is unchanged (pure translation is direction-preserving)
-> we write (u, v, 0) directly.

For the chosen hour this rewrites, in <case>/0/U:
  * the inletOutlet 'freestreamValue uniform (...)' line   (the BC marker)
  * the 'internalField   uniform (...)' line                (initial condition)

Usage:
  python set_wind.py --list                       # print the 24-hour table, change nothing
  python set_wind.py --hour 0                      # set hour index 0 (07:00-08:00)
  python set_wind.py --hour "12:00 - 13:00"        # set by column label
  python set_wind.py --hour 9 --case path/to/case  # explicit case dir

Designed to be called by the orchestration once per hour, per scenario (the wind
field is identical across the four scenarios -- only emissions differ later).
"""
import argparse, csv, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CASE = os.path.join(os.path.dirname(HERE), "initialCase")


def load_wind(csv_path):
    """Return (labels, us, vs) from the time/u/v CSV."""
    with open(csv_path, newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    labels = [c.strip() for c in header[1:]]
    data = {r[0].strip().lower(): [float(x) for x in r[1:]] for r in rows[1:] if r}
    if "u" not in data or "v" not in data:
        sys.exit(f"ERROR: expected 'u' and 'v' rows in {csv_path}, got {list(data)}")
    return labels, data["u"], data["v"]


def resolve_index(hour, labels):
    """Accept an integer index (0-23) or an exact/loose column label."""
    if hour is None:
        return None
    s = str(hour).strip()
    if re.fullmatch(r"\d+", s):
        i = int(s)
        if not 0 <= i < len(labels):
            sys.exit(f"ERROR: hour index {i} out of range 0..{len(labels)-1}")
        return i
    norm = s.replace(" ", "")
    for i, lab in enumerate(labels):
        if lab.replace(" ", "") == norm:
            return i
    sys.exit(f"ERROR: hour label '{hour}' not found. Labels: {labels}")


def met(u, v):
    """Speed and meteorological 'from' direction (deg, 0=N, 90=E) for reporting."""
    spd = math.hypot(u, v)
    frm = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
    return spd, frm


def print_table(labels, us, vs):
    print(f"{'idx':>3}  {'hour':<14} {'u(m/s)':>8} {'v(m/s)':>8} {'speed':>7} {'from(deg)':>9}")
    for i, lab in enumerate(labels):
        spd, frm = met(us[i], vs[i])
        print(f"{i:>3}  {lab:<14} {us[i]:>8.3f} {vs[i]:>8.3f} {spd:>7.3f} {frm:>9.0f}")


def set_wind(u_path, u, v):
    with open(u_path) as f:
        txt = f.read()
    vec = f"({u:.6f} {v:.6f} 0)"

    # 1) freestreamValue line (carries the HOURLY WIND marker)
    new, n1 = re.subn(
        r"(freestreamValue\s+uniform\s+)\([^)]*\)",
        rf"\g<1>{vec}", txt, count=1)
    # 2) internalField line -> same vector (initial condition)
    new, n2 = re.subn(
        r"(internalField\s+uniform\s+)\([^)]*\)",
        rf"\g<1>{vec}", new, count=1)

    if n1 != 1:
        sys.exit(f"ERROR: did not find a 'freestreamValue uniform (...)' line in {u_path}")
    if n2 != 1:
        sys.exit(f"ERROR: did not find an 'internalField uniform (...)' line in {u_path}")
    with open(u_path, "w") as f:
        f.write(new)
    return vec


def main():
    ap = argparse.ArgumentParser(description="Inject hourly wind into 0/U.")
    ap.add_argument("--case", default=DEFAULT_CASE, help="OpenFOAM case dir (has 0/U)")
    ap.add_argument("--wind-csv", default=None,
                    help="wind CSV (default: <case>/../wind_data/wind_velocity_time.csv)")
    ap.add_argument("--hour", default=None, help="hour index 0-23 or column label")
    ap.add_argument("--list", action="store_true", help="print the 24-hour table only")
    args = ap.parse_args()

    wind_csv = args.wind_csv or os.path.join(
        os.path.dirname(os.path.abspath(args.case)), "wind_data", "wind_velocity_time.csv")
    labels, us, vs = load_wind(wind_csv)

    if args.list or args.hour is None:
        print(f"# wind source: {wind_csv}")
        print_table(labels, us, vs)
        if args.hour is None and not args.list:
            print("\n(no --hour given; nothing written)")
        return

    i = resolve_index(args.hour, labels)
    u_path = os.path.join(args.case, "0", "U")
    if not os.path.isfile(u_path):
        sys.exit(f"ERROR: {u_path} not found")
    vec = set_wind(u_path, us[i], vs[i])
    spd, frm = met(us[i], vs[i])
    print(f"hour[{i}] {labels[i]}: set 0/U freestreamValue + internalField = {vec}"
          f"  (speed {spd:.2f} m/s, from {frm:.0f} deg)")


if __name__ == "__main__":
    main()
