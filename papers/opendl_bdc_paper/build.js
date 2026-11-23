// Builds the Word manuscript of the second direct lending paper from blocks.json (parse.py)
const fs = require("fs");
const d = require("docx");
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, AlignmentType, BorderStyle,
        Footer, PageNumber, ImageRun, ShadingType, FootnoteReferenceRun } = d;
const B = JSON.parse(fs.readFileSync("blocks.json", "utf8"));
const FONT = "Times New Roman";
const W = 9026;                         // A4 text width at 1-inch margins (DXA)
const runs = (rs, o = {}) => rs.map(r => new TextRun({ text: r.t, bold: r.b || o.bold, italics: r.i || o.italics, font: FONT, size: o.size || 24 }));
const P = (opts) => new Paragraph(opts);
const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const line = { style: BorderStyle.SINGLE, size: 6, color: "000000" };
function table(rows) {
  const n = rows[0].length;
  const first = n >= 8 ? 1000 : Math.min(2600, Math.round(W * (n > 4 ? 0.24 : 0.34)));
  const rest = Math.floor((W - first) / (n - 1));
  const widths = [first, ...Array(n - 1).fill(rest)];
  widths[n - 1] += W - widths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: W, type: WidthType.DXA }, columnWidths: widths,
    rows: rows.map((r, ri) => new TableRow({
      tableHeader: ri === 0, cantSplit: true,
      children: r.map((c, ci) => new TableCell({
        width: { size: widths[ci], type: WidthType.DXA },
        borders: { top: ri === 0 ? line : none, bottom: (ri === 0 || ri === rows.length - 1) ? line : none, left: none, right: none },
        margins: { top: 40, bottom: 40, left: 60, right: 60 },
        children: [P({ keepNext: ri < rows.length - 1, alignment: ci === 0 ? AlignmentType.LEFT : AlignmentType.CENTER,
          children: [new TextRun({ text: c, bold: ri === 0, font: FONT, size: 18 })] })]
      }))
    }))
  });
}
const kids = []; let fnText = "";
for (const b of B) {
  switch (b.type) {
    case "title": kids.push(P({ alignment: AlignmentType.CENTER, spacing: { before: 1200, after: 360 },
      children: [new TextRun({ text: b.text, bold: true, font: FONT, size: 32 })] })); break;
    case "footnote": fnText = b.text; break;
    case "author": kids.push(P({ alignment: AlignmentType.CENTER, spacing: { after: 60 },
      children: [new TextRun({ text: b.text, font: FONT, size: 26 }), new FootnoteReferenceRun(1)] })); break;
    case "affil": kids.push(P({ alignment: AlignmentType.CENTER, spacing: { after: 60 }, children: [new TextRun({ text: b.text, font: FONT, size: 24 })] })); break;
    case "date": kids.push(P({ alignment: AlignmentType.CENTER, spacing: { after: 480 }, children: [new TextRun({ text: b.text, font: FONT, size: 24 })] })); break;
    case "abstract_h": kids.push(P({ alignment: AlignmentType.CENTER, spacing: { before: 240, after: 120 }, keepNext: true,
      children: [new TextRun({ text: "Abstract", bold: true, font: FONT, size: 24 })] })); break;
    case "meta": kids.push(P({ spacing: { before: 120, after: 60 }, indent: { left: 567, right: 567 }, children: runs(b.runs, { size: 22 }) })); break;
    case "h1": kids.push(P({ pageBreakBefore: ["1. Introduction", "References"].includes(b.text), spacing: { before: 360, after: 160 }, keepNext: true,
      children: [new TextRun({ text: b.text, bold: true, font: FONT, size: 26 })] })); break;
    case "h2": kids.push(P({ spacing: { before: 240, after: 120 }, keepNext: true,
      children: [new TextRun({ text: b.text, bold: true, italics: true, font: FONT, size: 24 })] })); break;
    case "para": {
      const isAbstract = kids.length && kids.some(k => k === kids[kids.length - 1]) && B.indexOf(b) > 0 && B[B.indexOf(b) - 1].type === "abstract_h";
      kids.push(P({ alignment: AlignmentType.JUSTIFIED, spacing: { after: 160, line: isAbstract ? 300 : 360 },
        indent: isAbstract ? { left: 567, right: 567 } : undefined, children: runs(b.runs, { size: isAbstract ? 22 : 24 }) })); break; }
    case "caption": kids.push(P({ spacing: { before: 240, after: 120 }, keepNext: true, children: runs(b.runs, { size: 20 }) })); break;
    case "table": kids.push(table(b.rows)); break;
    case "note": kids.push(P({ alignment: AlignmentType.JUSTIFIED, spacing: { before: 80, after: 240 }, children: runs(b.runs, { size: 18 }) })); break;
    case "image": kids.push(P({ alignment: AlignmentType.CENTER, spacing: { before: 200, after: 80 }, keepNext: true,
      children: [new ImageRun({ type: "png", data: fs.readFileSync(b.path), transformation: { width: 600, height: 233 },
        altText: { title: "Figure 1", description: "Loans marked below 90 and below 80", name: "Figure 1" } })] })); break;
    case "figcaption": kids.push(P({ alignment: AlignmentType.JUSTIFIED, spacing: { after: 240 }, children: runs(b.runs, { size: 18 }) })); break;
    case "reference": kids.push(P({ alignment: AlignmentType.LEFT, spacing: { after: 100 }, indent: { left: 567, hanging: 567 }, children: runs(b.runs, { size: 22 }) })); break;
  }
}
const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: 24 } } } },
  footnotes: { 1: { children: [P({ children: [new TextRun({ text: fnText, font: FONT, size: 18 })] })] } },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [P({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 20 })] })] }) },
    children: kids
  }]
});
Packer.toBuffer(doc).then(buf => { fs.writeFileSync("Private_Credit_Valuations_from_Public_BDC_Filings.docx", buf); console.log("written"); });
