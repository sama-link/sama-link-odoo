#!/usr/bin/env python3
"""
SamaLink Security Checklist PDF Generator v2.0
================================================
Scans all custom Odoo addons and generates a comprehensive printable PDF
security checklist for management review meetings.

Key features:
  - Current CRUD shown + empty NEW CRUD checkboxes for decisions
  - Full Groups documentation with editable decision fields
  - Cross-reference matrix: Models x Groups  
  - Sensitive fields with editable access decision

Usage:
    pip install reportlab
    python generate_security_checklist.py

Output:
    SamaLink_Security_Checklist_YYYY-MM-DD.pdf
"""

import os
import csv
import glob
import re
from datetime import datetime
from xml.etree import ElementTree as ET

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, HRFlowable
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ADDONS_DIR = os.path.dirname(os.path.abspath(__file__))
TODAY = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = os.path.join(ADDONS_DIR, f"SamaLink_Security_Checklist_{TODAY}.pdf")

# Brand colours
CLR_PRIMARY   = colors.HexColor("#1B3A5C")
CLR_ACCENT    = colors.HexColor("#2E86C1")
CLR_LIGHT_BG  = colors.HexColor("#EBF5FB")
CLR_WHITE     = colors.white
CLR_ROW_ALT   = colors.HexColor("#F8F9FA")
CLR_BORDER    = colors.HexColor("#BDC3C7")
CLR_HEADER    = colors.HexColor("#1B3A5C")
CLR_WARN      = colors.HexColor("#E74C3C")
CLR_OK        = colors.HexColor("#27AE60")
CLR_SECTION   = colors.HexColor("#D4E6F1")
CLR_NEW_BG    = colors.HexColor("#FEF9E7")  # light yellow for "new" columns
CLR_CHANGE    = colors.HexColor("#F39C12")   # orange for "change" headers

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
_ss = getSampleStyleSheet()

S_TITLE = ParagraphStyle("CTitle", parent=_ss["Title"],
    fontSize=32, leading=38, textColor=CLR_PRIMARY, spaceAfter=10, alignment=TA_CENTER)
S_SUBTITLE = ParagraphStyle("CSub", parent=_ss["Normal"],
    fontSize=14, leading=18, textColor=CLR_ACCENT, spaceAfter=6, alignment=TA_CENTER)
S_SECTION = ParagraphStyle("Sec", parent=_ss["Heading1"],
    fontSize=18, leading=22, textColor=CLR_PRIMARY, spaceBefore=14, spaceAfter=8)
S_BODY = ParagraphStyle("Bd", parent=_ss["Normal"],
    fontSize=9, leading=12, textColor=colors.black)
S_CELL = ParagraphStyle("Cl", parent=_ss["Normal"],
    fontSize=7, leading=9, textColor=colors.black)
S_CELLB = ParagraphStyle("ClB", parent=S_CELL, fontName="Helvetica-Bold")
S_CELLW = ParagraphStyle("ClW", parent=S_CELL, textColor=CLR_WARN, fontName="Helvetica-Bold")
S_CELLG = ParagraphStyle("ClG", parent=S_CELL, textColor=CLR_OK, fontName="Helvetica-Bold")
S_HDR = ParagraphStyle("Hdr", parent=S_CELL, textColor=CLR_WHITE, fontName="Helvetica-Bold", fontSize=6.5)
S_HDR_CHANGE = ParagraphStyle("HdrC", parent=S_HDR, backColor=CLR_CHANGE)
S_NOTE = ParagraphStyle("Nt", parent=_ss["Normal"],
    fontSize=9, leading=12, textColor=colors.HexColor("#555555"), leftIndent=10)
S_REC = ParagraphStyle("Rec", parent=_ss["Normal"],
    fontSize=9, leading=13, textColor=colors.black, leftIndent=12, spaceBefore=2, spaceAfter=2)
S_CELL_EMPTY = ParagraphStyle("ClE", parent=S_CELL, fontSize=8, leading=10)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def P(text, style=S_CELL):
    return Paragraph(str(text), style)

def Phdr(text):
    return Paragraph(str(text), S_HDR)

def Phdr_new(text):
    """Header cell for 'new/desired' columns - orange background."""
    return Paragraph(str(text), S_HDR_CHANGE)

def perm_text(val):
    v = str(val).strip()
    if v == "1":
        return Paragraph("<b>YES</b>", S_CELLG)
    return Paragraph("<b>NO</b>", S_CELLW)

def empty_box():
    """An empty checkbox field for managers to fill in."""
    return Paragraph("[ ]", S_CELL_EMPTY)

def default_tstyle(n_rows):
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), CLR_HEADER),
        ("TEXTCOLOR", (0, 0), (-1, 0), CLR_WHITE),
        ("FONTNAME",  (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",  (0, 0), (-1, 0), 6.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING",    (0, 0), (-1, 0), 5),
        ("GRID",      (0, 0), (-1, -1), 0.4, CLR_BORDER),
        ("VALIGN",    (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING",    (0, 1), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2),
    ]
    for i in range(1, n_rows):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), CLR_ROW_ALT))
    return TableStyle(cmds)


def section_bar(title, subtitle=""):
    content = f"<b>{title}</b>"
    if subtitle:
        content += f"  <font size=7 color='#555'>{subtitle}</font>"
    sty = ParagraphStyle("SB", parent=S_CELL, fontSize=10, leading=13,
        textColor=CLR_PRIMARY, fontName="Helvetica-Bold")
    data = [[Paragraph(content, sty)]]
    t = Table(data, colWidths=[None])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), CLR_SECTION),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("BOX", (0,0), (-1,-1), 0.5, CLR_ACCENT),
    ]))
    return t


# ---------------------------------------------------------------------------
# Scanners
# ---------------------------------------------------------------------------
def discover_addons(base_dir):
    addons = []
    for entry in sorted(os.listdir(base_dir)):
        manifest = os.path.join(base_dir, entry, "__manifest__.py")
        if os.path.isfile(manifest):
            addons.append(entry)
    return addons


def parse_manifest(addon_dir):
    mpath = os.path.join(addon_dir, "__manifest__.py")
    if not os.path.isfile(mpath):
        return {}
    try:
        with open(mpath, "r", encoding="utf-8") as f:
            return eval(f.read(), {"__builtins__": {}})
    except:
        return {}


def parse_access_csv(addon_path):
    csv_path = os.path.join(addon_path, "security", "ir.model.access.csv")
    if not os.path.isfile(csv_path):
        return []
    rows = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("id", "").strip():
                    rows.append(row)
    except:
        pass
    return rows


def parse_groups_xml(addon_path):
    groups = []
    for pattern in ["security/res_groups.xml", "security/*groups*.xml", "security/*group*.xml"]:
        for fpath in glob.glob(os.path.join(addon_path, pattern)):
            try:
                tree = ET.parse(fpath)
                for rec in tree.getroot().iter("record"):
                    if rec.get("model") != "res.groups":
                        continue
                    gid = rec.get("id", "")
                    name = category = ""
                    implied = []
                    menus = []
                    for field in rec.findall("field"):
                        fn = field.get("name")
                        if fn == "name":
                            name = field.text or ""
                        elif fn == "category_id":
                            category = field.get("ref", "")
                        elif fn == "implied_ids":
                            implied = re.findall(r"ref\(['\"](.+?)['\"]\)", field.get("eval", ""))
                        elif fn in ("whitelisted_menu_ids", "menu_access"):
                            menus += re.findall(r"ref\(['\"](.+?)['\"]\)", field.get("eval", ""))
                    groups.append({"id": gid, "name": name, "category": category,
                                   "implied": implied, "menus": menus})
            except:
                pass
    return groups


def parse_record_rules(addon_path):
    rules = []
    for fpath in glob.glob(os.path.join(addon_path, "security", "ir_rule*.xml")):
        try:
            tree = ET.parse(fpath)
            for rec in tree.getroot().iter("record"):
                if rec.get("model") != "ir.rule":
                    continue
                rule = {"id": rec.get("id", ""), "perms": {}}
                for field in rec.findall("field"):
                    fn = field.get("name")
                    if fn == "name":
                        rule["name"] = field.text or ""
                    elif fn == "model_id":
                        rule["model_ref"] = field.get("ref", "")
                    elif fn == "groups":
                        rule["groups"] = re.findall(r"ref\(['\"](.+?)['\"]\)", field.get("eval", ""))
                    elif fn == "domain_force":
                        rule["domain"] = (field.text or "").strip()
                    elif fn.startswith("perm_"):
                        rule["perms"][fn] = field.get("eval", "0")
                if rule.get("name"):
                    rules.append(rule)
        except:
            pass
    return rules


def discover_models(addon_path):
    models_info = []
    mdir = os.path.join(addon_path, "models")
    if not os.path.isdir(mdir):
        return models_info
    for py in glob.glob(os.path.join(mdir, "*.py")):
        if os.path.basename(py) == "__init__.py":
            continue
        try:
            with open(py, "r", encoding="utf-8") as f:
                content = f.read()
            model_names = re.findall(r"_name\s*=\s*['\"](.+?)['\"]", content)
            field_defs = re.findall(
                r"(\w+)\s*=\s*fields\.(Char|Text|Boolean|Integer|Float|Date|Datetime|"
                r"Selection|Many2one|One2many|Many2many|Binary|Html|Monetary|Image)\s*\(", content)
            sensitive_kw = ["salary","wage","bank","password","pin","ssn","iban",
                "identification","passport","certificate","private","emergency",
                "personal","marital","gender","birthday","birth","visa","permit","image","photo"]
            sensitive = [(fn,ft) for fn,ft in field_defs if any(k in fn.lower() for k in sensitive_kw)]
            for mn in model_names:
                models_info.append({"model": mn, "file": os.path.basename(py),
                    "fields": field_defs, "sensitive_fields": sensitive})
        except:
            pass
    return models_info


def discover_views(addon_path):
    views = []
    vdir = os.path.join(addon_path, "views")
    if not os.path.isdir(vdir):
        return views
    for xf in glob.glob(os.path.join(vdir, "*.xml")):
        try:
            tree = ET.parse(xf)
            for rec in tree.getroot().iter("record"):
                if rec.get("model") != "ir.ui.view":
                    continue
                vid = rec.get("id", "")
                vname = vmodel = vtype = ""
                for field in rec.findall("field"):
                    fn = field.get("name")
                    if fn == "name": vname = field.text or ""
                    elif fn == "model": vmodel = field.text or ""
                    elif fn == "type": vtype = field.text or ""
                if not vtype:
                    af = rec.find(".//field[@name='arch']")
                    if af is not None:
                        at = ET.tostring(af, encoding="unicode")
                        for tag,tp in [("<tree","list"),("<list","list"),("<form","form"),
                            ("<kanban","kanban"),("<search","search"),("<calendar","calendar")]:
                            if tag in at:
                                vtype = tp; break
                grps = ""
                af = rec.find(".//field[@name='arch']")
                if af is not None:
                    gf = re.findall(r'groups="([^"]+)"', ET.tostring(af, encoding="unicode"))
                    grps = ", ".join(gf)
                views.append({"file": os.path.basename(xf), "id": vid, "name": vname,
                    "model": vmodel, "type": vtype or "inherit", "groups_in_view": grps})
        except:
            pass
    return views


# ---------------------------------------------------------------------------
# PDF Sections
# ---------------------------------------------------------------------------

def build_cover(story):
    story.append(Spacer(1, 55*mm))
    story.append(Paragraph("SamaLink", S_TITLE))
    story.append(Paragraph("Security & Access Control Checklist", ParagraphStyle(
        "T2", parent=S_TITLE, fontSize=24, leading=30)))
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="60%", thickness=2, color=CLR_ACCENT, spaceAfter=10, spaceBefore=5))
    story.append(Paragraph(f"Document Date: <b>{TODAY}</b>", S_SUBTITLE))
    story.append(Paragraph("Prepared for: Management Review Meeting", S_SUBTITLE))
    story.append(Paragraph("Prepared by: IT / Development Team", S_SUBTITLE))
    story.append(Spacer(1, 12*mm))

    instr = """
    <b>How to use this document:</b><br/><br/>
    Each table shows <b>CURRENT</b> permissions in green/red columns, and has
    <b>yellow "NEW" columns</b> for you to write your desired changes.<br/><br/>
    <b>For each row:</b><br/>
    - If current permissions are OK: write nothing in yellow columns (keeps current).<br/>
    - If you want to change: fill the yellow NEW columns with <b>Y</b> (yes) or <b>N</b> (no).<br/>
    - Use the <b>"Notes"</b> column for any comments or conditions.<br/><br/>
    <b>Legend:</b><br/>
    <font color="#27AE60"><b>YES</b></font> = Permission currently GRANTED  |
    <font color="#E74C3C"><b>NO</b></font> = Permission currently DENIED  |
    <font color="#F39C12">[ ]</font> = Empty field for YOUR decision
    """
    story.append(Paragraph(instr, ParagraphStyle("Ins", parent=S_BODY, fontSize=10,
        leading=14, borderWidth=1, borderColor=CLR_ACCENT, borderPadding=12, backColor=CLR_LIGHT_BG)))
    story.append(PageBreak())


def build_toc(story, addons):
    story.append(Paragraph("Table of Contents", S_SECTION))
    story.append(Spacer(1, 4*mm))
    items = [
        "1. Groups Documentation & Configuration",
        "2. Model Access Rights (Current + New Decision)",
        "3. Cross-Reference Matrix: Models x Groups",
        "4. Record Rules (Row-Level Security)",
        "5. Sensitive Fields & Access Decisions",
        "6. Views Inventory & Field-Level Groups",
        "7. Recommendations & Action Items",
        "8. Meeting Notes & Sign-off",
    ]
    for it in items:
        story.append(Paragraph(f"<b>{it}</b>", ParagraphStyle("TOC", parent=S_BODY,
            fontSize=11, leading=18, leftIndent=20, spaceBefore=2)))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(f"<b>Modules Covered:</b> {len(addons)} custom addons", S_BODY))
    story.append(PageBreak())


# -----------------------------------------------------------------------
# SECTION 1: Groups Documentation
# -----------------------------------------------------------------------
def build_groups_doc(story, all_groups):
    story.append(Paragraph("1. Groups Documentation & Configuration", S_SECTION))
    story.append(Paragraph(
        "Complete documentation of each security group. Review the purpose, inherited groups, "
        "and menu access. Use the <b>yellow columns</b> to write changes.",
        S_BODY))
    story.append(Spacer(1, 3*mm))

    for module, groups in sorted(all_groups.items()):
        if not groups:
            continue
        story.append(section_bar(f"Module: {module}", f"{len(groups)} group(s)"))
        story.append(Spacer(1, 2*mm))

        for g in groups:
            # Group detail card
            cat = g["category"].split(".")[-1] if g["category"] else "N/A"
            implied_list = g.get("implied", [])
            implied_str = ", ".join(implied_list) if implied_list else "None"
            menus_list = g.get("menus", [])
            menus_str = ", ".join([m.split(".")[-1] for m in menus_list]) if menus_list else "None"

            hdr = [
                Phdr("Property"),
                Phdr("Current Value"),
                Phdr_new("Change To (fill if needed)"),
            ]

            rows = [
                [P("Group XML ID", S_CELLB), P(g["id"]), P("", S_CELL_EMPTY)],
                [P("Display Name", S_CELLB), P(g["name"]), P("New name: _____________", S_CELL_EMPTY)],
                [P("Category", S_CELLB), P(cat), P("New category: _____________", S_CELL_EMPTY)],
                [P("Inherits From", S_CELLB), P(implied_str), P("Add: _________ Remove: _________", S_CELL_EMPTY)],
                [P("Menu Access", S_CELLB), P(menus_str), P("Add: _________ Remove: _________", S_CELL_EMPTY)],
                [P("Decision", S_CELLB), P(""), P("[ ] Keep  [ ] Remove  [ ] Merge with: _____", S_CELL_EMPTY)],
                [P("Notes", S_CELLB), P(""), P("_________________________________", S_CELL_EMPTY)],
            ]
            data = [hdr] + rows

            t = Table(data, colWidths=[80, 200, 230])
            ts = default_tstyle(len(data))
            # Yellow background for "change" column
            ts.add("BACKGROUND", (2, 1), (2, -1), CLR_NEW_BG)
            # Orange header for change column
            ts.add("BACKGROUND", (2, 0), (2, 0), CLR_CHANGE)
            t.setStyle(ts)
            story.append(t)
            story.append(Spacer(1, 4*mm))

    story.append(PageBreak())


# -----------------------------------------------------------------------
# SECTION 2: Access Rights with Current + New columns
# -----------------------------------------------------------------------
def build_access_rights(story, all_access, addons_list):
    story.append(Paragraph("2. Model Access Rights (Current + New Decision)", S_SECTION))
    story.append(Paragraph(
        "For each access rule: the <b>green/red columns</b> show current CRUD permissions. "
        "The <b>yellow columns</b> are for your desired changes. Leave blank = keep current.",
        S_BODY))
    story.append(Spacer(1, 3*mm))

    #                          Current              New (editable)
    hdr = [
        Phdr("#"),
        Phdr("Model"),
        Phdr("Group"),
        Phdr("R"),      # current
        Phdr("W"),
        Phdr("C"),
        Phdr("D"),
        Phdr_new("New R"),  # editable
        Phdr_new("New W"),
        Phdr_new("New C"),
        Phdr_new("New D"),
        Phdr("Notes"),
    ]
    col_w = [16, 95, 95, 20, 20, 20, 20, 26, 26, 26, 26, 80]

    for addon in addons_list:
        access_rows = all_access.get(addon, [])
        if not access_rows:
            continue

        story.append(section_bar(f"Module: {addon}", f"{len(access_rows)} rule(s)"))
        story.append(Spacer(1, 2*mm))

        data = [hdr]
        for i, row in enumerate(access_rows, 1):
            model_id = row.get("model_id:id", row.get("model_id/id", ""))
            group_id = row.get("group_id:id", row.get("group_id/id", ""))
            data.append([
                P(str(i)),
                P(model_id),
                P(group_id, S_CELLB),
                perm_text(row.get("perm_read", "0")),
                perm_text(row.get("perm_write", "0")),
                perm_text(row.get("perm_create", "0")),
                perm_text(row.get("perm_unlink", "0")),
                empty_box(), empty_box(), empty_box(), empty_box(),
                P(""),  # notes
            ])

        t = Table(data, colWidths=col_w, repeatRows=1)
        ts = default_tstyle(len(data))
        # Yellow background on NEW columns
        ts.add("BACKGROUND", (7, 1), (10, -1), CLR_NEW_BG)
        ts.add("BACKGROUND", (7, 0), (10, 0), CLR_CHANGE)
        t.setStyle(ts)
        story.append(t)
        story.append(Spacer(1, 5*mm))

    story.append(PageBreak())


# -----------------------------------------------------------------------
# SECTION 3: Cross-Reference Matrix (Models x Groups)
# -----------------------------------------------------------------------
def build_matrix(story, all_access, all_groups):
    story.append(Paragraph("3. Cross-Reference Matrix: Models x Groups", S_SECTION))
    story.append(Paragraph(
        "This matrix shows ALL models (rows) vs ALL groups (columns). Each cell shows "
        "the current CRUD as <b>RWCD</b> letters. Below each cell is an editable line "
        "for your desired change.",
        S_BODY))
    story.append(Spacer(1, 3*mm))

    # Collect all unique groups and models
    all_group_ids = set()
    all_model_ids = set()
    access_map = {}  # (model, group) -> (R,W,C,D)

    for addon, rows in all_access.items():
        for row in rows:
            model = row.get("model_id:id", row.get("model_id/id", ""))
            group = row.get("group_id:id", row.get("group_id/id", ""))
            if not model or not group:
                continue
            # Shorten the identifiers
            model_short = model.split(".")[-1] if "." in model else model
            group_short = group.split(".")[-1] if "." in group else group
            all_model_ids.add((model_short, model))
            all_group_ids.add((group_short, group))
            r = row.get("perm_read", "0").strip()
            w = row.get("perm_write", "0").strip()
            c = row.get("perm_create", "0").strip()
            d = row.get("perm_unlink", "0").strip()
            access_map[(model, group)] = (r, w, c, d)

    group_list = sorted(all_group_ids, key=lambda x: x[0])
    model_list = sorted(all_model_ids, key=lambda x: x[0])

    # Split into chunks of 5 groups per table (to fit on page)
    GROUPS_PER_PAGE = 5
    for chunk_start in range(0, len(group_list), GROUPS_PER_PAGE):
        chunk_groups = group_list[chunk_start:chunk_start + GROUPS_PER_PAGE]

        # Header
        hdr_cells = [Phdr("Model")]
        for gs, gf in chunk_groups:
            hdr_cells.append(Phdr(gs))
        data = [hdr_cells]

        col_widths = [120] + [100] * len(chunk_groups)

        for ms, mf in model_list:
            row_cells = [P(ms, S_CELLB)]
            for gs, gf in chunk_groups:
                key = (mf, gf)
                if key in access_map:
                    r, w, c, d = access_map[key]
                    crud = ""
                    crud += "<font color='#27AE60'>R</font>" if r == "1" else "<font color='#E74C3C'>-</font>"
                    crud += "<font color='#27AE60'>W</font>" if w == "1" else "<font color='#E74C3C'>-</font>"
                    crud += "<font color='#27AE60'>C</font>" if c == "1" else "<font color='#E74C3C'>-</font>"
                    crud += "<font color='#27AE60'>D</font>" if d == "1" else "<font color='#E74C3C'>-</font>"
                    cell = Paragraph(
                        f"<b>{crud}</b><br/><font size=6 color='#F39C12'>New:____</font>",
                        S_CELL)
                else:
                    cell = P("<font color='#999'>N/A</font>")
                row_cells.append(cell)
            data.append(row_cells)

        if len(data) > 1:
            t = Table(data, colWidths=col_widths, repeatRows=1)
            ts = default_tstyle(len(data))
            t.setStyle(ts)
            story.append(section_bar(
                f"Matrix (Groups {chunk_start+1}-{chunk_start+len(chunk_groups)} of {len(group_list)})"))
            story.append(Spacer(1, 2*mm))
            story.append(t)
            story.append(Spacer(1, 5*mm))

    story.append(PageBreak())


# -----------------------------------------------------------------------
# SECTION 4: Record Rules
# -----------------------------------------------------------------------
def build_record_rules(story, all_rules, addons_list):
    story.append(Paragraph("4. Record Rules (Row-Level Security)", S_SECTION))
    story.append(Paragraph(
        "Record rules filter WHICH records a user can access. "
        "Current permissions shown + yellow columns for changes.",
        S_BODY))
    story.append(Spacer(1, 3*mm))

    hdr = [Phdr("#"), Phdr("Module"), Phdr("Rule Name"), Phdr("Model"),
           Phdr("Group(s)"), Phdr("Domain"), Phdr("R"), Phdr("W"), Phdr("C"), Phdr("D"),
           Phdr_new("New Domain / Change"), Phdr("Notes")]
    col_w = [14, 50, 70, 50, 60, 70, 14, 14, 14, 14, 90, 60]

    data = [hdr]
    idx = 1
    for module, rules in sorted(all_rules.items()):
        for r in rules:
            groups_str = ", ".join([g.split(".")[-1] for g in r.get("groups", ["--"])])
            data.append([
                P(str(idx)), P(module, S_CELLB), P(r.get("name", "")),
                P(r.get("model_ref", "").split(".")[-1]),
                P(groups_str), P(r.get("domain", "--")),
                perm_text(r.get("perms", {}).get("perm_read", "0")),
                perm_text(r.get("perms", {}).get("perm_write", "0")),
                perm_text(r.get("perms", {}).get("perm_create", "0")),
                perm_text(r.get("perms", {}).get("perm_unlink", "0")),
                P("", S_CELL_EMPTY),
                P("", S_CELL_EMPTY),
            ])
            idx += 1

    if len(data) > 1:
        t = Table(data, colWidths=col_w, repeatRows=1)
        ts = default_tstyle(len(data))
        ts.add("BACKGROUND", (10, 1), (10, -1), CLR_NEW_BG)
        ts.add("BACKGROUND", (10, 0), (10, 0), CLR_CHANGE)
        t.setStyle(ts)
        story.append(t)
    else:
        story.append(Paragraph("<i>No record rules found.</i>", S_NOTE))

    story.append(Spacer(1, 5*mm))

    # Modules without record rules
    story.append(Paragraph("<b>Modules WITHOUT Record Rules (security risk):</b>",
        ParagraphStyle("W", parent=S_BODY, textColor=CLR_WARN)))
    modules_with = set(all_rules.keys())
    missing = []
    for addon in addons_list:
        csv_p = os.path.join(ADDONS_DIR, addon, "security", "ir.model.access.csv")
        if os.path.isfile(csv_p) and addon not in modules_with:
            missing.append(addon)

    if missing:
        # Table with decision column
        mhdr = [Phdr("#"), Phdr("Module"), Phdr_new("Add Record Rules? (describe)")]
        mdata = [mhdr]
        for i, m in enumerate(missing, 1):
            mdata.append([P(str(i)), P(m, S_CELLB),
                P("[ ] Yes  [ ] No  Rule: _______________", S_CELL_EMPTY)])
        mt = Table(mdata, colWidths=[20, 150, 300], repeatRows=1)
        mts = default_tstyle(len(mdata))
        mts.add("BACKGROUND", (2, 1), (2, -1), CLR_NEW_BG)
        mts.add("BACKGROUND", (2, 0), (2, 0), CLR_CHANGE)
        mt.setStyle(mts)
        story.append(mt)
    else:
        story.append(Paragraph("  All modules have record rules.", S_NOTE))

    story.append(PageBreak())


# -----------------------------------------------------------------------
# SECTION 5: Sensitive Fields
# -----------------------------------------------------------------------
def build_sensitive_fields(story, all_models):
    story.append(Paragraph("5. Sensitive Fields & Access Decisions", S_SECTION))
    story.append(Paragraph(
        "Fields containing personal, financial, or confidential data. "
        "Use the yellow column to decide which groups should see each field.",
        S_BODY))
    story.append(Spacer(1, 3*mm))

    hdr = [Phdr("#"), Phdr("Module"), Phdr("Model"), Phdr("Field Name"),
           Phdr("Type"), Phdr("Risk"),
           Phdr_new("Visible To Groups"), Phdr_new("Access Level")]
    col_w = [14, 60, 80, 70, 45, 40, 120, 80]

    data = [hdr]
    idx = 1
    for module, models in sorted(all_models.items()):
        for m in models:
            for fn, ft in m.get("sensitive_fields", []):
                risk = "MEDIUM"
                for hk in ["salary","wage","bank","iban","pin","password","ssn"]:
                    if hk in fn.lower():
                        risk = "HIGH"; break
                data.append([
                    P(str(idx)), P(module, S_CELLB), P(m["model"]),
                    P(fn, S_CELLB), P(ft),
                    P(risk, S_CELLW if risk == "HIGH" else S_CELL),
                    P("Groups: _______________", S_CELL_EMPTY),
                    P("[ ] Hide  [ ] Read  [ ] Full", S_CELL_EMPTY),
                ])
                idx += 1

    if len(data) > 1:
        t = Table(data, colWidths=col_w, repeatRows=1)
        ts = default_tstyle(len(data))
        ts.add("BACKGROUND", (6, 1), (7, -1), CLR_NEW_BG)
        ts.add("BACKGROUND", (6, 0), (7, 0), CLR_CHANGE)
        t.setStyle(ts)
        story.append(t)
    else:
        story.append(Paragraph("<i>No sensitive fields detected.</i>", S_NOTE))
    story.append(PageBreak())


# -----------------------------------------------------------------------
# SECTION 6: Views Inventory
# -----------------------------------------------------------------------
def build_views(story, all_views):
    story.append(Paragraph("6. Views Inventory & Field-Level Groups", S_SECTION))
    story.append(Paragraph(
        "All views defined in custom addons. Use yellow column to specify "
        "which groups should access each view or to restrict fields within it.",
        S_BODY))
    story.append(Spacer(1, 3*mm))

    hdr = [Phdr("#"), Phdr("Module"), Phdr("View ID"), Phdr("Name"),
           Phdr("Model"), Phdr("Type"), Phdr("Groups in View"),
           Phdr_new("Change Groups To"), Phdr("Notes")]
    col_w = [14, 50, 70, 70, 55, 35, 65, 85, 60]

    for module, views in sorted(all_views.items()):
        if not views:
            continue
        story.append(section_bar(f"Module: {module}", f"{len(views)} view(s)"))
        story.append(Spacer(1, 2*mm))

        data = [hdr]
        for i, v in enumerate(views, 1):
            data.append([
                P(str(i)), P(module, S_CELLB), P(v["id"]), P(v["name"]),
                P(v["model"]), P(v["type"]),
                P(v.get("groups_in_view", "--") or "--"),
                P("_______________", S_CELL_EMPTY),
                P("", S_CELL_EMPTY),
            ])

        t = Table(data, colWidths=col_w, repeatRows=1)
        ts = default_tstyle(len(data))
        ts.add("BACKGROUND", (7, 1), (7, -1), CLR_NEW_BG)
        ts.add("BACKGROUND", (7, 0), (7, 0), CLR_CHANGE)
        t.setStyle(ts)
        story.append(t)
        story.append(Spacer(1, 4*mm))

    story.append(PageBreak())


# -----------------------------------------------------------------------
# SECTION 7: Recommendations
# -----------------------------------------------------------------------
def build_recommendations(story):
    story.append(Paragraph("7. Recommendations & Action Items", S_SECTION))
    story.append(Spacer(1, 3*mm))

    recs = [
        ("CRITICAL: Unify Security Groups",
         "Many modules use generic Odoo groups (base.group_user, hr.group_hr_manager) "
         "instead of SamaLink's 5 groups. Users may bypass SamaLink restrictions.",
         "Map all modules to SamaLink groups (Employee, Manager, Administrator, HR Officer, Accountant)."),
        ("CRITICAL: Over-Permissive oh_appraisal",
         "oh_appraisal gives FULL CRUD to base.group_user -- every user can create/delete appraisals.",
         "Restrict Create/Delete to HR. Employees read their own only."),
        ("CRITICAL: hr_reminder Blocks All Access",
         "hr_reminder sets (0,0,0,0) for base.group_user. Employees cannot see reminders.",
         "Grant Read (1,0,0,0) to Employee group."),
        ("HIGH: Missing Record Rules",
         "hr_custody, hr_mission, ohrms_loan, hr_resignation have NO record rules. "
         "Users can see ALL records including other employees' data.",
         "Add rules: Employees=own, Managers=team, HR=all."),
        ("HIGH: Payslip Line Rules Commented Out",
         "Record rules for hr.payslip.line are commented out. Any employee can see all salary details.",
         "Uncomment and activate payslip line record rules."),
        ("HIGH: Field-Level Access Missing",
         "Sensitive fields (salary, bank, passport) lack groups attributes. "
         "Any user with model read can see ALL fields.",
         "Add groups='...' to sensitive fields in views."),
        ("MEDIUM: Consolidate Module Groups",
         "hr_mission, hr_work_location_transfer, hr_attendance_deviation define own group hierarchies.",
         "Make module groups inherit from SamaLink groups via implied_ids."),
        ("MEDIUM: Menu Access Audit",
         "Verify no sensitive menus (payroll, system settings) visible to wrong groups.",
         "Audit whitelisted_menu_ids and remove inappropriate entries."),
    ]

    hdr = [Phdr("#"), Phdr("Priority"), Phdr("Issue"), Phdr("Recommended Action"),
           Phdr_new("Decision"), Phdr("Notes")]
    col_w = [14, 55, 150, 140, 70, 80]
    data = [hdr]
    for i, (title, detail, action) in enumerate(recs, 1):
        priority = title.split(":")[0]
        issue_text = title.split(":", 1)[1].strip() + "<br/>" + detail
        color = S_CELLW if "CRITICAL" in priority else S_CELLB
        data.append([
            P(str(i)), P(priority, color),
            P(issue_text), P(action, S_CELLB),
            P("[ ] Approve<br/>[ ] Reject<br/>[ ] Modify", S_CELL_EMPTY),
            P("", S_CELL_EMPTY),
        ])

    t = Table(data, colWidths=col_w, repeatRows=1)
    ts = default_tstyle(len(data))
    ts.add("BACKGROUND", (4, 1), (4, -1), CLR_NEW_BG)
    ts.add("BACKGROUND", (4, 0), (4, 0), CLR_CHANGE)
    t.setStyle(ts)
    story.append(t)
    story.append(PageBreak())


# -----------------------------------------------------------------------
# SECTION 8: Sign-off
# -----------------------------------------------------------------------
def build_signoff(story):
    story.append(Paragraph("8. Meeting Notes & Sign-off", S_SECTION))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph("<b>Additional Notes:</b>", S_BODY))
    for _ in range(14):
        story.append(Paragraph("_" * 120,
            ParagraphStyle("Ln", parent=S_BODY, spaceBefore=8)))
    story.append(Spacer(1, 8*mm))

    sign = [
        [Phdr("Role"), Phdr("Name"), Phdr("Signature"), Phdr("Date")],
        [P("IT Manager"), P(""), P(""), P("")],
        [P("HR Manager"), P(""), P(""), P("")],
        [P("Finance Manager"), P(""), P(""), P("")],
        [P("General Manager"), P(""), P(""), P("")],
        [P("CEO / Owner"), P(""), P(""), P("")],
    ]
    st = Table(sign, colWidths=[100, 140, 140, 80])
    sts = default_tstyle(len(sign))
    sts.add("TOPPADDING", (0,1), (-1,-1), 14)
    sts.add("BOTTOMPADDING", (0,1), (-1,-1), 14)
    st.setStyle(sts)
    story.append(st)


# -----------------------------------------------------------------------
# Page number
# -----------------------------------------------------------------------
def page_footer(canvas, doc):
    canvas.saveState()
    txt = f"SamaLink Security Checklist  |  Page {canvas.getPageNumber()}  |  {TODAY}"
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#888"))
    canvas.drawCentredString(doc.pagesize[0]/2, 12*mm, txt)
    canvas.setStrokeColor(CLR_ACCENT)
    canvas.setLineWidth(0.5)
    canvas.line(15*mm, doc.pagesize[1]-12*mm, doc.pagesize[0]-15*mm, doc.pagesize[1]-12*mm)
    canvas.restoreState()


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------
def main():
    print("=" * 60)
    print("  SamaLink Security Checklist PDF Generator v2.0")
    print("=" * 60)
    print(f"\nScanning addons in: {ADDONS_DIR}")

    addons = discover_addons(ADDONS_DIR)
    print(f"Found {len(addons)} addons\n")

    all_groups = {}
    all_access = {}
    all_rules = {}
    all_models = {}
    all_views = {}

    for addon in addons:
        ap = os.path.join(ADDONS_DIR, addon)
        g = parse_groups_xml(ap);    all_groups[addon] = g if g else []
        a = parse_access_csv(ap);    all_access[addon] = a if a else []
        r = parse_record_rules(ap);  all_rules[addon] = r if r else []
        m = discover_models(ap);     all_models[addon] = m if m else []
        v = discover_views(ap);      all_views[addon] = v if v else []
        print(f"  {addon:40s} | G={len(g):2d} | A={len(a):2d} | R={len(r):2d} | M={len(m):2d} | V={len(v):2d}")

    # Filter out empty entries for certain sections
    groups_filtered = {k: v for k, v in all_groups.items() if v}
    access_filtered = {k: v for k, v in all_access.items() if v}
    rules_filtered = {k: v for k, v in all_rules.items() if v}
    models_filtered = {k: v for k, v in all_models.items() if v}
    views_filtered = {k: v for k, v in all_views.items() if v}

    print(f"\nGenerating PDF: {OUTPUT_FILE}")

    doc = SimpleDocTemplate(OUTPUT_FILE, pagesize=landscape(A4),
        leftMargin=10*mm, rightMargin=10*mm, topMargin=16*mm, bottomMargin=16*mm,
        title="SamaLink Security Checklist v2", author="SamaLink IT Team")

    story = []
    build_cover(story)
    build_toc(story, addons)
    build_groups_doc(story, groups_filtered)
    build_access_rights(story, access_filtered, addons)
    build_matrix(story, access_filtered, groups_filtered)
    build_record_rules(story, rules_filtered, addons)
    build_sensitive_fields(story, models_filtered)
    build_views(story, views_filtered)
    build_recommendations(story)
    build_signoff(story)

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)

    sz = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"\n[OK] PDF generated successfully!")
    print(f"   File: {OUTPUT_FILE}")
    print(f"   Size: {sz:.1f} KB")
    print("\nNext steps:")
    print("  1. Print the PDF")
    print("  2. Discuss each section in the management meeting")
    print("  3. Fill in the YELLOW columns with your decisions")
    print("  4. Return the annotated PDF/photos to IT for implementation")


if __name__ == "__main__":
    main()
