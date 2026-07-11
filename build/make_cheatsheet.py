#!/usr/bin/env python3
"""Generate cheatsheet.pdf -- a printable analog backup of the frozen board,
tuned for a 14-team, 0-PPR draft. Tiered, color-coded, with VOR / ADP / flags."""
import json, os
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                Spacer, PageBreak)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
board = json.load(open(os.path.join(ROOT, "board.json")))
P = board["players"]; M = board["meta"]

POSC = {"QB": colors.HexColor("#e85d75"), "RB": colors.HexColor("#1f9d6b"),
        "WR": colors.HexColor("#2f7fd6"), "TE": colors.HexColor("#d98a1f"),
        "K": colors.HexColor("#777"), "DST": colors.HexColor("#777")}

styles = getSampleStyleSheet()
h = ParagraphStyle('h', parent=styles['Heading1'], fontSize=15, spaceAfter=2)
sub = ParagraphStyle('s', parent=styles['Normal'], fontSize=8, textColor=colors.grey)
sech = ParagraphStyle('sec', parent=styles['Heading2'], fontSize=11, spaceBefore=8, spaceAfter=3)
note = ParagraphStyle('n', parent=styles['Normal'], fontSize=7.5, textColor=colors.HexColor("#444"), leading=10)

doc = SimpleDocTemplate(os.path.join(ROOT, "cheatsheet.pdf"), pagesize=letter,
                        topMargin=0.4*inch, bottomMargin=0.4*inch,
                        leftMargin=0.4*inch, rightMargin=0.4*inch)
story = []
story.append(Paragraph("Draft Day Cheat Sheet — 14-Team Standard (0 PPR)", h))
story.append(Paragraph(f"Built {M['built']} · Source: {M['source']} · "
                       f"Replacement pts: " + ", ".join(f"{k} {v}" for k,v in M['replacement_pts'].items()), sub))
story.append(Spacer(1, 6))


def tbl(rows, header):
    data = [header] + rows
    t = Table(data, colWidths=[0.4*inch, 1.5*inch, 0.45*inch, 0.42*inch,
                               0.42*inch, 0.42*inch, 0.4*inch, 1.85*inch], repeatRows=1)
    sty = [('FONTSIZE',(0,0),(-1,-1),7.5),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
           ('BACKGROUND',(0,0),(-1,0),colors.HexColor("#222")),('TEXTCOLOR',(0,0),(-1,0),colors.white),
           ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor("#f4f6f9")]),
           ('GRID',(0,0),(-1,-1),0.25,colors.HexColor("#dde2e8")),
           ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2)]
    t.setStyle(TableStyle(sty))
    return t


# Overall top 60 by ECR
hdr = ['ECR','Player','Pos','VOR','ADP','vADP','Bye','Flags']
rows = []
for p in sorted(P, key=lambda x: x['ecr'])[:60]:
    rows.append([p['ecr'], p['name'], p['pos_rank'], p['vor'] if p['vor'] is not None else '',
                 p['adp'] or '', (f"+{p['value_vs_adp']}" if (p['value_vs_adp'] or 0)>0 else (p['value_vs_adp'] if p['value_vs_adp'] is not None else '')),
                 p['bye'] or '', " ".join(p['flags']+p.get('strategy',[]))])
story.append(Paragraph("Overall Top 60 (consensus order)", sech))
story.append(tbl(rows, hdr))
story.append(PageBreak())

# Per-position tiered
for pos in ['RB','WR','QB','TE']:
    grp = [p for p in P if p['pos']==pos and p.get('proj_pts') is not None]
    grp.sort(key=lambda x: (-(x['proj_pts'] or 0)))
    story.append(Paragraph(f"{pos} — tiered ({M['strategy_notes'][pos]})", sech))
    rows=[]; last=None
    for p in grp:
        if p['pos_tier']!=last:
            rows.append(['', f"— TIER {p['pos_tier']} —", '', '', '', '', '', ''])
            last=p['pos_tier']
        rows.append([p['ecr'], p['name'], p['pos_rank'], p['vor'] if p['vor'] is not None else '',
                     p['adp'] or '', (f"+{p['value_vs_adp']}" if (p['value_vs_adp'] or 0)>0 else (p['value_vs_adp'] if p['value_vs_adp'] is not None else '')),
                     p['bye'] or '', " ".join(p['flags']+p.get('strategy',[]))])
    story.append(tbl(rows, hdr))
    story.append(Spacer(1,6))

story.append(Paragraph("VALUE = falls past ADP (draft him) · REACH = crowd takes him early · "
                       "CEILING = wide range of outcomes (late-round upside) · SAFE = tight consensus floor. "
                       "VOR = projected points over your league's replacement level — the higher, the more scarce/valuable in standard scoring.", note))

doc.build(story)
print("Wrote cheatsheet.pdf")
