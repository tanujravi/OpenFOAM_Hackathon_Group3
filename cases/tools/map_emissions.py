#!/usr/bin/env python3
"""
Map per-segment hourly emission factors to per-segment source values, with the
mobility-scenario scaling applied. This is the scenario-implementation core
(reference / S1 / S2 / S3) and is mesh-independent.

Inputs (provided data, read-only):
  traffic/emission_factor_per_segment_CO.csv    196 rows x 24 hourly cols
  traffic/emission_factor_per_segment_NOx.csv
  road_ids_reduction.txt                        S3 tiers (50%-list, 30%-list)

Row order == segment order == road_segments.csv order. Road ID == 0-based row
index (IDs in road_ids_reduction.txt go up to 192 < 196 -> consistent; validate
once before trusting S3).

Scenario scaling (per CLAUDE.md):
  reference : x1.0 everywhere
  S1        : x0.8 everywhere   (20% of gas vehicles -> EV)
  S2        : x0.6 everywhere   (40% -> EV)
  S3        : x0.5 on the 50%-list, x0.7 on the 30%-list, x1.0 elsewhere (Metro Bus)

NOTE on units: the CSV value is a per-segment hourly emission rate (NOT the g/km
EF). Converting to a wall fixedGradient (kg/(m^2 s)) needs (a) the rate's physical
unit [OPEN] and (b) the carved street-face area per segment [needs the mesh].
This tool outputs the SCALED emission per segment in the CSV's own units; the
flux conversion is applied later by set_emissions.py once area + unit are fixed.

Usage:
  python map_emissions.py --pollutant CO --hour 0 --scenario S3
  python map_emissions.py --pollutant NOx --hour 8 --scenario reference --out geo/em.txt
  python map_emissions.py --check         # validate row counts + S3 id ranges
"""
import argparse, csv, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SCEN_FLAT = {"reference": 1.0, "S1": 0.8, "S2": 0.6}


def load_factors(pollutant):
    p = os.path.join(ROOT, "traffic", f"emission_factor_per_segment_{pollutant}.csv")
    with open(p, newline="") as f:
        rows = list(csv.reader(f))
    header = [c.strip() for c in rows[0]]
    data = [[float(x) for x in r] for r in rows[1:] if r and r[0] != ""]
    return header, data


def load_s3_tiers():
    """Parse the two ID lists from road_ids_reduction.txt."""
    txt = open(os.path.join(ROOT, "road_ids_reduction.txt")).read()
    import re
    # split on the two headers; grab bracketed integer lists
    blocks = re.split(r"(?i)(50%|30%)\s*reduction", txt)
    tiers = {"50": set(), "30": set()}
    # re-walk: find "50% reduction" / "30% reduction" then the next [...] list
    for key in ("50", "30"):
        m = re.search(rf"{key}%\s*reduction.*?\[([^\]]*)\]", txt, re.S | re.I)
        if m:
            ids = [int(t) for t in re.findall(r"\d+", m.group(1))]
            tiers[key] = set(ids)
    return tiers["50"], tiers["30"]


def scenario_scale(scenario, n_segments):
    """Return a list of per-segment multipliers."""
    if scenario in SCEN_FLAT:
        return [SCEN_FLAT[scenario]] * n_segments
    if scenario == "S3":
        list50, list30 = load_s3_tiers()
        sc = []
        for i in range(n_segments):
            if i in list50:
                sc.append(0.5)
            elif i in list30:
                sc.append(0.7)
            else:
                sc.append(1.0)
        return sc
    sys.exit(f"ERROR: unknown scenario '{scenario}' (use reference/S1/S2/S3)")


def hour_column(header, hour):
    labels = header  # 24 hourly labels
    s = str(hour).strip()
    if s.isdigit():
        i = int(s)
        if not 0 <= i < len(labels):
            sys.exit(f"ERROR: hour index {i} out of range 0..{len(labels)-1}")
        return i
    norm = s.replace(" ", "")
    for i, lab in enumerate(labels):
        if lab.replace(" ", "") == norm:
            return i
    sys.exit(f"ERROR: hour '{hour}' not in {labels}")


def do_check():
    ok = True
    for pol in ("CO", "NOx"):
        header, data = load_factors(pol)
        msg = "OK" if (len(data) == 196 and len(header) == 24) else "MISMATCH"
        if msg != "OK":
            ok = False
        print(f"{pol}: {len(data)} segments x {len(header)} hours -> {msg}")
    l50, l30 = load_s3_tiers()
    print(f"S3 tiers: 50%-list={len(l50)} ids (max {max(l50)}), "
          f"30%-list={len(l30)} ids (max {max(l30)})")
    overlap = l50 & l30
    print(f"  tier overlap: {sorted(overlap) if overlap else 'none'}")
    print(f"  all ids < 196 (0-based fits): {max(l50 | l30) < 196}")
    print("CHECK:", "PASS" if ok and not overlap and max(l50 | l30) < 196 else "REVIEW")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pollutant", choices=["CO", "NOx"])
    ap.add_argument("--hour", default=None)
    ap.add_argument("--scenario", default="reference")
    ap.add_argument("--out", default=None)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.check:
        do_check(); return
    if not args.pollutant or args.hour is None:
        sys.exit("ERROR: --pollutant and --hour are required (or use --check)")

    header, data = load_factors(args.pollutant)
    col = hour_column(header, args.hour)
    scale = scenario_scale(args.scenario, len(data))
    scaled = [data[i][col] * scale[i] for i in range(len(data))]

    total_ref = sum(data[i][col] for i in range(len(data)))
    total_scn = sum(scaled)
    n_changed = sum(1 for s in scale if s != 1.0)
    print(f"# pollutant={args.pollutant} hour='{header[col]}' scenario={args.scenario}")
    print(f"# segments={len(scaled)}  changed={n_changed}  "
          f"total {total_ref:.3f} -> {total_scn:.3f} ({100*total_scn/total_ref:.1f}% of ref)")
    if args.out:
        with open(args.out, "w") as f:
            for v in scaled:
                f.write(f"{v:.10g}\n")
        print(f"# wrote {len(scaled)} per-segment values -> {args.out}")
    else:
        print("# (no --out; first 5 scaled values:)", [round(v, 4) for v in scaled[:5]])


if __name__ == "__main__":
    main()
