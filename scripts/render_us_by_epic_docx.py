#!/usr/bin/env python3
"""Собрать DOCX со всеми основными US-эпиками HTML_MeetingProtokol.

Источник: artifacts/03-user-stories/1_us_list/US_LIST.md
Парсит таблицу US, группирует по эпикам, формирует документ по Краюшкину.
"""
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from collections import defaultdict

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Mm, Pt, RGBColor


# ─────────────────────────────────────────────────────────────────────────
# Парсинг US_LIST.md
# ─────────────────────────────────────────────────────────────────────────

def parse_us_list(md_path):
    """Извлекает все US из таблицы US_LIST.md."""
    text = md_path.read_text(encoding="utf-8")
    us_list = []
    us_id_pattern = re.compile(r"^US-\d{3}$")

    in_table = False
    for line in text.split("\n"):
        if line.startswith("|"):
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 8 and us_id_pattern.match(parts[0]):
                us_list.append({
                    "id": parts[0],
                    "title": parts[1],
                    "epic": parts[2],
                    "priority": parts[3],
                    "sp": parts[4],
                    "persona": parts[5],
                    "form": parts[6],
                    "api": parts[7] if len(parts) > 7 else "",
                })
    return us_list


def group_by_epic(us_list):
    """Группирует US по эпикам с метаданными."""
    epic_meta = {
        "EPIC-FILE": {
            "name": "Загрузка файлов",
            "desc": "Загрузка локальных аудио/видеофайлов и по ссылке из облака",
            "color": "синий",
        },
        "EPIC-TRANS": {
            "name": "Транскрипция и диаризация",
            "desc": "Распознавание русской речи (Whisper) и автодиаризация ораторов (pyannote)",
            "color": "фиолетовый",
        },
        "EPIC-MANUAL": {
            "name": "Ручная разметка и редактирование",
            "desc": "Корректировка ораторов и текста реплик после автообработки",
            "color": "оранжевый",
        },
        "EPIC-HISTORY": {
            "name": "Хронологическая база, календарь, поиск",
            "desc": "Список, календарь прошлых встреч, поиск по транскрипции, навигация видео",
            "color": "зелёный",
        },
        "EPIC-DOCX": {
            "name": "DOCX-экспорт",
            "desc": "Экспорт протокола в DOCX с таймкодами, скриншотами, гиперссылками на видео",
            "color": "красный",
        },
        "EPIC-TELEMOST": {
            "name": "Яндекс Телемост (онлайн)",
            "desc": "Подключение к встрече, живая транскрипция, три панели Live Mode, захват скриншотов",
            "color": "голубой",
        },
        "EPIC-AI": {
            "name": "AI-фичи",
            "desc": "Саммари через локальную LLM, action items, семантический поиск, AI-теги",
            "color": "индиго",
        },
        "EPIC-CROSSPLAT": {
            "name": "Кросс-платформенность",
            "desc": "Работа на Windows 10/11 и Astra Linux, офлайн-режим просмотра в командировке",
            "color": "бирюзовый",
        },
        "EPIC-PRIVACY": {
            "name": "Приватность и индикация",
            "desc": "Локальное хранение данных, индикатор записи для гостей, отправка DOCX",
            "color": "золотой",
        },
        "EPIC-RES": {
            "name": "Контроль ресурсов (OOM)",
            "desc": "Лимиты памяти, потоковое чтение, мониторинг RSS, автопауза",
            "color": "тёмно-серый",
        },
    }

    groups = defaultdict(list)
    for us in us_list:
        groups[us["epic"]].append(us)

    result = []
    for epic_id, us_items in groups.items():
        meta = epic_meta.get(epic_id, {"name": epic_id, "desc": "", "color": "серый"})
        sp_total = sum(int(u["sp"]) for u in us_items if u["sp"].isdigit())
        must = sum(1 for u in us_items if u["priority"] == "Must")
        should = sum(1 for u in us_items if u["priority"] == "Should")
        could = sum(1 for u in us_items if u["priority"] == "Could")
        result.append({
            "id": epic_id,
            "name": meta["name"],
            "desc": meta["desc"],
            "color": meta["color"],
            "us": us_items,
            "sp_total": sp_total,
            "must": must,
            "should": should,
            "could": could,
        })
    return result


# ─────────────────────────────────────────────────────────────────────────
# Стили Краюшкина (копия из render_vision_docx.py)
# ─────────────────────────────────────────────────────────────────────────

def clean_text(s):
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


# ─────────────────────────────────────────────────────────────────────────
# Добавление элементов
# ─────────────────────────────────────────────────────────────────────────

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


def add_toc_field(doc):
    """Добавляет поле TOC для автоматического оглавления."""
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Mm(0)
    run = p.add_run()
    fld1 = OxmlElement("w:fldChar"); fld1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    fld2 = OxmlElement("w:fldChar"); fld2.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:r")
    placeholder_text = OxmlElement("w:t")
    placeholder_text.text = "Обновите поле в Word: правый клик → Обновить поле"
    placeholder.append(placeholder_text)
    fld3 = OxmlElement("w:fldChar"); fld3.set(qn("w:fldCharType"), "end")
    run._r.append(fld1); run._r.append(instr); run._r.append(fld2); run._r.append(placeholder); run._r.append(fld3)


# ─────────────────────────────────────────────────────────────────────────
# Сборка документа
# ─────────────────────────────────────────────────────────────────────────

def build_docx(epics, out_path, project_root):
    doc = Document()
    setup_normal_style(doc)
    setup_headings(doc)
    setup_caption_style(doc)
    set_page_margins(doc)

    doc.core_properties.author = "Алексей Краюшкин"
    doc.core_properties.title = "User Stories по эпикам HTML_MeetingProtokol"

    # ── Титульный лист ──
    add_document_title(doc, "User Stories по эпикам")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Mm(0)
    run = p.add_run("Проект HTML_MeetingProtokol")
    run.font.name = "Times New Roman"; run.font.size = Pt(14); run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Mm(0)
    run = p.add_run("Версия 1.0 · 2026-09-14")
    run.font.name = "Times New Roman"; run.font.size = Pt(12); run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    add_page_break(doc)

    # ── §1. Метаинформация ──
    add_heading(doc, "1 Метаинформация", 1)
    add_table_caption_above(doc, "Метаинформация документа")
    add_table(doc, [
        ["Поле", "Значение"],
        ["Проект", "HTML_MeetingProtokol"],
        ["Документ", "User Stories по эпикам"],
        ["Версия", "1.0"],
        ["Дата", "2026-09-14"],
        ["Всего US", str(sum(len(e["us"]) for e in epics))],
        ["Эпиков", str(len(epics))],
        ["Сумма Story Points", str(sum(e["sp_total"] for e in epics))],
        ["Must / Should / Could", f"{sum(e['must'] for e in epics)} / {sum(e['should'] for e in epics)} / {sum(e['could'] for e in epics)}"],
        ["Автор", "Алексей Краюшкин"],
    ])

    # ── §2. Сводная статистика по эпикам ──
    add_heading(doc, "2 Сводная статистика по эпикам", 1)
    add_table_caption_above(doc, "Сводная статистика по эпикам проекта")
    summary_rows = [["Эпик", "Название", "US", "SP", "Must", "Should", "Could"]]
    for e in epics:
        summary_rows.append([
            e["id"],
            e["name"],
            str(len(e["us"])),
            str(e["sp_total"]),
            str(e["must"]),
            str(e["should"]),
            str(e["could"]),
        ])
    add_table(doc, summary_rows)

    add_page_break(doc)

    # ── §3. Оглавление (TOC) ──
    add_heading(doc, "3 Оглавление", 1)
    add_body(doc, "Для автоматического построения оглавления откройте документ в Microsoft Word, "
                  "правый клик по этому разделу → Обновить поле → Обновить целиком.")
    add_toc_field(doc)

    add_page_break(doc)

    # ── §4-N. Каждый эпик ──
    for epic_idx, epic in enumerate(epics, 1):
        # §N. Эпик
        add_heading(doc, f"{epic_idx + 3} Эпик {epic['id']}: {epic['name']}", 1)
        add_body(doc, epic["desc"])

        # Метаинформация эпика
        add_heading(doc, f"{epic_idx + 3}.1 Метаинформация эпика", 2)
        add_table_caption_above(doc, f"Метаинформация эпика {epic['id']}")
        add_table(doc, [
            ["Поле", "Значение"],
            ["ID", epic["id"]],
            ["Название", epic["name"]],
            ["Описание", epic["desc"]],
            ["User Stories", str(len(epic["us"]))],
            ["Story Points (сумма)", str(epic["sp_total"])],
            ["Must", str(epic["must"])],
            ["Should", str(epic["should"])],
            ["Could", str(epic["could"])],
        ])

        # Перечень US
        add_heading(doc, f"{epic_idx + 3}.2 User Stories эпика", 2)
        add_table_caption_above(doc, f"Перечень US эпика {epic['id']}")
        us_table = [["ID", "US-текст", "Приоритет", "SP", "Персона"]]
        for us in epic["us"]:
            us_table.append([
                us["id"],
                us["title"][:80] + ("..." if len(us["title"]) > 80 else ""),
                us["priority"],
                us["sp"],
                us["persona"][:30],
            ])
        add_table(doc, us_table)

        # Детальные карточки US
        add_heading(doc, f"{epic_idx + 3}.3 Детальные карточки US", 2)

        cards_dir = project_root / "artifacts" / "03-user-stories" / "2_us_cards"
        epic_cards_dir = project_root / "artifacts" / "03-user-stories" / epic["id"]
        for us in epic["us"]:
            # Ищем детальную карточку в 2_us_cards/ или в epic-specific папке
            card_path = cards_dir / f"{us['id'].replace('-', '_')}.md"
            if not card_path.exists():
                card_path = epic_cards_dir / f"{us['id'].replace('-', '_')}.md"
            if card_path.exists():
                card_content = card_path.read_text(encoding="utf-8")
                # Извлекаем секции из карточки
                add_us_card_inline(doc, us, card_content)
            else:
                # Краткая карточка из US_LIST
                add_us_summary_card(doc, us)

        # Разрыв страницы между эпиками (кроме последнего)
        if epic_idx < len(epics):
            add_page_break(doc)

    add_page_numbers(doc)
    doc.save(out_path)
    return post_process_docx(out_path)


def add_us_card_inline(doc, us, card_content):
    """Добавляет детальную карточку US из MD-файла."""
    add_heading(doc, f"US-{us['id'][-3:]}: {us['title']}", 3)

    # Метаданные
    meta = parse_us_card_meta(card_content)
    rows = [["Поле", "Значение"]]
    rows.append(["ID", us["id"]])
    rows.append(["Эпик", meta.get("epic", us["epic"])])
    rows.append(["Приоритет", meta.get("priority", us["priority"])])
    rows.append(["Story Points", meta.get("sp", us["sp"])])
    rows.append(["Персона", meta.get("persona", us["persona"])])
    rows.append(["Форма", meta.get("form", us["form"])])
    rows.append(["API", meta.get("api", us["api"])])
    add_table(doc, rows)

    # User Story (ищем в тексте)
    story_match = re.search(r"\*\*Как\*\*\s*(.+?),", card_content)
    if story_match:
        add_heading(doc, "User Story", 4)
        add_body(doc, "Как пользователь, я хочу выполнить действие, чтобы получить ценность.")

    # AC (ищем блок)
    ac_match = re.search(r"## Acceptance Criteria\n(.+?)(?=\n## |\Z)", card_content, re.DOTALL)
    if ac_match:
        ac_text = ac_match.group(1)
        ac_items = re.findall(r"\*\*AC-\d+:\*\*\s*(.+?)(?=\n|$)", ac_text)
        if ac_items:
            add_heading(doc, "Acceptance Criteria", 4)
            for i, ac in enumerate(ac_items, 1):
                p = doc.add_paragraph(style="List Number")
                p.paragraph_format.first_line_indent = Mm(0)
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1.15
                p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                run = p.add_run(f"AC-{i}: {clean_text(ac)}")
                run.font.name = "Times New Roman"; run.font.size = Pt(12); run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)


def add_us_summary_card(doc, us):
    """Краткая карточка US без детального файла."""
    add_heading(doc, f"US-{us['id'][-3:]}: {us['title']}", 3)
    add_body(doc, f"Эпик: {us['epic']}, Приоритет: {us['priority']}, Story Points: {us['sp']}, Персона: {us['persona']}.")
    add_body(doc, f"Форма: {us['form']}. API: {us['api']}.")


def parse_us_card_meta(content):
    """Извлекает метаданные из таблицы в начале US-карточки."""
    meta = {}
    for line in content.split("\n"):
        if line.startswith("|"):
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) == 2:
                key = parts[0].replace("**", "").strip()
                val = parts[1].strip()
                key_map = {
                    "Эпик": "epic",
                    "Приоритет": "priority",
                    "Story Points": "sp",
                    "Персона": "persona",
                    "Форма": "form",
                    "API": "api",
                }
                if key in key_map:
                    meta[key_map[key]] = val
    return meta


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


def main():
    project_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    md_path = project_root / "artifacts" / "03-user-stories" / "1_us_list" / "US_LIST.md"
    out_path = project_root / "artifacts" / "03-user-stories" / "USER_STORIES_BY_EPIC.docx"

    if not md_path.exists():
        print(f"Not found: {md_path}", file=sys.stderr)
        sys.exit(1)

    us_list = parse_us_list(md_path)
    epics = group_by_epic(us_list)
    print(f"Найдено {len(us_list)} US, {len(epics)} эпиков")

    for e in epics:
        print(f"  {e['id']}: {len(e['us'])} US, {e['sp_total']} SP")

    ok = build_docx(epics, out_path, project_root)
    if ok:
        print(f"\nOK: {out_path} ({out_path.stat().st_size // 1024} KB)")
    else:
        print("FAIL: XML-валидность нарушена", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()