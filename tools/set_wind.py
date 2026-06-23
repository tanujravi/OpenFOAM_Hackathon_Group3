#!/usr/bin/env python3
"""
Inject the hourly reference wind into a simpleFoam case.

Wind (wind_data/wind_velocity_time.csv) is one (u, v) per hour, 24 bins
07:00 -> 07:00. Two case styles are supported automatically:

  ABL style  (cases/flowCase): 0/include/ABLConditions present ->
      set Uref = |(u,v)|  and  angle = atan2(v,u) [deg]  (flowDir=(cos,sin,0))
      so the atmBoundaryLayerInlet* profile points the right way.

  vector style (freestream / split 0/U): no ABLConditions ->
      set the 'internalField uniform (...)' line and the '// HOURLY WIND' line.

Usage:
  python3 set_wind.py --list
  python3 set_wind.py --case cases/flowCase --hour 0
"""
import argparse, csv, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CASE = os.path.join(os.path.dirname(HERE), "cases", "flowCase")


def load_wind(csv_path):
    with open(csv_path, newline="") as f:
        rows = list(csv.reader(f))
    labels = [c.strip() for c in rows[0][1:]]
    data = {r[0].strip().lower(): [float(x) for x in r[1:]] for r in rows[1:] if r}
    if "u" not in data or "v" not in data:
        sys.exit("ERROR: expected 'u' and 'v' rows in %s" % csv_path)
    return labels, data["u"], data["v"]


def resolve_index(hour, labels):
    s = str(hour).strip()
    if re.fullmatch(r"\d+", s):
        i = int(s)
        if not 0 <= i < len(labels):
            sys.exit("ERROR: hour index %d out of range 0..%d" % (i, len(labels) - 1))
        return i
    norm = s.replace(" ", "")
    for i, lab in enumerate(labels):
        if lab.replace(" ", "") == norm:
            return i
    sys.exit("ERROR: hour '%s' not found. Labels: %s" % (hour, labels))


def met(u, v):
    return math.hypot(u, v), (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


def print_table(labels, us, vs):
    print("%3s  %-14s %8s %8s %7s %9s" % ("idx", "hour", "u(m/s)", "v(m/s)", "speed", "from(deg)"))
    for i, lab in enumerate(labels):
        spd, frm = met(us[i], vs[i])
        print("%3d  %-14s %8.3f %8.3f %7.3f %9.0f" % (i, lab, us[i], vs[i], spd, frm))


def set_abl(abl_path, u, v):
    txt = open(abl_path).read()
    Uref = math.hypot(u, v)
    angle = math.degrees(math.atan2(v, u))    # flowDir=(cos,sin) => (u,v)/|.|
    txt, n1 = re.subn(r"(?m)^(\s*Uref\s+)[-\d.eE+]+;",
                      lambda m: "%s%.6f;" % (m.group(1), Uref), txt, count=1)
    txt, n2 = re.subn(r"(?m)^(\s*angle\s+)[-\d.eE+]+;",
                      lambda m: "%s%.4f;" % (m.group(1), angle), txt, count=1)
    if n1 != 1 or n2 != 1:
        sys.exit("ERROR: could not set Uref/angle in %s (n1=%d n2=%d)" % (abl_path, n1, n2))
    open(abl_path, "w").write(txt)
    return Uref, angle


def set_vector(u_path, u, v):
    txt = open(u_path).read()
    vec = "(%.6f %.6f 0)" % (u, v)
    txt, n_if = re.subn(r"(internalField\s+uniform\s+)\([^)]*\)",
                        lambda m: m.group(1) + vec, txt, count=1)
    txt, n_hw = re.subn(r"[^\n]*//\s*HOURLY WIND[^\n]*",
                        lambda m: re.sub(r"\([^)]*\)", vec, m.group(0), count=1), txt, count=1)
    if n_if != 1 or n_hw != 1:
        sys.exit("ERROR: vector-style markers not found in %s" % u_path)
    open(u_path, "w").write(txt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=DEFAULT_CASE)
    ap.add_argument("--wind-csv", default=None)
    ap.add_argument("--hour", default=None)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    wind_csv = args.wind_csv or os.path.join(
        os.path.dirname(os.path.abspath(args.case)), "..", "wind_data", "wind_velocity_time.csv")
    labels, us, vs = load_wind(wind_csv)

    if args.list or args.hour is None:
        print("# wind source: %s" % wind_csv)
        print_table(labels, us, vs)
        if args.hour is None and not args.list:
            print("\n(no --hour given; nothing written)")
        return

    i = resolve_index(args.hour, labels)
    u, v = us[i], vs[i]
    abl = os.path.join(args.case, "0", "include", "ABLConditions")
    if os.path.isfile(abl):
        Uref, angle = set_abl(abl, u, v)
        print("hour[%d] %s: ABL Uref=%.3f m/s, angle=%.2f deg  (u,v=%.3f,%.3f) -> %s"
              % (i, labels[i], Uref, angle, u, v, abl))
    else:
        u_path = os.path.join(args.case, "0", "U")
        if not os.path.isfile(u_path):
            sys.exit("ERROR: neither ABLConditions nor 0/U found under %s" % args.case)
        set_vector(u_path, u, v)
        spd, frm = met(u, v)
        print("hour[%d] %s: set 0/U vector (%.4f %.4f 0)  (speed %.2f, from %.0f deg)"
              % (i, labels[i], u, v, spd, frm))


if __name__ == "__main__":
    main()
