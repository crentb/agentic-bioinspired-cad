"""
abcad/reporting/mission_control.py — static HTML mission-control dashboard for agentic-bioinspired-cad.

Aggregates the program's evidence records into ONE self-contained, local HTML page (no server,
no external requests — sovereignty-preserving): the damage-tolerance ranking (TM-3), the
fracture-toughness results (TM-6), print certification status, loop-convergence history, and the
generator families. Key result plots are embedded as base64 so the file is fully portable.

INPUTS (all relative to the output root: $ABCAD_OUT, default ./out, or --root DIR)
    damage_tolerance_v05/*/damage_tolerance.json   TM-3 ranking of record (0.5 mm voxel, AMG solver)
    tm6/tm6_result.json, tm6_jintegral_result.json, tm6_bouligand_result.json, tm6/*.png
    print_audit*/print_audit.csv                    TM-2 print certification tables
    agent_runs/*/run_manifest.json                  design-loop run manifests
    Missing inputs are skipped; the page renders whatever records exist.

OUTPUT
    <root>/mission_control.html   (open in a browser); a one-line summary on stdout.

Run:  python -m abcad.reporting.mission_control [--root DIR]
"""

from __future__ import annotations

import argparse
import base64
import csv
import glob
import json
import os
from datetime import datetime

# Output root: ./out under the working directory unless ABCAD_OUT points elsewhere. The dashboard
# reads its evidence from, and writes its HTML into, this directory (never the package directory).
_OUT_ROOT = os.environ.get("ABCAD_OUT", "out")


def load_json(p):
    """Parse a JSON file, or return None when it is missing or unreadable."""
    try:
        return json.load(open(p))
    except Exception:
        return None


def embed_png(path):
    """Base64 data-URI of a PNG so the HTML is self-contained; '' if missing."""
    if not os.path.exists(path):
        return ""
    b = open(path, "rb").read()
    return "data:image/png;base64," + base64.b64encode(b).decode()


# ---------------------------------------------------------------- TM-3 ranking
def tm3_rows(root):
    """Rank the 0.5 mm damage-tolerance records by floor margin (min retention - (1 - mean dose))."""
    rows = []
    for f in sorted(glob.glob(os.path.join(root, "damage_tolerance_v05/*/damage_tolerance.json"))):
        d = load_json(f)
        if not d:
            continue
        reps = d.get("samples", [])
        rets = [r["retention"] for r in reps]
        if not rets:
            continue
        doses = [r["removed_rod_frac"] for r in reps]
        mn, dose = min(rets), sum(doses) / len(doses)
        rows.append(
            {
                "part": f.split("/")[-2],
                "E": d["intact_E_eff_MPa"],
                "hex": reps[0].get("n_hex", 0),
                "min_ret": mn,
                "margin": mn - (1 - dose),
            }
        )
    return sorted(rows, key=lambda r: -r["margin"])


# ---------------------------------------------------------------- print status
def print_rows(root):
    """Collect the FDM verdicts from every print-audit CSV, one row per file."""
    rows = []
    for csvf in sorted(glob.glob(os.path.join(root, "print_audit*/print_audit.csv"))):
        for r in csv.DictReader(open(csvf)):
            rows.append(
                {
                    "file": r["file"],
                    "bbox": r.get("bbox_x_mm", "?"),
                    "watertight": r.get("watertight", "?"),
                    "verdict": r.get("verdict_fdm", "?"),
                }
            )
    # dedupe by filename, prefer a PRINT verdict
    best = {}
    for r in rows:
        k = r["file"]
        if k not in best or (r["verdict"] == "PRINT" and best[k]["verdict"] != "PRINT"):
            best[k] = r
    return list(best.values())


# ---------------------------------------------------------------- loop runs
def loop_rows(root):
    """Summarize each design-loop run manifest: approved? printable artifact?"""
    rows = []
    for f in sorted(glob.glob(os.path.join(root, "agent_runs/*/run_manifest.json"))):
        d = load_json(f)
        if not d:
            continue
        manu = d.get("manufacturability") or {}
        scaled = (manu.get("deep_audit") or {}).get("autoscaled_variant") or {}
        rows.append(
            {
                "run": f.split("/")[-2],
                "approved": d.get("approved") or d.get("ever_approved"),
                "printable": manu.get("printable") or scaled.get("verdict") == "PRINT",
            }
        )
    return rows


def cell(v):
    """Render a boolean-ish value as a check / dash table cell."""
    if v is True:
        return '<span class="ok">✓</span>'
    if v is False or v is None:
        return '<span class="no">–</span>'
    return str(v)


def build_html(root):
    """Assemble the dashboard HTML from the records under ``root``; returns (html, counts)."""
    tm3 = tm3_rows(root)
    tm6 = load_json(os.path.join(root, "tm6/tm6_result.json")) or {}
    tm6j = load_json(os.path.join(root, "tm6/tm6_jintegral_result.json")) or {}
    tm6b = load_json(os.path.join(root, "tm6/tm6_bouligand_result.json")) or {}
    prints = print_rows(root)
    loops = loop_rows(root)

    tm3_html = "".join(
        f"<tr><td>{r['part']}</td><td>{r['E']:.0f}</td><td>{r['hex']:,}</td>"
        f"<td>{r['min_ret']:.3f}</td><td class='{'no' if r['margin']<-0.02 else 'ok'}'>{r['margin']:+.3f}</td></tr>"
        for r in tm3
    )

    tm6_angles = tm6.get("angles_deg", [])
    tm6_work = tm6.get("work_of_fracture", [])
    tm6_html = ""
    if tm6_angles:
        wr = tm6.get("work_ratio_max_min", 0)
        tm6_html = (
            # Wording follows the corrected reading of the archived sweep (docs/FRACTURE.md):
            # the work window closes before the aligned specimens peak, so the work ratio
            # tracks initial stiffness; J at initiation is the toughness measure.
            f"<p>Work to a common displacement <b>peaks at {tm6.get('peak_angle_deg','?')}°</b> "
            f"({wr:.2f}× the aligned minimum), a stiffness-weighted measure: the window closes "
            f"before the aligned specimens reach peak load. J at crack initiation peaks at "
            f"{tm6j.get('peak_angle',tm6j.get('peak_Jc_angle','?'))}° "
            f"({tm6j.get('Jc_ratio',tm6j.get('Jc_ratio_max_min',0)):.2f}× max/min across angles); "
            f"the J-integral reproduces the closed-form K benchmark to "
            f"{tm6j.get('benchmark_error_pct','?')}%.</p>"
        )

    boul_html = ""
    if tm6b:
        boul_html = (
            "<table><tr><th>pitch °/ply</th><th>tortuosity</th><th>twist amp</th></tr>"
            + "".join(
                f"<tr><td>{k}</td><td>{v['tortuosity']:.2f}</td><td>{v['twist_amp']:.2f}</td></tr>"
                for k, v in sorted(tm6b.items(), key=lambda kv: int(kv[0]))
            )
            + "</table>"
        )

    prints_html = "".join(
        f"<tr><td>{r['file']}</td><td>{cell(r['watertight']=='True')}</td>"
        f"<td class='{'ok' if r['verdict']=='PRINT' else ''}'>{r['verdict']}</td></tr>"
        for r in prints
    )

    loops_html = "".join(
        f"<tr><td>{r['run']}</td><td>{cell(r['approved'])}</td><td>{cell(r['printable'])}</td></tr>"
        for r in loops
    )

    conv = sum(1 for r in loops if r["printable"])  # runs that ended with a printable artifact

    # embed the key result plots
    imgs = {
        "TM-6 toughness vs angle": embed_png(os.path.join(root, "tm6/tm6_toughness_vs_angle.png")),
        "TM-6 J-integral": embed_png(os.path.join(root, "tm6/tm6_jintegral_vs_angle.png")),
        "Stage D — crack deflection (rod angle steers the crack)": embed_png(
            os.path.join(root, "tm6/tm6_stageD_deflection.png")
        ),
        "Bouligand coupons — crack twisting": embed_png(
            os.path.join(root, "tm6/tm6_bouligand_twist.png")
        ),
        "Woven: fea_small vs full lattice": embed_png(os.path.join(root, "tm6/woven_compare.png")),
    }
    imgs_html = "".join(
        f"<figure><figcaption>{t}</figcaption><img src='{u}'></figure>"
        for t, u in imgs.items()
        if u
    )

    # Self-contained page: inline CSS only (light/dark via prefers-color-scheme), no scripts.
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agentic-bioinspired-cad — Mission Control</title>
<style>
:root {{ color-scheme: light dark; --bg:#fbfbfd; --fg:#1c1c1e; --card:#fff; --line:#e3e3e8;
        --ok:#1a7f37; --no:#c0392b; --accent:#6a0dad; --mut:#6b6b70; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161618; --fg:#e6e6e8; --card:#1f1f22;
        --line:#33333a; --ok:#3fb950; --no:#f85149; --accent:#bb86fc; --mut:#9a9aa0; }} }}
* {{ box-sizing:border-box; }}
body {{ font:15px/1.5 -apple-system,system-ui,sans-serif; background:var(--bg); color:var(--fg);
        margin:0; padding:0 4vw 4rem; }}
header {{ padding:2rem 0 1rem; border-bottom:2px solid var(--accent); margin-bottom:1.5rem; }}
h1 {{ margin:0; font-size:1.7rem; }} h2 {{ margin:2rem 0 .6rem; font-size:1.2rem; }}
.sub {{ color:var(--mut); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:1rem; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:1.1rem 1.2rem; }}
.big {{ font-size:2rem; font-weight:700; }} .accent {{ color:var(--accent); }}
table {{ border-collapse:collapse; width:100%; margin:.4rem 0; font-size:14px; }}
th,td {{ text-align:left; padding:.4rem .6rem; border-bottom:1px solid var(--line); }}
th {{ color:var(--mut); font-weight:600; }} td:not(:first-child),th:not(:first-child) {{ text-align:right; }}
.ok {{ color:var(--ok); font-weight:600; }} .no {{ color:var(--no); }}
.scroll {{ overflow-x:auto; }}
figure {{ margin:1rem 0; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:1rem; }}
figcaption {{ color:var(--mut); font-size:13px; margin-bottom:.5rem; }}
img {{ max-width:100%; height:auto; border-radius:6px; }}
code {{ background:var(--line); padding:.1rem .35rem; border-radius:4px; font-size:13px; }}
</style></head><body>
<header>
  <h1>agentic-bioinspired-cad — Mission Control</h1>
  <div class="sub">Single-material, damage-tolerant, printable architectures · generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</header>

<div class="grid">
  <div class="card"><div class="sub">Loop convergences (certified artifact)</div><div class="big accent">{conv}</div></div>
  <div class="card"><div class="sub">Generator families</div><div class="big">3</div><div class="sub">woven · helicoidal · enamel</div></div>
  <div class="card"><div class="sub">TM-6 J-integral vs closed-form K</div><div class="big accent">{tm6j.get('benchmark_error_pct', '?')}%</div><div class="sub">benchmark error (validation gate)</div></div>
  <div class="card"><div class="sub">Architectures ranked (TM-3, 0.5 mm)</div><div class="big">{len(tm3)}</div></div>
</div>

<h2>Damage tolerance — TM-3 ranking (0.5 mm AMG, ranking of record)</h2>
<div class="scroll"><table><tr><th>architecture</th><th>E_eff MPa</th><th>hex</th><th>min retention</th><th>floor margin</th></tr>{tm3_html}</table></div>
<p class="sub">Margin ≈ 0 = continuum-proportional; more negative = load-path-sensitive. The fused woven is the sole real outlier.</p>

<h2>Fracture toughness — TM-6 (MOOSE phase-field, validated)</h2>
{tm6_html}
<p class="sub">Bouligand-coupon crack tortuosity (crack path length / span), driven through each coupon's real ply pitch:</p>
{boul_html}

<h2>Print certification (FDM)</h2>
<div class="scroll"><table><tr><th>file</th><th>watertight</th><th>verdict</th></tr>{prints_html}</table></div>

<h2>Loop convergence history</h2>
<div class="scroll"><table><tr><th>run</th><th>approved</th><th>printable artifact</th></tr>{loops_html}</table></div>

<h2>Results gallery</h2>
{imgs_html}

<p class="sub">Sources (under the output root): <code>damage_tolerance_v05/</code>, <code>tm6/</code>, <code>print_audit*/</code>,
<code>agent_runs/</code>. Curated evidence records and their provenance: <code>results/README.md</code>.</p>
</body></html>"""
    return html, {"tm3": len(tm3), "prints": len(prints), "loops": len(loops), "conv": conv}


def main(argv=None):
    """CLI entry point: build the dashboard from the output root and write mission_control.html."""
    ap = argparse.ArgumentParser(description="Static HTML mission-control dashboard.")
    ap.add_argument(
        "--root",
        default=_OUT_ROOT,
        help="output root holding the evidence records (default: $ABCAD_OUT or ./out)",
    )
    a = ap.parse_args(argv)

    html, n = build_html(a.root)
    out = os.path.join(a.root, "mission_control.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, "w").write(html)
    print(
        f"wrote {out} ({os.path.getsize(out)//1024} KB) — {n['tm3']} ranked, {n['prints']} print parts, "
        f"{n['loops']} loop runs, {n['conv']} convergences"
    )


if __name__ == "__main__":
    main()
