"""Read and write Word, Excel and PDF files.

Word (.docx), Excel (.xlsx) and PowerPoint (.pptx) files are zip archives of XML, so the standard
library reads and writes them. PDF needs a parser: the small, pure-Python `pypdf` package.
"""

import csv
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
TEXT_FILES = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".xml", ".html", ".htm", ".py", ".js", ".ini",
              ".yaml", ".yml", ".toml", ".srt"}
MAX_ROWS = 500               # per Excel sheet: enough to understand it, small enough for a model
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class DocumentError(Exception):
    """The file cannot be read or written."""


def _xml(package: zipfile.ZipFile, name: str):
    try:
        return ElementTree.fromstring(package.read(name))
    except KeyError:
        return None


def _text(value) -> str:
    return escape(_INVALID_XML.sub("", str(value)))


# ---------- reading ----------
def read_docx(path) -> str:
    """Paragraphs (headings as #), lists as •, tables as | a | b | rows."""
    with zipfile.ZipFile(path) as package:
        root = _xml(package, "word/document.xml")
    if root is None:
        raise DocumentError("this is not a Word document")
    body, lines = root.find(f"{W}body"), []

    def paragraph(p) -> str:
        parts = []
        for node in p.iter():
            if node.tag == f"{W}t":
                parts.append(node.text or "")
            elif node.tag == f"{W}tab":
                parts.append("\t")
            elif node.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
        text = "".join(parts)
        style = p.find(f"{W}pPr/{W}pStyle")
        level = re.match(r"(?i)heading\s*(\d)", (style.get(f"{W}val") or "") if style is not None else "")
        if level and text.strip():
            return "#" * int(level.group(1)) + " " + text
        if p.find(f"{W}pPr/{W}numPr") is not None and text.strip():
            return "• " + text
        return text

    for block in body if body is not None else []:
        if block.tag == f"{W}p":
            lines.append(paragraph(block))
        elif block.tag == f"{W}tbl":
            for row in block.iter(f"{W}tr"):
                cells = [" ".join(paragraph(p) for p in cell.iter(f"{W}p")).strip() for cell in row.iter(f"{W}tc")]
                lines.append("| " + " | ".join(cells) + " |")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _column(reference: str) -> int:
    letters, number = re.match(r"([A-Z]+)", reference or "A").group(1), 0
    for letter in letters:
        number = number * 26 + ord(letter) - 64
    return number - 1


def read_xlsx(path, max_rows: int = MAX_ROWS) -> str:
    """Every sheet as '## name' followed by its rows, cells separated by ' | '."""
    with zipfile.ZipFile(path) as package:
        book, rels = _xml(package, "xl/workbook.xml"), _xml(package, "xl/_rels/workbook.xml.rels")
        if book is None:
            raise DocumentError("this is not an Excel workbook")
        shared_root = _xml(package, "xl/sharedStrings.xml")
        shared = ["".join(t.text or "" for t in si.iter(f"{S}t")) for si in shared_root.iter(f"{S}si")] \
            if shared_root is not None else []
        targets = {r.get("Id"): r.get("Target") for r in rels.iter(f"{REL}Relationship")} if rels is not None else {}
        out = []
        for number, sheet in enumerate(book.iter(f"{S}sheet"), 1):
            target = targets.get(sheet.get(f"{R}id"), f"worksheets/sheet{number}.xml").lstrip("/")
            data = _xml(package, target if target.startswith("xl/") else "xl/" + target)
            out.append(f"## {sheet.get('name')}")
            rows = list(data.iter(f"{S}row")) if data is not None else []
            for row in rows[:max_rows]:
                values = {}
                for cell in row.iter(f"{S}c"):
                    kind, value = cell.get("t"), cell.find(f"{S}v")
                    if kind == "inlineStr":
                        text = "".join(t.text or "" for t in cell.iter(f"{S}t"))
                    elif value is None:
                        continue
                    elif kind == "s":
                        text = shared[int(value.text)] if value.text and int(value.text) < len(shared) else ""
                    elif kind == "b":
                        text = "TRUE" if value.text == "1" else "FALSE"
                    else:
                        text = value.text or ""
                    values[_column(cell.get("r"))] = text
                if values:
                    out.append(" | ".join(values.get(i, "") for i in range(max(values) + 1)))
            if len(rows) > max_rows:
                out.append(f"...[{len(rows) - max_rows} more rows]")
            out.append("")
    return "\n".join(out).strip()


def read_pptx(path) -> str:
    with zipfile.ZipFile(path) as package:
        slides = sorted((n for n in package.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        out = []
        for number, name in enumerate(slides, 1):
            root = _xml(package, name)
            texts = [t.text for t in root.iter(f"{A}t") if t.text] if root is not None else []
            out.append(f"## Slide {number}\n" + "\n".join(texts))
    return "\n\n".join(out)


def read_pdf(path, max_pages: int = 100) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise DocumentError("reading PDF files needs the pypdf package: pip install pypdf") from None
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            reader.decrypt("")
        pages = [page.extract_text() or "" for page in reader.pages[:max_pages]]
    except Exception as error:
        raise DocumentError(f"could not read this PDF: {error}") from None
    text = "\n\n".join(f"[page {number}]\n{page.strip()}" for number, page in enumerate(pages, 1) if page.strip())
    if not text:
        return "(This PDF has no text layer: it is probably a scan. Send it as an image to read it.)"
    if len(reader.pages) > max_pages:
        text += f"\n...[{len(reader.pages) - max_pages} more pages]"
    return text


def read_any(path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            return read_docx(path)
        if suffix in (".xlsx", ".xlsm"):
            return read_xlsx(path)
        if suffix == ".pptx":
            return read_pptx(path)
        if suffix == ".pdf":
            return read_pdf(path)
    except (zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise DocumentError(f"the file is damaged or not really {suffix}: {error}") from None
    raw = path.read_bytes()
    if suffix in TEXT_FILES or b"\x00" not in raw[:4096]:
        return raw.decode("utf-8", errors="replace")
    raise DocumentError(f"cannot read {suffix or 'this'} files (Word, Excel, PowerPoint, PDF and text files work)")


# ---------- writing ----------
_CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
{overrides}</Types>'''
_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{items}</Relationships>'''
_DOC_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
_WORD_STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/>
</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr>
</w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
{headings}
<w:style w:type="table" w:styleId="Grid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4" w:color="999999"/><w:left w:val="single" w:sz="4" w:color="999999"/>
<w:bottom w:val="single" w:sz="4" w:color="999999"/><w:right w:val="single" w:sz="4" w:color="999999"/>
<w:insideH w:val="single" w:sz="4" w:color="999999"/><w:insideV w:val="single" w:sz="4" w:color="999999"/>
</w:tblBorders></w:tblPr></w:style>
</w:styles>'''
_HEADING = ('<w:style w:type="paragraph" w:styleId="Heading{n}"><w:name w:val="heading {n}"/><w:basedOn w:val="Normal"/>'
            '<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/>'
            '<w:outlineLvl w:val="{level}"/></w:pPr><w:rPr><w:b/><w:sz w:val="{size}"/></w:rPr></w:style>')


def _runs(text: str) -> str:
    """Text with **bold** parts as Word runs."""
    out = []
    for number, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if part:
            bold = "<w:rPr><w:b/></w:rPr>" if number % 2 else ""
            out.append(f'<w:r>{bold}<w:t xml:space="preserve">{_text(part)}</w:t></w:r>')
    return "".join(out)


def _paragraph(text: str, style: str = "") -> str:
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{props}{_runs(text)}</w:p>"


def _table(rows: list[list[str]]) -> str:
    cells = lambda row: "".join(f"<w:tc>{_paragraph(cell)}</w:tc>" for cell in row)
    return ('<w:tbl><w:tblPr><w:tblStyle w:val="Grid"/><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
            + "".join(f"<w:tr>{cells(row)}</w:tr>" for row in rows) + "</w:tbl>")


def write_docx(path, content: str) -> Path:
    """A Word document from simple Markdown: # headings, - lists, **bold**, | tables |, paragraphs."""
    body, table = [], []
    for line in content.splitlines() + [""]:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                table.append(cells)
            continue
        if table:
            body.append(_table(table))
            table = []
        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            body.append(_paragraph(heading.group(2), f"Heading{len(heading.group(1))}"))
        elif re.match(r"^[-*•]\s+", stripped):
            body.append(_paragraph("• " + re.sub(r"^[-*•]\s+", "", stripped)))
        elif stripped:
            body.append(_paragraph(stripped))
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                + "".join(body) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1418" w:right="1418" w:bottom="1418" w:left="1418"/></w:sectPr></w:body></w:document>')
    headings = "".join(_HEADING.format(n=n, level=n - 1, size=size) for n, size in ((1, 36), (2, 30), (3, 26)))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", _CONTENT_TYPES.format(overrides=
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
            'wordprocessingml.document.main+xml"/>\n<Override PartName="/word/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>\n'))
        package.writestr("_rels/.rels", _RELS.format(items=
            f'<Relationship Id="rId1" Type="{_DOC_TYPE}officeDocument" Target="word/document.xml"/>'))
        package.writestr("word/_rels/document.xml.rels", _RELS.format(items=
            f'<Relationship Id="rId1" Type="{_DOC_TYPE}styles" Target="styles.xml"/>'))
        package.writestr("word/document.xml", document)
        package.writestr("word/styles.xml", _WORD_STYLES.format(headings=headings))
    return path


def _cell_name(row: int, column: int) -> str:
    letters, column = "", column + 1
    while column:
        column, rest = divmod(column - 1, 26)
        letters = chr(65 + rest) + letters
    return f"{letters}{row}"


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return float(text) if "." in text else int(text)
    return None


def write_xlsx(path, sheets: dict[str, list[list]]) -> Path:
    """An Excel workbook: {"Sheet name": [[header...], [row...], ...]}; the first row is bold."""
    names = []
    for name in sheets:
        clean = re.sub(r"[\[\]:*?/\\]", " ", str(name)).strip()[:31] or f"Sheet{len(names) + 1}"
        while clean in names:
            clean = (clean[:28] + f" {len(names) + 1}")[:31]
        names.append(clean)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        overrides = ['<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
                     'officedocument.spreadsheetml.sheet.main+xml"/>',
                     '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-'
                     'officedocument.spreadsheetml.styles+xml"/>']
        workbook_rels = [f'<Relationship Id="rId0" Type="{_DOC_TYPE}styles" Target="styles.xml"/>']
        sheet_tags = []
        for number, (name, rows) in enumerate(zip(names, sheets.values()), 1):
            overrides.append(f'<Override PartName="/xl/worksheets/sheet{number}.xml" ContentType="application/'
                             'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
            workbook_rels.append(f'<Relationship Id="rId{number}" Type="{_DOC_TYPE}worksheet" '
                                 f'Target="worksheets/sheet{number}.xml"/>')
            sheet_tags.append(f'<sheet name="{escape(name, {chr(34): "&quot;"})}" sheetId="{number}" r:id="rId{number}"/>')
            xml_rows = []
            for r, row in enumerate(rows, 1):
                cells = []
                for c, value in enumerate(row):
                    if value is None or value == "":
                        continue
                    style = ' s="1"' if r == 1 else ""
                    number_value = _number(value)
                    if number_value is not None:
                        cells.append(f'<c r="{_cell_name(r, c)}"{style}><v>{number_value}</v></c>')
                    else:
                        cells.append(f'<c r="{_cell_name(r, c)}" t="inlineStr"{style}><is><t xml:space="preserve">'
                                     f'{_text(value)}</t></is></c>')
                xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
            package.writestr(f"xl/worksheets/sheet{number}.xml",
                             '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                             f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
        package.writestr("[Content_Types].xml", _CONTENT_TYPES.format(overrides="\n".join(overrides) + "\n"))
        package.writestr("_rels/.rels", _RELS.format(items=
            f'<Relationship Id="rId1" Type="{_DOC_TYPE}officeDocument" Target="xl/workbook.xml"/>'))
        package.writestr("xl/_rels/workbook.xml.rels", _RELS.format(items="".join(workbook_rels)))
        package.writestr("xl/workbook.xml",
                         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                         f'<sheets>{"".join(sheet_tags)}</sheets></workbook>')
        package.writestr("xl/styles.xml",
                         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                         '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                         '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                         '<fills count="2"><fill><patternFill patternType="none"/></fill>'
                         '<fill><patternFill patternType="gray125"/></fill></fills>'
                         '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                         '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                         '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                         '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
                         '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                         '</styleSheet>')
    return path


def rows_from_csv(text: str) -> list[list]:
    """CSV text (comma, semicolon or tab separated) as rows."""
    sample = text[:2000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text.strip()), dialect) if any(cell.strip() for cell in row)]
