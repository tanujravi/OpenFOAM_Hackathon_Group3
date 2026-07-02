#!/usr/bin/env python3
"""
make_maps.py -- spatial maps for the Guimaraes air-quality report.

Builds two figures from the provided data + the receptor results:
  map_pollution.png   road network (line width ~ pollutant emission), the S3 reduced
                      corridor highlighted, and reference receptor concentrations.
  map_scenarios.png   receptor concentrations for reference/S1/S2/S3 on a shared scale.

Inputs (all via CLI, no hard-coded paths):
  --repo     repo root (has traffic/ and road_ids_reduction.txt)
  --disp     a dispersion case dir (uses constant/triSurface/receptors.json for coords)
  --report   dir with receptor_summary.csv (from make_report.py)
  --pollutant  pollutant to map (default NOx); --out output dir.

Usage:
  python3 make_maps.py --repo .. --disp ../dispersionCaseBig \
      --report results_pod/report --pollutant NOx --out results_pod/report/figs
"""
import argparse, csv, json, os, re
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

LBL={"receptor1":"Public Hospital","receptor2":"F. Holanda",
     "receptor3":"M. Sarmento","receptor4":"S. Simoes"}

def grab_tier(txt,key):
    m=re.search(rf"{key}%\s*reduction.*?\[([^\]]*)\]",txt,re.S|re.I)
    return set(int(t) for t in re.findall(r"\d+",m.group(1))) if m else set()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo",required=True)
    ap.add_argument("--disp",required=True)
    ap.add_argument("--report",required=True)
    ap.add_argument("--pollutant",default="NOx")
    ap.add_argument("--geojson",default=None,help="road geojson (default traffic/out_CO.geojson)")
    ap.add_argument("--out",required=True)
    a=ap.parse_args(); os.makedirs(a.out,exist_ok=True)
    P=a.pollutant

    gj=a.geojson or os.path.join(a.repo,"traffic","out_CO.geojson")
    feats=json.load(open(gj))["features"]
    geom={f["properties"]["geo_id"]: np.array(f["geometry"]["coordinates"])[:,:2] for f in feats}
    rows=[r for r in csv.reader(open(os.path.join(a.repo,"traffic",f"emission_factor_per_segment_{P}.csv"))) ][1:]
    emis={i:sum(float(x) for x in r) for i,r in enumerate([r for r in rows if r and r[0]!=""])}
    emax=max(emis.values()) or 1.0
    txt=open(os.path.join(a.repo,"road_ids_reduction.txt")).read()
    corridor=grab_tier(txt,"50")|grab_tier(txt,"30")
    rj=json.load(open(os.path.join(a.disp,"constant","triSurface","receptors.json")))
    rc={r["id"]:r["centroid_utm"][:2] for r in rj}
    st={}
    for r in csv.DictReader(open(os.path.join(a.report,"receptor_summary.csv"))):
        st[(r["scenario"],r["pollutant"],r["receptor"])]=float(r["mean_ugm3"])
    RECEP=sorted(rc)
    scen_present=sorted({s for (s,p,rk) in st}, key=lambda s:(s!="reference",s))

    def draw_network(ax):
        base=[geom[i] for i in geom if i not in corridor]
        ax.add_collection(LineCollection(base,colors="#9aa3ad",
            linewidths=[0.25+2.6*emis.get(i,0)/emax for i in geom if i not in corridor],zorder=1))
        ax.add_collection(LineCollection([geom[i] for i in corridor if i in geom],colors="#1f6fd6",
            linewidths=[1.0+2.6*emis.get(i,0)/emax for i in corridor if i in geom],zorder=2))
        ax.set_aspect("equal"); ax.axis("off")
        xs=np.concatenate([g[:,0] for g in geom.values()]); ys=np.concatenate([g[:,1] for g in geom.values()])
        ax.set_xlim(xs.min()-150,xs.max()+150); ax.set_ylim(ys.min()-150,ys.max()+150)
        x0,y0=xs.min()+100,ys.min()+60
        ax.plot([x0,x0+1000],[y0,y0],"k-",lw=2,zorder=5); ax.text(x0+500,y0+45,"1 km",ha="center",fontsize=8)

    # Figure 1
    fig,ax=plt.subplots(figsize=(9,7.6)); draw_network(ax)
    vals=[st[("reference",P,rk)] for rk in RECEP]
    sc=ax.scatter([rc[rk][0] for rk in RECEP],[rc[rk][1] for rk in RECEP],c=vals,s=420,
                  cmap="YlOrRd",edgecolor="black",linewidth=1.4,zorder=6,vmin=0)
    for rk in RECEP:
        dx,ha=((-12,"right") if rk==RECEP[-1] else (10,"left"))
        ax.annotate(f"{LBL.get(rk,rk)}\n{st[('reference',P,rk)]:.1f}",(rc[rk][0],rc[rk][1]),
            xytext=(dx,8),textcoords="offset points",ha=ha,fontsize=8.5,fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.2",fc="white",ec="none",alpha=0.75),zorder=7)
    cb=fig.colorbar(sc,ax=ax,shrink=0.6,pad=0.01); cb.set_label(f"receptor {P} mean [ug/m3]")
    ax.legend(handles=[Line2D([0],[0],color="#9aa3ad",lw=3,label=f"road network (width ~ {P} emission)"),
                       Line2D([0],[0],color="#1f6fd6",lw=3,label="S3 Metro-Bus reduced corridor")],
              loc="upper right",fontsize=8,framealpha=0.9)
    ax.set_title(f"Guimaraes road network and {P} exposure at the four receptors (reference)",fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(a.out,"map_pollution.png"),dpi=150); plt.close(fig)

    # Figure 2
    vmax=max(st[("reference",P,rk)] for rk in RECEP)
    n=len(scen_present); cols=2; rowsN=(n+1)//2
    fig,axes=plt.subplots(rowsN,cols,figsize=(11,4.5*rowsN),squeeze=False)
    axf=axes.ravel()
    for ax,scn in zip(axf,scen_present):
        draw_network(ax)
        v=[st[(scn,P,rk)] for rk in RECEP]
        sc=ax.scatter([rc[rk][0] for rk in RECEP],[rc[rk][1] for rk in RECEP],c=v,s=300,
                      cmap="YlOrRd",vmin=0,vmax=vmax,edgecolor="black",linewidth=1.2,zorder=6)
        for rk in RECEP:
            ax.annotate(f"{st[(scn,P,rk)]:.1f}",(rc[rk][0],rc[rk][1]),xytext=(6,6),
                        textcoords="offset points",fontsize=8,fontweight="bold",zorder=7)
        ax.set_title(scn,fontsize=11)
    for k in range(n,len(axf)): axf[k].axis("off")
    fig.colorbar(sc,ax=axes.ravel().tolist(),shrink=0.5,label=f"receptor {P} mean [ug/m3]")
    fig.suptitle(f"{P} at the four receptors by scenario (same colour scale)",fontsize=12)
    fig.savefig(os.path.join(a.out,"map_scenarios.png"),dpi=150,bbox_inches="tight"); plt.close(fig)
    print("wrote map_pollution.png, map_scenarios.png ->", a.out)

if __name__=="__main__": main()
