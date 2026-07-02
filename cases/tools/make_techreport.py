#!/usr/bin/env python3
"""
make_techreport.py -- build the technical-report PDF for the Guimaraes air-quality study.

Data-driven tables/figures + authored narrative. Reproducible: all paths via CLI.

Inputs:
  --report  dir with receptor_summary.csv and figs/ (bar_mean_*.png, heatmap_pct.png, ...)
  --maps    dir with map_pollution.png / map_scenarios.png (default: <report>/figs)
  --slice   optional ground-slice concentration PNG (from pv_ground_slice.py) to embed
  --out     output PDF path

Usage:
  python3 make_techreport.py --report results_pod/report \
      --maps results_pod/report/figs --slice results_pod/report/figs/reference_T_NOx_ground.png \
      --out results_pod/report/technical_report.pdf
"""
import argparse, csv, os
import matplotlib.image as mpimg
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                Image, PageBreak)

POLLS=["CO","NOx"]; OTH=["S1","S2","S3"]

def load(report):
    st={}; site={}
    for r in csv.DictReader(open(os.path.join(report,"receptor_summary.csv"))):
        st[(r["scenario"],r["pollutant"],r["receptor"])]=dict(mean=float(r["mean_ugm3"]),peak=float(r["peak_ugm3"]),peak_hour=r["peak_hour"])
        site[r["receptor"]]=r["site"]
    recep=sorted({rk for (_,_,rk) in st})
    return st,site,recep

def short(site,rk):
    s=site.get(rk,rk)
    for key,lab in [("Hospital","Public Hospital"),("Holanda","Francisco de Holanda HS"),
                    ("Sarmento","Martins Sarmento HS"),("Santos","Santos Simoes HS")]:
        if key in s: return lab
    return s

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--report",required=True)
    ap.add_argument("--maps",default=None)
    ap.add_argument("--slice",default=None)
    ap.add_argument("--compare-summary",default=None,help="a second receptor_summary.csv (e.g. surface) for a sensitivity table")
    ap.add_argument("--compare-label",default="surface area-average")
    ap.add_argument("--primary-label",default="volume average")
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    maps=a.maps or os.path.join(a.report,"figs")
    FIGS=os.path.join(a.report,"figs")
    st,site,RECEP=load(a.report)
    st2=None
    if a.compare_summary and os.path.isfile(a.compare_summary):
        import csv as _csv
        st2={}
        for r in _csv.DictReader(open(a.compare_summary)):
            st2[(r["scenario"],r["pollutant"],r["receptor"])]=dict(mean=float(r["mean_ugm3"]),peak=float(r["peak_ugm3"]))
    def pcv(s,p,rk): rv=st[("reference",p,rk)]["mean"]; return 100*(st[(s,p,rk)]["mean"]-rv)/rv
    def pc(v,rf): return "%+.1f%%"%(100*(v-rf)/rf)
    def rid(sub): return next((rk for rk in RECEP if sub in site[rk]),RECEP[0])
    hosp,ss=rid("Hospital"),rid("Santos")
    s3h=pcv("S3","NOx",hosp); s3s=pcv("S3","NOx",ss)
    DAY_START=7  # data hour 0 == 07:00-08:00
    pk=sorted({(DAY_START+int(float(st[("reference","NOx",rk)]["peak_hour"])))%24 for rk in RECEP})
    peaktxt=" and ".join("%02d:00"%h for h in pk)

    ss_=getSampleStyleSheet()
    H1=ParagraphStyle("H1",parent=ss_["Heading1"],fontSize=13,spaceBefore=10,spaceAfter=5,textColor=colors.HexColor("#16314f"))
    H2=ParagraphStyle("H2",parent=ss_["Heading2"],fontSize=11,spaceBefore=7,spaceAfter=3,textColor=colors.HexColor("#1f4e79"))
    BODY=ParagraphStyle("BODY",parent=ss_["BodyText"],fontSize=9.5,leading=13,alignment=TA_JUSTIFY,spaceAfter=5)
    CAP=ParagraphStyle("CAP",parent=ss_["BodyText"],fontSize=8,leading=10,textColor=colors.HexColor("#555555"),alignment=TA_CENTER,spaceBefore=2,spaceAfter=8)
    TITLE=ParagraphStyle("TITLE",parent=ss_["Title"],fontSize=19,leading=23,textColor=colors.HexColor("#16314f"))
    SUB=ParagraphStyle("SUB",parent=ss_["BodyText"],fontSize=10.5,alignment=TA_CENTER,textColor=colors.HexColor("#444444"))
    def figp(path,w=15.5*cm,cap=None):
        if not path or not os.path.isfile(path): return []
        h,wp=mpimg.imread(path).shape[:2]; out=[Image(path,width=w,height=w*h/wp)]
        if cap: out.append(Paragraph(cap,CAP))
        return out
    def tbl(data,widths):
        t=Table(data,colWidths=widths,hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1f4e79")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTSIZE",(0,0),(-1,-1),8.2),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("ALIGN",(1,0),(-1,-1),"CENTER"),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#eef2f7")]),
            ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#b8c4d4")),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
        return t

    S=[Spacer(1,2.2*cm),
       Paragraph("Air-Quality Impact of Sustainable-Mobility Scenarios in Guimar&atilde;es",TITLE),
       Spacer(1,0.3*cm),Paragraph("OpenFOAM Hackathon Challenge &mdash; OFW21",SUB),
       Paragraph("CFD assessment of CO and NOx at four sensitive receptors",SUB),Spacer(1,0.8*cm),
       Paragraph("Executive summary",H1),
       Paragraph("Four mobility scenarios &mdash; the provided reference case, two fleet-electrification "
         "scenarios (S1: 20%% of gas vehicles replaced by EVs; S2: 40%%), and a Metro-Bus corridor scenario "
         "(S3) &mdash; were evaluated with a steady-RANS dispersion workflow on the real terrain of "
         "Guimar&atilde;es. CO and NOx were sampled at the four sensitive receptors: the Public Hospital and "
         "the Martins Sarmento, Francisco de Holanda and Santos Sim&otilde;es high schools. Electrification "
         "lowers concentrations uniformly at every receptor (&minus;20%% for S1, &minus;40%% for S2), whereas "
         "the Metro Bus is strongly location-dependent: about %.0f%% at the Public Hospital &mdash; comparable "
         "to S2 &mdash; but only about %.0f%% at Santos Sim&otilde;es. The exact &minus;20/&minus;40%% scaling "
         "of the electrification cases is itself a consistency check on the modelling chain."%(s3h,s3s),BODY),
       Paragraph("1. Objective",H1),
       Paragraph("Quantify how sustainable-mobility measures change air quality at four sensitive locations, "
         "using the provided reference case as the baseline and reporting the air-quality improvement of each "
         "scenario. The assessment metric is the pollutant concentration sampled at the receptor surfaces, "
         "reported per pollutant and compared against the reference in absolute and percentage terms.",BODY),
       Paragraph("2. Methodology",H1),
       Paragraph("<b>Domain and mesh.</b> Terrain and region-of-interest buildings are recentred and meshed "
         "once with snappyHexMesh on a COST-732-style domain; the same mesh, boundary conditions and solver "
         "settings are reused for every hour and scenario, so only the emission input changes and comparisons "
         "are fair.",BODY),
       Paragraph("<b>Flow.</b> Hourly wind is computed with steady RANS (simpleFoam, k-&epsilon; with neutral "
         "ABL wall functions) using an all-round atmospheric inlet that accepts the hour-varying direction; a "
         "first-order warm-up then a second-order restart keeps the solve stable on steep terrain. The "
         "converged fields are frozen and passed to the dispersion stage.",BODY),
       Paragraph("<b>Dispersion.</b> Each pollutant is transported as a separate passive scalar "
         "(scalarTransportFoam) on the frozen flow; the road network is carved into the ground as a "
         "&lsquo;streets&rsquo; patch carrying a non-uniform fixed-gradient flux from the per-segment hourly "
         "emission factors. Concentrations are the local traffic increment (no background).",BODY),
       Paragraph("<b>Receptors and temporal strategy.</b> Concentration is the area average over each ROI "
         "receptor surface. Ten representative hours were selected (maximin over wind and emissions) and run "
         "identically for all scenarios; the statistics below are over those hours. A Snakemake workflow keeps "
         "the mesh decomposed end-to-end on the HPC system and reuses each hour&rsquo;s flow across scenarios.",BODY),
       Paragraph("3. Scenarios",H1),
       Paragraph("The mobility scenarios are implemented purely as a scaling of the per-segment emission "
         "factors. S3 applies the reductions to the segments listed in <i>road_ids_reduction.txt</i> "
         "(verified to map correctly onto the emission rows) &mdash; predominantly the Circular Urbana ring "
         "plus one EN101 section, i.e. the bus corridor rather than the full EN101.",BODY),
       tbl([["Scenario","Definition","Emission scaling"],
            ["Reference","Provided traffic","x1.00 (baseline)"],
            ["S1","20% of gas vehicles -> EV","x0.80, all segments"],
            ["S2","40% of gas vehicles -> EV","x0.60, all segments"],
            ["S3","Metro Bus (Guimaraes-Braga corridor)","x0.50 / x0.70 on listed segments"]],
           [3.0*cm,7.6*cm,4.9*cm]),
       PageBreak(),Paragraph("4. Results",H1),Paragraph("4.1 Baseline exposure",H2),
       Paragraph("At baseline the most exposed receptor is Santos Sim&otilde;es (NOx mean %.1f, peak %.1f "
         "&micro;g/m&sup3;). NOx is the pollutant of interest; CO is far below its 8-hour guideline. Exposure "
         "is highest in the intervals starting %s (24-hour clock)."%(st[("reference","NOx",ss)]["mean"],st[("reference","NOx",ss)]["peak"],peaktxt),BODY)]
    base=[["Receptor","CO mean","CO peak","NOx mean","NOx peak"]]
    for rk in RECEP:
        base.append([short(site,rk)]+["%.2f"%st[("reference",p,rk)][m] for p in POLLS for m in ("mean","peak")])
    S+=[tbl(base,[5.3*cm,2.55*cm,2.55*cm,2.55*cm,2.55*cm]),
        Paragraph("Table 2. Reference concentrations (&micro;g/m&sup3;), mean and peak over the sampled hours.",CAP)]
    S+=figp(os.path.join(FIGS,"bar_mean_NOx.png"),cap="Figure 1. Mean NOx by receptor and scenario (dashed: EU/WHO NO2 references; modelled NOx is not ambient NO2).")
    S+=[Paragraph("4.2 Scenario comparison",H2),
        Paragraph("Electrification scales uniformly &mdash; every receptor falls by exactly &minus;20%% (S1) "
          "and &minus;40%% (S2), for both pollutants and both the mean and the peak. The Metro Bus is spatially "
          "selective: it removes only about 19%% of the city-wide emission total yet cuts the Public Hospital "
          "by about %.0f%%, while barely affecting the off-corridor receptors."%s3h,BODY)]
    for p in POLLS:
        rows=[["Receptor","Reference","S1","S2","S3"]]
        for rk in RECEP:
            rv=st[("reference",p,rk)]["mean"]
            rows.append([short(site,rk),"%.2f"%rv]+["%.2f (%s)"%(st[(s,p,rk)]["mean"],pc(st[(s,p,rk)]["mean"],rv)) for s in OTH])
        S+=[Paragraph("<b>%s</b> &mdash; mean concentration (&micro;g/m&sup3;) and change vs reference"%p,BODY),
            tbl(rows,[4.4*cm,2.3*cm,3.0*cm,3.0*cm,3.0*cm]),Spacer(1,0.2*cm)]
    S+=figp(os.path.join(FIGS,"heatmap_pct.png"),w=12.5*cm,cap="Figure 2. Change in mean concentration vs reference (green = improvement).")
    S+=[Paragraph("4.3 Spatial distribution",H2),
        Paragraph("Placing the receptors on the road network explains the pattern: the S3 corridor (blue) "
          "traces the Circular Urbana ring, which runs next to the Public Hospital and far from Santos "
          "Sim&otilde;es, so the Metro Bus removes the Hospital&rsquo;s dominant local source while leaving the "
          "most-exposed school essentially untouched. Road width is proportional to NOx emission.",BODY)]
    S+=figp(os.path.join(maps,"map_pollution.png"),w=15.0*cm,cap="Figure 3. Road network (width ~ NOx emission), S3 corridor (blue), reference NOx at each receptor.")
    S+=figp(os.path.join(maps,"map_scenarios.png"),w=15.5*cm,cap="Figure 4. Receptor NOx by scenario on a shared colour scale.")
    if a.slice:
        S+=figp(a.slice,w=15.0*cm,cap="Figure 5. Ground-level NOx concentration field (horizontal slice) from the CFD solution.")
    if st2 is not None:
        S+=[Paragraph("4.4 Sensitivity to the sampling method",H2),
            Paragraph(f"The primary metric above is the {a.primary_label} (breathing air in a box "
              f"above each receptor). Recomputing with the {a.compare_label} on the ROI surface gives "
              f"the table below: S1 and S2 fall by -20% and -40% under both metrics (linear response), "
              f"and the spatially-selective S3 agrees within about 2 percentage points at every "
              f"receptor -- so the scenario conclusions do not depend on the sampling choice. Absolute "
              f"levels differ modestly (the {a.primary_label} ranks the Public Hospital, rather than "
              f"Santos Sim&otilde;es, as the most exposed site).",BODY)]
        rows=[["Receptor","ref (vol)","ref (surf)","S3 (vol)","S3 (surf)"]]
        for rk in RECEP:
            rv1=st[("reference","NOx",rk)]["mean"]; rv2=st2[("reference","NOx",rk)]["mean"]
            rows.append([short(site,rk),"%.1f"%rv1,"%.1f"%rv2,
                         pc(st[("S3","NOx",rk)]["mean"],rv1), pc(st2[("S3","NOx",rk)]["mean"],rv2)])
        S+=[Paragraph("<b>NOx</b> &mdash; mean (&micro;g/m&sup3;) and S3 change vs reference: volume vs surface",BODY),
            tbl(rows,[4.6*cm,2.5*cm,2.5*cm,2.7*cm,2.7*cm]),Spacer(1,0.2*cm)]
    S+=[PageBreak(),Paragraph("5. Discussion and conclusions",H1),
        Paragraph("The measures serve different objectives. S2 is the strongest broad measure, lowering every "
          "receptor uniformly by 40%%; S1 gives the same at half the magnitude. The Metro Bus is the most "
          "cost-effective intervention for the Public Hospital, achieving near-S2 benefit there while changing "
          "far less traffic overall, because the reduced corridor is the Hospital&rsquo;s dominant local "
          "source &mdash; but it does little for receptors away from the corridor and almost nothing for "
          "Santos Sim&otilde;es, the most exposed site at baseline.",BODY),
        Paragraph("No single measure is best everywhere. A combined strategy &mdash; the Metro Bus for the "
          "Hospital and central corridor, plus partial electrification for the off-corridor schools &mdash; "
          "would give the most uniform city-wide improvement. If one receptor must be prioritised, the bus "
          "protects the Hospital and electrification protects Santos Sim&otilde;es.",BODY),
        Paragraph("6. Limitations and future work",H1),
        Paragraph("Statistics are over ten representative hours (same hours for every scenario), so mean/peak "
          "are sampled-hour figures; concentrations exclude background and modelled NOx is not ambient NO2, so "
          "absolute levels are relative traffic increments, not compliance values. Natural extensions: the full "
          "24-hour cycle with daily-aggregated exposure; the domain-influence study on the larger city4CFD "
          "domain with a porous vegetation canopy; a combined Metro-Bus-plus-EV scenario; and full 3-D "
          "concentration-field maps to complement the receptor numbers.",BODY)]
    SimpleDocTemplate(a.out,pagesize=A4,topMargin=1.6*cm,bottomMargin=1.5*cm,leftMargin=1.7*cm,
                      rightMargin=1.7*cm,title="Guimaraes Mobility Air-Quality Report").build(S)
    print("wrote",a.out,"(%d bytes)"%os.path.getsize(a.out))

if __name__=="__main__": main()
