import re, json
from pathlib import Path
md=Path("paper2.md").read_text(encoding="utf-8").replace("\r","")
lines=md.split("\n")
def inline(t):
    t=re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", t)
    runs=[]; pos=0
    for m in re.finditer(r"\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+)`", t):
        if m.start()>pos: runs.append({"t":t[pos:m.start()]})
        if m.group(1) is not None: runs.append({"t":m.group(1),"b":True})
        elif m.group(2) is not None: runs.append({"t":m.group(2),"i":True})
        else: runs.append({"t":m.group(3),"i":True})
        pos=m.end()
    if pos<len(t): runs.append({"t":t[pos:]})
    return [r for r in runs if r["t"]]
blocks=[]; para=[]; in_refs=False; first=True
def flush():
    global para
    if para:
        txt=" ".join(x.strip() for x in para).replace("\\*","*")
        typ="reference" if in_refs else "para"
        if txt.startswith("*Notes:*"): typ="note"
        if txt.startswith("*JEL classification:*") or txt.startswith("*Keywords:*"): typ="meta"
        blocks.append({"type":typ,"runs":inline(txt)})
        para=[]
i=0
while i<len(lines):
    l=lines[i]; s=l.strip()
    if s.startswith("# ") and first:
        blocks.append({"type":"title","text":s[2:]}); first=False
        # author, affiliation, date, footnote
        rest=[x.strip() for x in lines[i+1:i+12] if x.strip()]
        blocks.append({"type":"author","text":rest[0].rstrip("\\*").rstrip("*")})
        blocks.append({"type":"affil","text":rest[1]}); blocks.append({"type":"date","text":rest[2]})
        # footnote: all lines of the paragraph that starts with "\*"
        k=i+1
        while not lines[k].strip().startswith("\\*"): k+=1
        fl=[]
        while lines[k].strip():
            fl.append(lines[k].strip()); k+=1
        fn=" ".join(fl).lstrip("\\*").lstrip("*").strip()
        blocks.append({"type":"footnote","text":fn})
        # skip to Abstract
        while not lines[i].startswith("## Abstract"): i+=1
        continue
    if s=="":
        flush(); i+=1; continue
    if s.startswith("## "):
        flush(); h=s[3:]
        if h=="Abstract": blocks.append({"type":"abstract_h"})
        else:
            in_refs = (h=="References")
            blocks.append({"type":"h1","text":h})
        i+=1; continue
    if s.startswith("### "):
        flush(); blocks.append({"type":"h2","text":s[4:]}); i+=1; continue
    if s=="{{FIGURE1}}":
        flush(); blocks.append({"type":"image","path":"figure1.png"})
        blocks.append({"type":"figcaption","runs":[{"t":"Figure 1. ","b":True},{"t":"Loans marked below 90 and below 80, in % of estimated cost, by quarter-end. Left: loans in European currencies held by direct lending BDCs (OpenDL Europe). Right: US dollar loans of the same BDCs (OpenDL US BDC), constructed with the same method."}]})
        i+=1; continue
    m=re.match(r"^\*\*(Table \d+\.)\s*(.+)\*\*$", s)
    if m:
        flush(); blocks.append({"type":"caption","runs":[{"t":m.group(1)+" ","b":True},{"t":m.group(2),"b":True}]}); i+=1; continue
    if s.startswith("|"):
        flush(); rows=[]
        while i<len(lines) and lines[i].strip().startswith("|"):
            r=[c.strip() for c in lines[i].strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?",c) for c in r): rows.append(r)
            i+=1
        blocks.append({"type":"table","rows":rows}); continue
    para.append(l); i+=1
flush()
Path("blocks.json").write_text(json.dumps(blocks,ensure_ascii=False,indent=0),encoding="utf-8")
print(len(blocks), sorted(set(b["type"] for b in blocks)))
