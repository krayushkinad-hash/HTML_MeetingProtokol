#!/usr/bin/env python3
"""Render Mermaid blocks from PROCESSES.md → PNG, then build PROCESSES.docx по Краюшкину."""
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Mm, Pt, RGBColor
from PIL import Image


# ─────────────────────────────────────────────────────────────────────────
# Шаг 1: Извлечь Mermaid-блоки и привязать к заголовкам
# ─────────────────────────────────────────────────────────────────────────

def extract_mermaid_blocks(md_path):
    text = md_path.read_text(encoding="utf-8")
    mermaid_pattern = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
    header_pattern = re.compile(r"^(#{2,6}\s+([^\n]+))", re.MULTILINE)
    headers = [(m.start(), m.group(1).strip()) for m in header_pattern.finditer(text)]
    diagrams = list(mermaid_pattern.finditer(text))
    results = []
    for m in diagrams:
        preceding = [h for h in headers if h[0] < m.start()]
        section = preceding[-1][1] if preceding else f"diagram_{len(results)+1}"
        results.append((section, m.group(1).strip()))
    return results


def safe_filename(name, idx):
    name = re.sub(r"^\d+(\.\d+)*\.?\s*", "", name)
    name = re.sub(r"[^A-Za-zА-Яа-я0-9_]+", "_", name)
    name = name.strip("_") or f"diagram_{idx}"
    return f"{idx:02d}_{name}"


# ─────────────────────────────────────────────────────────────────────────
# Шаг 2: Mermaid → PNG через Playwright
# ─────────────────────────────────────────────────────────────────────────

def render_mermaid_to_png(blocks, diagrams_dir):
    """Рендерит каждый Mermaid-блок в PNG через Playwright."""
    from playwright.sync_api import sync_playwright

    # Готовим HTML-обёртку для рендеринга
    html_template = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
body {{ margin: 0; padding: 16px; background: white; font-family: 'Segoe UI', sans-serif; }}
.mermaid {{ font-size: 14px; }}
.mermaid .nodeLabel, .mermaid .edgeLabel {{ font-family: 'Segoe UI', sans-serif !important; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
</head><body>
<div class="mermaid">
{code}
</div>
<script>
mermaid.initialize({{ startOnLoad: true, theme: 'default', flowchart: {{ curve: 'basis' }} }});
window.rendered = false;
mermaid.run().then(() => {{ window.rendered = true; }});
</script>
</body></html>"""

    rendered_files = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for idx, (section, code) in enumerate(blocks, 1):
            fname = safe_filename(section, idx)
            out = diagrams_dir / f"{fname}.png"
            tmp_html = diagrams_dir / f"{fname}.html"
            tmp_html.write_text(html_template.format(code=code), encoding="utf-8")

            page = browser.new_page(viewport={"width": 1800, "height": 1200})
            page.goto(f"file://{tmp_html.resolve()}")
            page.wait_for_function("window.rendered === true", timeout=15000)
            # Дополнительно ждём, чтобы SVG полностью отрисовался
            page.wait_for_timeout(500)
            svg = page.locator(".mermaid svg").first
            svg.screenshot(path=str(out))
            page.close()
            tmp_html.unlink()

            size_kb = out.stat().st_size // 1024
            print(f"  [{idx}/{len(blocks)}] {section} → {out.name} ({size_kb} KB)")
            rendered_files.append(out)
        browser.close()

    return rendered_files


# ─────────────────────────────────────────────────────────────────────────
# Шаг 3: DOCX по стандарту Краюшкина
# ─────────────────────────────────────────────────────────────────────────

def clean_text(s: str) -> str:
    s = s.replace("—", "-").replace("–", "-")
    s = s.replace("\xa0", " ")
    s = re.sub(r" {2,}", " ", s)
    return s.strip()


def setup_normal_style(doc):
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    rPr = normal.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), "Times New Roman")
    rFonts.set(qn("w:hAnsi"), "Times New Roman")
    rFonts.set(qn("w:eastAsia"), "Times New Roman")
    rFonts.set(qn("w:cs"), "Times New Roman")
    for old in rPr.findall(qn("w:lang")):
        rPr.remove(old)
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "ru-RU")
    lang.set(qn("w:eastAsia"), "ru-RU")
    lang.set(qn("w:bidi"), "ru-RU")
    rPr.append(lang)
    pf = normal.paragraph_format
    pf.first_line_indent = Mm(12.5)
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.15
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE


def setup_caption_style(doc):
    styles = doc.styles
    try:
        cap = styles["Подпись"]
    except KeyError:
        cap = styles.add_style("Подпись", WD_STYLE_TYPE.PARAGRAPH)
        cap.base_style = styles["Normal"]
    cap.font.name = "Times New Roman"
    cap.font.size = Pt(12)
    cap.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    pf = cap.paragraph_format
    pf.first_line_indent = Mm(0)
    pf.space_before = Pt(12)
    pf.space_after = Pt(6)
    pf.line_spacing = 1.15
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf.keep_with_next = True


def set_page_margins(doc):
    for section in doc.sections:
        section.left_margin = Mm(20)
        section.right_margin = Mm(10)
        section.top_margin = Mm(10)
        section.bottom_margin = Mm(10)


def setup_headings(doc):
    sizes = {1: 16, 2: 14, 3: 12}
    for lvl, sz in sizes.items():
        try:
            s = doc.styles[f"Heading {lvl}"]
        except KeyError:
            continue
        s.font.name = "Times New Roman"
        s.font.size = Pt(sz)
        s.font.bold = True
        s.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
        rPr = s.element.get_or_add_rPr()
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rPr.append(rFonts)
        rFonts.set(qn("w:ascii"), "Times New Roman")
        rFonts.set(qn("w:hAnsi"), "Times New Roman")
        rFonts.set(qn("w:eastAsia"), "Times New Roman")
        rFonts.set(qn("w:cs"), "Times New Roman")
        pf = s.paragraph_format
        pf.first_line_indent = Mm(0)
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing = 1.15
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE


def add_page_numbers(doc):
    for section in doc.sections:
        footer = section.footer
        for p in list(footer.paragraphs):
            p._element.getparent().remove(p._element)
        p = footer.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Mm(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run()
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
        fld1 = OxmlElement("w:fldChar"); fld1.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = " PAGE "
        fld2 = OxmlElement("w:fldChar"); fld2.set(qn("w:fldCharType"), "end")
        run._r.append(fld1); run._r.append(instr); run._r.append(fld2)


def add_document_title(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Mm(0)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    run = p.add_run(clean_text(text))
    run.font.name = "Times New Roman"
    run.font.size = Pt(18)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)


def add_heading(doc, text, level):
    p = doc.add_paragraph(style=f"Heading {level}")
    run = p.add_run(clean_text(text))


def add_body(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = p.add_run(clean_text(text))
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)


def add_list_bullet(doc, items):
    for indent, txt in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.first_line_indent = Mm(0)
        p.paragraph_format.left_indent = Mm(7.5 * (1 + indent // 2))
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.15
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run = p.add_run(clean_text(txt))
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)


def add_list_number(doc, items):
    for txt in items:
        p = doc.add_paragraph(style="List Number")
        p.paragraph_format.first_line_indent = Mm(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.15
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run = p.add_run(clean_text(txt))
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)


def add_seq_field(paragraph, name):
    run = paragraph.add_run()
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    fld1 = OxmlElement("w:fldChar"); fld1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve")
    instr.text = f" SEQ {name} \\* ARABIC "
    fld2 = OxmlElement("w:fldChar"); fld2.set(qn("w:fldCharType"), "end")
    run._r.append(fld1); run._r.append(instr); run._r.append(fld2)


def add_table_caption_above(doc, caption_text):
    p = doc.add_paragraph(style="Подпись")
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.first_line_indent = Mm(0)
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.keep_with_next = True
    run1 = p.add_run(f"{clean_text(caption_text)} приведено в таблице (Таблица ")
    run1.font.name = "Times New Roman"; run1.font.size = Pt(12); run1.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    add_seq_field(p, "Таблица")
    run2 = p.add_run(").")
    run2.font.name = "Times New Roman"; run2.font.size = Pt(12); run2.font.color.rgb = RGBColor(0x00, 0x00, 0x00)


def add_figure_caption_below(doc, caption_text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Mm(0)
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(12)
    run1 = p.add_run("Рисунок ")
    run1.font.name = "Times New Roman"; run1.font.size = Pt(12); run1.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    add_seq_field(p, "Рисунок")
    run2 = p.add_run(f". {clean_text(caption_text)}")
    run2.font.name = "Times New Roman"; run2.font.size = Pt(12); run2.font.color.rgb = RGBColor(0x00, 0x00, 0x00)


def add_picture(doc, image_path, caption_text, max_width_cm=15.0):
    """Встраивает PNG + подпись рисунка под ним."""
    if not image_path.exists():
        return False
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Mm(0)
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.keep_with_next = True
    run = p.add_run()
    # Используем PIL для расчёта размеров с сохранением пропорций
    with Image.open(image_path) as img:
        orig_w_px, orig_h_px = img.size
    # 96 dpi стандарт для python-docx, но пропорции считаем по пикселям
    # Ограничение: максимальная ширина 15 см
    target_w_cm = max_width_cm
    # Высота в см пропорционально
    target_h_cm = target_w_cm * (orig_h_px / orig_w_px)
    # Ограничиваем высоту 20 см
    if target_h_cm > 20:
        target_h_cm = 20
        target_w_cm = target_h_cm * (orig_w_px / orig_h_px)
    run.add_picture(str(image_path), width=Cm(target_w_cm), height=Cm(target_h_cm))
    add_figure_caption_below(doc, caption_text)
    return True


def add_table(doc, rows):
    if not rows:
        return None
    n_cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=n_cols)
    try:
        table.style = "Table Grid"
    except KeyError:
        table.style = "Light Grid Accent 1"
    trPr = table.rows[0]._tr.get_or_add_trPr()
    tblHeader = OxmlElement("w:tblHeader")
    tblHeader.set(qn("w:val"), "true")
    trPr.append(tblHeader)
    for i, row in enumerate(rows):
        for j in range(n_cols):
            cell_text = row[j] if j < len(row) else ""
            cell = table.rows[i].cells[j]
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.first_line_indent = Mm(0)
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            run = p.add_run(clean_text(cell_text))
            run.font.name = "Times New Roman"
            run.font.size = Pt(12)
            run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    return table


def add_page_break(doc):
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Mm(0)
    run = p.add_run()
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run._r.append(br)


# ─────────────────────────────────────────────────────────────────────────
# Шаг 4: Парсер MD с inline-вставкой PNG
# ─────────────────────────────────────────────────────────────────────────

def strip_prefix(text):
    return re.sub(r"^\d+(\.\d+)*\.?\s+", "", text).strip()


def md_to_docx(md_path, out_path, diagrams_dir):
    text = md_path.read_text(encoding="utf-8")
    blocks = extract_mermaid_blocks(md_path)
    diagram_index = 0

    doc = Document()
    setup_normal_style(doc)
    setup_headings(doc)
    setup_caption_style(doc)
    set_page_margins(doc)

    doc.core_properties.author = "Алексей Краюшкин"
    doc.core_properties.title = "Бизнес-процессы HTML_MeetingProtokol"

    # Заголовок документа (18 пт, жирный, по центру)
    add_document_title(doc, "Бизнес-процессы HTML_MeetingProtokol")

    lines = text.split("\n")
    i = 0
    in_mermaid = False
    table_lines = []
    in_table = False

    while i < len(lines):
        line = lines[i].rstrip()

        # Mermaid-блок → PNG + подпись
        if line.strip().startswith("```mermaid"):
            in_mermaid = True
            i += 1
            continue
        elif in_mermaid and line.strip() == "```":
            in_mermaid = False
            if diagram_index < len(blocks):
                section, _ = blocks[diagram_index]
                png_path = diagrams_dir / f"{safe_filename(section, diagram_index + 1)}.png"
                if png_path.exists():
                    add_picture(doc, png_path, section, max_width_cm=15.5)
                diagram_index += 1
            i += 1
            continue
        elif in_mermaid:
            i += 1
            continue

        # H1 (заголовок документа) — игнорируем, у нас свой add_document_title
        if re.match(r"^#\s+", line) and not re.match(r"^##\s+", line):
            i += 1
            continue

        # H2 / H3 / H4
        m = re.match(r"^(#{2,4})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            title = strip_prefix(m.group(2))
            add_heading(doc, title, level - 1)  # H2 → Heading 1 и т.д.
            i += 1
            continue

        # Таблица
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|", lines[i + 1].strip()):
            tbl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl.append(lines[i].strip())
                i += 1
            rows = []
            for row in tbl:
                if re.match(r"^\|[\s\-:|]+\|$", row):
                    continue
                cells = [c.strip() for c in row.strip("|").split("|")]
                rows.append(cells)
            # Подпись таблицы — обобщённая
            n = len(rows)
            add_table_caption_above(doc, f"Сводные данные ({n - 1} строк)")
            add_table(doc, rows)
            continue

        # Цитата
        if line.lstrip().startswith(">"):
            quote_text = re.sub(r"^>\s*", "", line).strip()
            add_body(doc, quote_text)
            i += 1
            continue

        # Нумерованный список
        if re.match(r"^\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]).rstrip())
                i += 1
            add_list_number(doc, items)
            continue

        # Буллет-список
        if re.match(r"^\s*-\s+", line) or re.match(r"^\s*\*\s+", line):
            items = []
            while i < len(lines) and (re.match(r"^\s*-\s+", lines[i]) or re.match(r"^\s*\*\s+", lines[i])):
                raw = lines[i]
                indent = len(raw) - len(raw.lstrip())
                txt = re.sub(r"^\s*[-\*]\s+", "", raw).rstrip()
                items.append((indent, txt))
                i += 1
            add_list_bullet(doc, items)
            continue

        # Параграф
        if line.strip():
            add_body(doc, line)
        i += 1

    add_page_numbers(doc)
    doc.save(out_path)


# ─────────────────────────────────────────────────────────────────────────
# Пост-обработка DOCX
# ─────────────────────────────────────────────────────────────────────────

def post_process_docx(docx_path):
    tmp = docx_path.with_suffix(".tmp.docx")
    seen_n = False
    with zipfile.ZipFile(docx_path, "r") as zin:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == "word/numbering.xml":
                    if seen_n:
                        continue
                    seen_n = True
                zout.writestr(item.filename, zin.read(item.filename))
    shutil.move(tmp, docx_path)
    with zipfile.ZipFile(docx_path, "r") as z:
        for name in z.namelist():
            if name.endswith((".xml", ".rels")):
                try:
                    ET.fromstring(z.read(name))
                except ET.ParseError as e:
                    print(f"INVALID: {name}: {e}")
                    return False
    return True


# ─────────────────────────────────────────────────────────────────────────
# Главная функция
# ─────────────────────────────────────────────────────────────────────────

def main():
    project_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    md_path = project_root / "artifacts" / "04-processes" / "PROCESSES.md"
    diagrams_dir = project_root / "artifacts" / "04-processes" / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)
    out_path = md_path.parent / "PROCESSES.docx"

    if not md_path.exists():
        print(f"Not found: {md_path}", file=sys.stderr)
        sys.exit(1)

    # Шаг 1: Mermaid → PNG
    blocks = extract_mermaid_blocks(md_path)
    print(f"Найдено {len(blocks)} Mermaid-блоков")
    print("Рендерим PNG через Playwright...")
    render_mermaid_to_png(blocks, diagrams_dir)

    # Шаг 2: MD + PNG → DOCX (Краюшкин)
    print("\nСобираем DOCX по стандарту Краюшкина...")
    md_to_docx(md_path, out_path, diagrams_dir)

    # Шаг 3: Пост-обработка (XML-валидность)
    print("Пост-обработка DOCX...")
    ok = post_process_docx(out_path)
    if ok:
        print(f"\nOK: {out_path} ({out_path.stat().st_size // 1024} KB)")
    else:
        print("FAIL: XML-валидность нарушена", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()