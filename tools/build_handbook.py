#!/usr/bin/env python3
"""Build the printable Local Context Forge handbook from the Markdown docs."""

from __future__ import annotations

import html
import re
import textwrap
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parents[1]
DOCS = sorted((ROOT / "docs").glob("[0-9][0-9]-*.md"))
OUTPUT = ROOT / "output" / "pdf" / "Local-Context-Forge-Handbook.pdf"
FONT_PATH = ROOT / "tools" / "NotoSansSC-Regular.ttf"
FONT_NAME = "LCFSans"

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT = 21 * mm
RIGHT = 18 * mm
TOP = 20 * mm
BOTTOM = 18 * mm

INK = HexColor("#151822")
MUTED = HexColor("#596174")
FAINT = HexColor("#8990A0")
PAPER = HexColor("#F7F7FA")
PANEL = HexColor("#EEF0F6")
LINE_COLOR = HexColor("#D9DCE7")
VIOLET = HexColor("#7651E9")
VIOLET_SOFT = HexColor("#A891FF")
TEAL = HexColor("#12A894")
DARK = HexColor("#090A0F")
DARK_PANEL = HexColor("#151822")


def normalize(value: str) -> str:
    return (
        value.replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("\u2192", "->")
        .replace("\u2190", "<-")
        .replace("\u2193", "down")
        .replace("\u2191", "up")
        .replace("\t", "    ")
    )


def inline_markup(value: str) -> str:
    text = html.escape(normalize(value.strip()))
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<link href="\2" color="#6240D5"><u>\1</u></link>',
        text,
    )
    text = re.sub(
        r"`([^`]+)`",
        r'<font name="LCFSans" color="#4C3B80">\1</font>',
        text,
    )
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", text)
    return text


if not FONT_PATH.exists():
    raise FileNotFoundError(f"Bundled CJK font is missing: {FONT_PATH}")
pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
pdfmetrics.registerFontFamily(
    "LCFSong",
    normal=FONT_NAME,
    bold=FONT_NAME,
    italic=FONT_NAME,
    boldItalic=FONT_NAME,
)

base = getSampleStyleSheet()
styles = {
    "cover_kicker": ParagraphStyle(
        "cover_kicker",
        parent=base["Normal"],
        fontName="LCFSans",
        fontSize=8.5,
        leading=12,
        textColor=VIOLET_SOFT,
        spaceAfter=10 * mm,
        tracking=1.6,
    ),
    "cover_title": ParagraphStyle(
        "cover_title",
        parent=base["Title"],
        fontName="LCFSans",
        fontSize=31,
        leading=40,
        textColor=colors.white,
        alignment=TA_LEFT,
        spaceAfter=8 * mm,
    ),
    "cover_subtitle": ParagraphStyle(
        "cover_subtitle",
        parent=base["Normal"],
        fontName="LCFSans",
        fontSize=12,
        leading=21,
        textColor=HexColor("#C2C7D4"),
        spaceAfter=12 * mm,
    ),
    "cover_meta": ParagraphStyle(
        "cover_meta",
        parent=base["Normal"],
        fontName="LCFSans",
        fontSize=8.5,
        leading=14,
        textColor=HexColor("#8D94A7"),
    ),
    "chapter": ParagraphStyle(
        "chapter",
        parent=base["Heading1"],
        fontName="LCFSans",
        fontSize=24,
        leading=33,
        textColor=INK,
        spaceAfter=10 * mm,
        keepWithNext=True,
    ),
    "h2": ParagraphStyle(
        "h2",
        parent=base["Heading2"],
        fontName="LCFSans",
        fontSize=16,
        leading=24,
        textColor=INK,
        spaceBefore=8 * mm,
        spaceAfter=4 * mm,
        keepWithNext=True,
    ),
    "h3": ParagraphStyle(
        "h3",
        parent=base["Heading3"],
        fontName="LCFSans",
        fontSize=12.5,
        leading=19,
        textColor=VIOLET,
        spaceBefore=5.5 * mm,
        spaceAfter=2.5 * mm,
        keepWithNext=True,
    ),
    "body": ParagraphStyle(
        "body",
        parent=base["BodyText"],
        fontName="LCFSans",
        fontSize=9.3,
        leading=16,
        textColor=INK,
        wordWrap="CJK",
        spaceAfter=3.2 * mm,
    ),
    "lead": ParagraphStyle(
        "lead",
        parent=base["BodyText"],
        fontName="LCFSans",
        fontSize=11.2,
        leading=19,
        textColor=MUTED,
        wordWrap="CJK",
        spaceAfter=5 * mm,
    ),
    "bullet": ParagraphStyle(
        "bullet",
        parent=base["BodyText"],
        fontName="LCFSans",
        fontSize=9,
        leading=15,
        leftIndent=5 * mm,
        firstLineIndent=-3.5 * mm,
        textColor=INK,
        wordWrap="CJK",
        spaceAfter=1.5 * mm,
    ),
    "quote": ParagraphStyle(
        "quote",
        parent=base["BodyText"],
        fontName="LCFSans",
        fontSize=9.2,
        leading=16,
        leftIndent=7 * mm,
        rightIndent=5 * mm,
        borderColor=VIOLET,
        borderWidth=0,
        borderPadding=(3 * mm, 4 * mm, 3 * mm, 5 * mm),
        backColor=HexColor("#F0ECFF"),
        textColor=HexColor("#4D4760"),
        spaceBefore=2 * mm,
        spaceAfter=4 * mm,
    ),
    "code": ParagraphStyle(
        "code",
        parent=base["Code"],
        fontName="LCFSans",
        fontSize=7.4,
        leading=11.2,
        leftIndent=4 * mm,
        rightIndent=4 * mm,
        borderPadding=4 * mm,
        backColor=HexColor("#EEF0F6"),
        textColor=HexColor("#352A54"),
        spaceBefore=2 * mm,
        spaceAfter=4 * mm,
    ),
    "caption": ParagraphStyle(
        "caption",
        parent=base["Normal"],
        fontName="LCFSans",
        fontSize=7.5,
        leading=11,
        textColor=FAINT,
        alignment=TA_CENTER,
        spaceAfter=5 * mm,
    ),
    "toc": ParagraphStyle(
        "toc",
        parent=base["Normal"],
        fontName="LCFSans",
        fontSize=10,
        leading=17,
        leftIndent=0,
        firstLineIndent=0,
        textColor=INK,
    ),
}


class HandbookDocTemplate(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if not isinstance(flowable, Paragraph):
            return
        style_name = flowable.style.name
        if style_name not in {"chapter", "h2"}:
            return
        level = 0 if style_name == "chapter" else 1
        text = flowable.getPlainText()
        key = f"heading-{level}-{self.seq.nextf('heading')}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=False)
        self.notify("TOCEntry", (level, text, self.page, key))


def draw_page_chrome(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
    canvas.setStrokeColor(LINE_COLOR)
    canvas.setLineWidth(0.45)
    canvas.line(LEFT, 13.5 * mm, PAGE_WIDTH - RIGHT, 13.5 * mm)
    canvas.setFont("LCFSans", 6.8)
    canvas.setFillColor(FAINT)
    canvas.drawString(LEFT, 8.5 * mm, "LOCAL CONTEXT FORGE / 本地 Context7 替代方案")
    canvas.drawRightString(
        PAGE_WIDTH - RIGHT,
        8.5 * mm,
        f"{doc.page:02d}  ·  2026-07-28",
    )
    canvas.restoreState()


def draw_cover(canvas, _doc):
    canvas.saveState()
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)
    canvas.setFillColor(HexColor("#241548"))
    canvas.circle(PAGE_WIDTH * 0.84, PAGE_HEIGHT * 0.78, 72 * mm, stroke=0, fill=1)
    canvas.setFillColor(HexColor("#0A4B45"))
    canvas.circle(PAGE_WIDTH * 1.02, PAGE_HEIGHT * 0.18, 58 * mm, stroke=0, fill=1)
    canvas.setStrokeColor(HexColor("#2A2D3A"))
    canvas.line(LEFT, 18 * mm, PAGE_WIDTH - RIGHT, 18 * mm)
    canvas.setFont("LCFSans", 7)
    canvas.setFillColor(HexColor("#7F8698"))
    canvas.drawString(LEFT, 11 * mm, "EVIDENCE-BACKED · GIT-VERSIONED · LOCAL-FIRST")
    canvas.drawRightString(PAGE_WIDTH - RIGHT, 11 * mm, "HANDBOOK / 2026")
    canvas.restoreState()


def architecture_drawing() -> Drawing:
    drawing = Drawing(170 * mm, 58 * mm)
    node_w = 30 * mm
    node_h = 17 * mm
    gap = 3.6 * mm
    labels = [
        ("01", "源码快照", "Git SHA", VIOLET),
        ("02", "事实层", "symbols/refs", VIOLET),
        ("03", "Typed Wiki", "MD + JSON", VIOLET_SOFT),
        ("04", "QMD", "BM25/vector", TEAL),
        ("05", "MCP", "Context7", TEAL),
    ]
    y = 22 * mm
    for index, (num, title, detail, accent) in enumerate(labels):
        x = index * (node_w + gap)
        drawing.add(Rect(x, y, node_w, node_h, rx=2, ry=2, fillColor=DARK_PANEL, strokeColor=HexColor("#45495A"), strokeWidth=0.7))
        drawing.add(Rect(x, y, 1.2 * mm, node_h, fillColor=accent, strokeColor=accent))
        drawing.add(String(x + 4 * mm, y + 11.7 * mm, num, fontName="LCFSans", fontSize=5.6, fillColor=HexColor("#7F8698")))
        drawing.add(String(x + 4 * mm, y + 7.4 * mm, title, fontName="LCFSans", fontSize=7.6, fillColor=colors.white))
        drawing.add(String(x + 4 * mm, y + 3.2 * mm, detail, fontName="LCFSans", fontSize=5.2, fillColor=HexColor("#858B9A")))
        if index < len(labels) - 1:
            x1 = x + node_w + 0.8 * mm
            x2 = x + node_w + gap - 0.8 * mm
            drawing.add(Line(x1, y + node_h / 2, x2, y + node_h / 2, strokeColor=accent, strokeWidth=0.9))
            drawing.add(Polygon([x2, y + node_h / 2, x2 - 1.8 * mm, y + node_h / 2 + 1.2 * mm, x2 - 1.8 * mm, y + node_h / 2 - 1.2 * mm], fillColor=accent, strokeColor=accent))
    drawing.add(String(0, 6 * mm, "检索负责导航，发布后的 Wiki 才是知识本体", fontName="LCFSans", fontSize=8.2, fillColor=HexColor("#B9BFCD")))
    return drawing


def dual_machine_drawing() -> Drawing:
    drawing = Drawing(170 * mm, 76 * mm)
    box_w = 65 * mm
    box_h = 47 * mm
    y = 19 * mm
    drawing.add(Rect(0, y, box_w, box_h, rx=4, ry=4, fillColor=HexColor("#F1EEFF"), strokeColor=VIOLET, strokeWidth=1))
    drawing.add(Rect(105 * mm, y, box_w, box_h, rx=4, ry=4, fillColor=HexColor("#EAF8F6"), strokeColor=TEAL, strokeWidth=1))
    drawing.add(String(5 * mm, y + 38 * mm, "M4 MACBOOK · 16 GB", fontName="LCFSans", fontSize=8.5, fillColor=VIOLET))
    drawing.add(String(5 * mm, y + 29 * mm, "FastAPI · SQLite · Git Wiki", fontName="LCFSans", fontSize=7.5, fillColor=INK))
    drawing.add(String(5 * mm, y + 22 * mm, "QMD · MCP · Web 审核台", fontName="LCFSans", fontSize=7.5, fillColor=INK))
    drawing.add(String(5 * mm, y + 9 * mm, "常驻控制面 / 本地知识状态", fontName="LCFSans", fontSize=6.7, fillColor=MUTED))
    drawing.add(String(110 * mm, y + 38 * mm, "WINDOWS · RTX 4060", fontName="LCFSans", fontSize=8.5, fillColor=TEAL))
    drawing.add(String(110 * mm, y + 29 * mm, "Ollama · qwen3.5:9b", fontName="LCFSans", fontSize=7.5, fillColor=INK))
    drawing.add(String(110 * mm, y + 22 * mm, "文档草案 / How-to / 示例", fontName="LCFSans", fontSize=7.5, fillColor=INK))
    drawing.add(String(110 * mm, y + 9 * mm, "按需生成面 / 不持有正式 Wiki", fontName="LCFSans", fontSize=6.7, fillColor=MUTED))
    drawing.add(Line(box_w + 5 * mm, y + 25 * mm, 100 * mm, y + 25 * mm, strokeColor=TEAL, strokeWidth=1.2))
    drawing.add(Polygon([100 * mm, y + 25 * mm, 96.5 * mm, y + 27 * mm, 96.5 * mm, y + 23 * mm], fillColor=TEAL, strokeColor=TEAL))
    drawing.add(String(73 * mm, y + 30 * mm, "PRIVATE LAN", fontName="LCFSans", fontSize=6.5, fillColor=TEAL))
    drawing.add(String(72 * mm, y + 17 * mm, "JSON / HTTP", fontName="LCFSans", fontSize=6.2, fillColor=MUTED))
    drawing.add(String(0, 3 * mm, "11434 只允许 Mac 固定私网 IP；不要做路由器端口映射", fontName="LCFSans", fontSize=7.2, fillColor=HexColor("#A04B4B")))
    return drawing


def table_from_rows(rows: list[list[str]], width: float):
    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
    cell_style = ParagraphStyle(
        "table_cell",
        parent=styles["body"],
        fontSize=7.6,
        leading=12,
        spaceAfter=0,
    )
    header_style = ParagraphStyle(
        "table_header",
        parent=cell_style,
        textColor=colors.white,
    )
    data = []
    for row_index, row in enumerate(normalized_rows):
        style = header_style if row_index == 0 else cell_style
        data.append([Paragraph(inline_markup(cell), style) for cell in row])
    table = Table(
        data,
        colWidths=[width / column_count] * column_count,
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), VIOLET),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.45, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def code_flowable(code: str):
    wrapped_lines: list[str] = []
    for raw in normalize(code).splitlines():
        if not raw:
            wrapped_lines.append("")
            continue
        chunks = textwrap.wrap(
            raw,
            width=94,
            subsequent_indent="  ",
            replace_whitespace=False,
            drop_whitespace=False,
        )
        wrapped_lines.extend(chunks or [""])
    return Preformatted("\n".join(wrapped_lines), styles["code"])


def markdown_to_flowables(source: str, *, first_chapter: bool = False):
    lines = normalize(source).splitlines()
    story = []
    paragraph_buffer: list[str] = []
    code_buffer: list[str] = []
    in_code = False
    table_buffer: list[list[str]] = []
    chapter_seen = False

    def flush_paragraph():
        if paragraph_buffer:
            text = " ".join(item.strip() for item in paragraph_buffer)
            story.append(Paragraph(inline_markup(text), styles["body"]))
            paragraph_buffer.clear()

    def flush_table():
        if not table_buffer:
            return
        rows = [
            row
            for row in table_buffer
            if not all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in row)
        ]
        if len(rows) >= 2:
            story.append(table_from_rows(rows, PAGE_WIDTH - LEFT - RIGHT))
            story.append(Spacer(1, 4 * mm))
        table_buffer.clear()

    for line in [*lines, ""]:
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            flush_table()
            if in_code:
                story.append(code_flowable("\n".join(code_buffer)))
                code_buffer.clear()
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buffer.append(line)
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            row = [cell.strip() for cell in stripped.strip("|").split("|")]
            table_buffer.append(row)
            continue
        flush_table()

        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            title = inline_markup(heading.group(2))
            if level == 1:
                if chapter_seen or first_chapter:
                    story.append(PageBreak())
                story.append(Paragraph(title, styles["chapter"]))
                chapter_seen = True
            elif level == 2:
                story.append(Paragraph(title, styles["h2"]))
            else:
                story.append(Paragraph(title, styles["h3"]))
            continue
        if not stripped:
            flush_paragraph()
            continue
        if stripped == "---":
            flush_paragraph()
            story.append(Spacer(1, 2 * mm))
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            story.append(
                Paragraph(inline_markup(stripped.lstrip("> ").strip()), styles["quote"])
            )
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        numbered = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if bullet:
            flush_paragraph()
            story.append(
                Paragraph(f'<font color="#12A894">●</font> {inline_markup(bullet.group(1))}', styles["bullet"])
            )
            continue
        if numbered:
            flush_paragraph()
            story.append(
                Paragraph(
                    f'<font color="#7651E9">{numbered.group(1)}.</font> {inline_markup(numbered.group(2))}',
                    styles["bullet"],
                )
            )
            continue
        paragraph_buffer.append(stripped)
    return story


def cover_story():
    metadata = [
        ["M4 · 16 GB", "索引 / MCP / Wiki"],
        ["RTX 4060 · 32 GB", "Ollama 文档生成"],
        ["LOCAL-FIRST", "默认本地；Codex 需显式外发"],
    ]
    meta_table = Table(
        [
            [
                Paragraph(f"<b>{inline_markup(left)}</b>", styles["cover_meta"]),
                Paragraph(inline_markup(right), styles["cover_meta"]),
            ]
            for left, right in metadata
        ],
        colWidths=[47 * mm, 74 * mm],
    )
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), HexColor("#11131A")),
                ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#333746")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, HexColor("#2A2D3A")),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return [
        Spacer(1, 20 * mm),
        Paragraph("LOCAL-FIRST · CONTEXT7-COMPATIBLE", styles["cover_kicker"]),
        Paragraph("让代码库自己<br/>长出可验证的 API 文档", styles["cover_title"]),
        Paragraph(
            "Local Context Forge 完整解决方案：不可变源码快照、确定性事实层、"
            "Git 版本化 Typed Wiki、QMD 本地混合检索与 Context7 兼容 MCP。",
            styles["cover_subtitle"],
        ),
        architecture_drawing(),
        Spacer(1, 8 * mm),
        meta_table,
        Spacer(1, 6 * mm),
        Paragraph(
            "完整工程包含 backend / MCP / React 审核台 / Docker / 双机脚本 / "
            "测试 / 运维与安全手册。文档版本 2026-07-28。",
            styles["cover_meta"],
        ),
        NextPageTemplate("content"),
        PageBreak(),
    ]


def front_matter_story():
    toc = TableOfContents()
    toc.levelStyles = [
        styles["toc"],
        ParagraphStyle(
            "toc2",
            parent=styles["toc"],
            fontSize=8.5,
            leading=14,
            leftIndent=7 * mm,
            textColor=MUTED,
        ),
    ]
    route_table = table_from_rows(
        [
            ["目标", "建议阅读"],
            ["先跑起来", "快速开始、硬件部署、排错"],
            ["理解架构", "总体说明、架构、Karpathy Wiki 改进"],
            ["接入 Agent", "API 与 MCP、Codex CLI"],
            ["长期维护", "数据模型、运维、备份、安全、模型选择"],
        ],
        PAGE_WIDTH - LEFT - RIGHT,
    )
    return [
        Paragraph("目录", styles["chapter"]),
        Paragraph(
            "本文档由项目内 Markdown 手册自动编译。页码、章节书签与链接可在 PDF 阅读器中使用。",
            styles["lead"],
        ),
        toc,
        PageBreak(),
        Paragraph("方案一览", styles["chapter"]),
        Paragraph(
            "推荐把 Mac 当作持续运行的知识控制面，把 Windows 4060 当作按需生成器。"
            "查询时不重新理解整仓库；已审核 Wiki 才是 Agent 的默认事实入口。",
            styles["lead"],
        ),
        dual_machine_drawing(),
        Paragraph("两台机器的私有分工。Windows 关机后，已有 Wiki、检索和 MCP 仍然可用。", styles["caption"]),
        Spacer(1, 3 * mm),
        route_table,
        PageBreak(),
    ]


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame = Frame(
        LEFT,
        BOTTOM,
        PAGE_WIDTH - LEFT - RIGHT,
        PAGE_HEIGHT - TOP - BOTTOM,
        id="content-frame",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    cover_frame = Frame(
        LEFT,
        20 * mm,
        PAGE_WIDTH - LEFT - RIGHT,
        PAGE_HEIGHT - 30 * mm,
        id="cover-frame",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    document = HandbookDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=LEFT,
        rightMargin=RIGHT,
        topMargin=TOP,
        bottomMargin=BOTTOM,
        title="Local Context Forge Handbook",
        author="Local Context Forge",
        subject="本地 Context7 替代方案：架构、部署、API、运维与安全",
    )
    document.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[cover_frame], onPage=draw_cover),
            PageTemplate(id="content", frames=[frame], onPage=draw_page_chrome),
        ]
    )

    story = [*cover_story(), *front_matter_story()]
    for index, doc_path in enumerate(DOCS):
        source = doc_path.read_text(encoding="utf-8")
        story.extend(markdown_to_flowables(source, first_chapter=index > 0))

    story.extend(
        [
            PageBreak(),
            Paragraph("交付检查单", styles["chapter"]),
            Paragraph(
                "在把 Local Context Forge 用于私有仓库前，完成下面的最小验收。",
                styles["lead"],
            ),
            *[
                Paragraph(
                    f'<font color="#12A894">□</font> {inline_markup(item)}',
                    styles["bullet"],
                )
                for item in [
                    "docker compose ps 的 api / mcp / web 全部健康。",
                    "mock demo 完成 ingest、proposal、publish、query 与 MCP 格式化。",
                    "Windows 11434 只允许 Mac 的固定私网或 VPN 地址。",
                    "加密 BACKUP_DIR 有足够空间容纳未压缩 staging、归档、checksum 与余量；已在独立目录验证恢复。",
                    "每个新激活版本都经 reindex.sh --embed 完成全局向量重建后，才开启 hybrid 检索。",
                    "Codex 的 MCP tool_timeout_sec 已设为 660.0；它与 MCP gateway 到后端的 HTTP timeout 相互独立。",
                    "Codex provider 默认关闭；若启用，确认 CLI 登录归属与隔离参数。",
                    "选择固定评测仓库，对引用准确率、页面命中率和示例质量建立基线。",
                    "API/MCP 只监听 loopback 或放在带认证与 TLS 的可信边界后。",
                ]
            ],
            Spacer(1, 8 * mm),
            Paragraph(
                "最终原则：模型可以替换，索引可以重建；不可失去的是源码证据、审核历史和版本边界。",
                styles["quote"],
            ),
        ]
    )
    document.multiBuild(story)
    return OUTPUT


if __name__ == "__main__":
    print(build())
