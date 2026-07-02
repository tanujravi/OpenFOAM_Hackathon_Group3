#!/usr/bin/env python3
"""
collect_cases.py
================
Scan the OpenFOAM dispersion-run tree and produce, for the linear PODI fit:

  * parameters.csv     one row per (scenario, hour): case,u,v,G,L
  * a staging/ tree     canonical foamToNumpy layout (symlinks, no copying):
        staging/<pollutant>/<case>/exported_data/<field>/<field>_proc_i.npy
        staging/<pollutant>/<case>/exported_data/cellVolumes/...
  * manifest.csv        full record of what was found and linked

All inputs come from a YAML config (default ./config.yaml):
    python3 collect_cases.py [config.yaml]

Then run the surrogate once per pollutant (commands are printed at the end).

Source layout assumed:
    <root>/workflow{,_S1,_S2,_S3}/runs_pod{,_S1,_S2,_S3}/disp/h<N>/<pollutant>/...
where each <pollutant> folder is a foamToNumpy dataDir.
"""
from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required:  pip install pyyaml")


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

def load_config(path: Path) -> dict:
    if not path.is_file():
        sys.exit(f"Config file not found: {path}")
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}

    cfg.setdefault("root", ".")
    cfg.setdefault("out", "collected")
    cfg.setdefault("stage", True)
    cfg.setdefault("hour_base", 0)
    cfg.setdefault("geometry_fields", ["cellVolumes", "cellCentre", "times"])

    if "scenarios" not in cfg or not cfg["scenarios"]:
        sys.exit("config: 'scenarios' mapping is required")
    if "wind" not in cfg or "u" not in cfg["wind"] or "v" not in cfg["wind"]:
        sys.exit("config: 'wind' with 'u' and 'v' lists is required")

    u, v = cfg["wind"]["u"], cfg["wind"]["v"]
    if len(u) != len(v):
        sys.exit(f"config: wind u ({len(u)}) and v ({len(v)}) lengths differ")

    for name, s in cfg["scenarios"].items():
        for key in ("G", "L", "tag"):
            if key not in s:
                sys.exit(f"config: scenario '{name}' missing '{key}'")
    return cfg


# --------------------------------------------------------------------------- #
# Discovery helpers
# --------------------------------------------------------------------------- #

def find_disp(scenario_dir: Path) -> Path | None:
    for pat in ("*/disp", "disp", "*/*/disp"):
        hits = sorted(scenario_dir.glob(pat))
        if hits:
            return hits[0]
    return None


def hour_index(name: str) -> int | None:
    m = re.match(r"^h(\d+)$", name)
    return int(m.group(1)) if m else None


def fields_under(directory: Path) -> dict[str, list[Path]]:
    """Find <field>_proc_<i>.npy under `directory`, skipping processor* trees."""
    out: dict[str, list[Path]] = {}
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if not d.startswith("processor")]
        for fn in filenames:
            m = re.match(r"(.+)_proc_\d+\.npy$", fn)
            if m:
                out.setdefault(m.group(1), []).append(Path(dirpath) / fn)
    for f in out:
        out[f].sort(key=lambda x: int(re.search(r"_proc_(\d+)\.npy$", x.name).group(1)))
    return out


def link_field(proc_files: list[Path], dst_field_dir: Path) -> None:
    dst_field_dir.mkdir(parents=True, exist_ok=True)
    for src in proc_files:
        link = dst_field_dir / src.name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(src.resolve())


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.yaml")
    cfg = load_config(config_path)

    root = Path(cfg["root"])
    out = Path(cfg["out"])
    hour_base = int(cfg["hour_base"])
    do_stage = bool(cfg["stage"])
    geometry = set(cfg["geometry_fields"])
    scenarios = cfg["scenarios"]
    u_tab, v_tab = cfg["wind"]["u"], cfg["wind"]["v"]
    n_cols = len(u_tab)
    time_label = [f"{(7 + i) % 24:02d}:00-{(8 + i) % 24:02d}:00" for i in range(n_cols)]

    out.mkdir(parents=True, exist_ok=True)
    stage_root = out / "staging"

    param_rows: list[dict] = []
    manifest_rows: list[dict] = []
    seen_cases: set[str] = set()
    pollutant_cases: dict[str, set[str]] = {}
    detected_fields: dict[str, set[str]] = {}
    missing_volumes: list[str] = []

    for scen, s in scenarios.items():
        G, L, tag = float(s["G"]), float(s["L"]), str(s["tag"])
        sdir = root / scen
        if not sdir.is_dir():
            print(f"[skip] scenario folder not found: {sdir}")
            continue
        disp = find_disp(sdir)
        if disp is None:
            print(f"[warn] no 'disp' under {sdir}")
            continue
        print(f"[scan] {scen}  (G={G}, L={L})  ->  {disp}")

        for hdir in sorted(disp.glob("h*"),
                           key=lambda d: hour_index(d.name) if hour_index(d.name) is not None else 999):
            hidx = hour_index(hdir.name)
            if hidx is None or not hdir.is_dir():
                continue
            col = (hidx + hour_base) % n_cols
            u, v = u_tab[col], v_tab[col]
            case = f"{tag}_{hdir.name}"

            if case not in seen_cases:
                param_rows.append({"case": case, "u": u, "v": v, "G": G, "L": L})
                seen_cases.add(case)

            for pol_dir in [d for d in sorted(hdir.iterdir())
                            if d.is_dir() and d.name not in geometry]:
                pol = pol_dir.name
                search_dir = pol_dir / "exported_data"
                if not search_dir.is_dir():
                    search_dir = pol_dir
                fields = fields_under(search_dir)
                conc = sorted(f for f in fields if f not in geometry)
                has_vol = "cellVolumes" in fields
                detected_fields.setdefault(pol, set()).update(conc)
                pollutant_cases.setdefault(pol, set()).add(case)
                if not has_vol:
                    missing_volumes.append(f"{case}/{pol}")

                if do_stage:
                    ed = stage_root / pol / case / "exported_data"
                    for fname, files in fields.items():
                        link_field(files, ed / fname)

                manifest_rows.append({
                    "case": case, "pollutant": pol, "u": u, "v": v, "G": G, "L": L,
                    "hour_folder": hdir.name, "wind_column": col, "time": time_label[col],
                    "fields": ";".join(conc) if conc else "(none)",
                    "cellVolumes": "yes" if has_vol else "NO",
                    "source": str(pol_dir.resolve()),
                })

    # ---- write CSVs ------------------------------------------------------- #
    param_rows.sort(key=lambda r: r["case"])
    with open(out / "parameters.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["case", "u", "v", "G", "L"])
        w.writeheader()
        w.writerows(param_rows)

    if manifest_rows:
        cols = ["case", "pollutant", "u", "v", "G", "L", "hour_folder",
                "wind_column", "time", "fields", "cellVolumes", "source"]
        with open(out / "manifest.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(manifest_rows)

    # ---- report ----------------------------------------------------------- #
    print("\n================ SUMMARY ================")
    print(f"cases (scenario x hour): {len(param_rows)}")
    by_scen: dict[str, int] = {}
    for r in param_rows:
        t = r["case"].rsplit("_h", 1)[0]
        by_scen[t] = by_scen.get(t, 0) + 1
    for tag, n in by_scen.items():
        print(f"  {tag:5s}: {n} hours")
    for pol, cases in pollutant_cases.items():
        print(f"pollutant '{pol}': {len(cases)} cases, field name(s) -> {sorted(detected_fields.get(pol, []))}")
    if missing_volumes:
        print(f"[warn] cellVolumes NOT found for {len(missing_volumes)} case(s); "
              f"volume-weighted POD will fail. First few: {missing_volumes[:3]}")
    print(f"\nWrote: {out/'parameters.csv'}, {out/'manifest.csv'}")
    if do_stage:
        print(f"Staging: {stage_root}/<pollutant>/<case>/exported_data/...")
    print("\nVerify the wind assignment in manifest.csv (time column) before fitting.")
    print("Then, per pollutant:")
    for pol in sorted(pollutant_cases):
        flds = sorted(detected_fields.get(pol, [pol]))
        fld = flds[0] if flds else pol
        print(f"  python3 podi_linear.py --cases-dir {stage_root}/{pol} "
              f"--parameters {out/'parameters.csv'} --field {fld}")


if __name__ == "__main__":
    main()
