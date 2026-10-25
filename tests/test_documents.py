"""Word, Excel and PDF: read and write documents without Office (Word/Excel need nothing extra)."""

import zipfile
from xml.etree import ElementTree

import pytest

from pocketagent import documents
from pocketagent.approvals import ApprovalEngine, AuditLog, RuleStore
from pocketagent.tools import ToolContext, ToolRegistry


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF with one line of text (Helvetica), with a correct cross-reference table."""
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def well_formed(path):
    with zipfile.ZipFile(path) as package:
        for name in package.namelist():
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(package.read(name))       # raises if the XML is broken
        return package.namelist()


# ---------- Word ----------
def test_word_documents_are_written_and_read_back(tmp_path):
    path = tmp_path / "rapor.docx"
    documents.write_docx(path, "# Haftalık rapor\nGiriş **önemli** metin & <özel> karakterler.\n\n"
                               "- birinci madde\n- ikinci madde\n\n| Ad | Puan |\n|---|---|\n| Elif | 90 |")
    parts = well_formed(path)
    assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml"} <= set(parts)
    text = documents.read_docx(path)
    assert "# Haftalık rapor" in text
    assert "Giriş önemli metin & <özel> karakterler." in text
    assert "• birinci madde" in text and "| Elif | 90 |" in text
    assert b"<w:b/>" in zipfile.ZipFile(path).read("word/document.xml")        # **önemli** is bold


# ---------- Excel ----------
def test_excel_files_are_written_and_read_back(tmp_path):
    path = tmp_path / "notlar.xlsx"
    documents.write_xlsx(path, {"Notlar": [["Ad", "Puan"], ["Elif", 90], ["Ali", 72.5]]})
    well_formed(path)
    sheet = zipfile.ZipFile(path).read("xl/worksheets/sheet1.xml").decode()
    assert "<v>90</v>" in sheet                                   # numbers stay numbers
    text = documents.read_xlsx(path)
    assert "## Notlar" in text and "Ad | Puan" in text and "Elif | 90" in text and "Ali | 72.5" in text


def test_excel_files_made_by_excel_with_shared_strings_are_read(tmp_path):
    path = tmp_path / "excel.xlsx"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                         '<sheets><sheet name="Satışlar" sheetId="1" r:id="rId7"/></sheets></workbook>')
        package.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId7" Type="worksheet" Target="worksheets/data.xml"/></Relationships>')
        package.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                         '<si><t>Ürün</t></si><si><r><t>Kal</t></r><r><t>em</t></r></si></sst>')
        package.writestr("xl/worksheets/data.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                         '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1"><v>3</v></c></row>'
                         '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="b"><v>1</v></c></row></sheetData></worksheet>')
    text = documents.read_xlsx(path)
    assert "## Satışlar" in text and "Ürün |  | 3" in text and "Kalem | TRUE" in text


# ---------- PDF ----------
def test_pdf_text_is_read(tmp_path):
    path = tmp_path / "belge.pdf"
    path.write_bytes(tiny_pdf("Hello from a PDF"))
    assert "Hello from a PDF" in documents.read_pdf(path)
    assert "Hello from a PDF" in documents.read_any(path)


def test_unknown_binary_files_are_explained(tmp_path):
    path = tmp_path / "x.bin"
    path.write_bytes(b"\x00\x01\x02binary")
    with pytest.raises(documents.DocumentError, match="cannot read"):
        documents.read_any(path)


# ---------- the tools ----------
def registry():
    reg = ToolRegistry()
    reg.load_builtin()
    return reg


def test_documents_in_the_workspace_are_read_freely_and_count_as_outside_content(tmp_path):
    ctx = ToolContext(workspace=tmp_path / "ws")
    (tmp_path / "ws" / "inbox").mkdir(parents=True)
    documents.write_xlsx(tmp_path / "ws" / "inbox" / "a.xlsx", {"S": [["x", 1]]})
    assert "x | 1" in registry().call("read_document", {"path": "inbox/a.xlsx"}, ctx)
    assert ctx.tainted_by == ["read_document(inbox/a.xlsx)"]


def test_documents_outside_the_workspace_need_computer_use_and_approval(tmp_path):
    outside = tmp_path / "Desktop" / "cv.docx"
    outside.parent.mkdir()
    documents.write_docx(outside, "Aykut Uçar")
    ctx = ToolContext(workspace=tmp_path / "ws")
    assert "computer use" in registry().call("read_document", {"path": str(outside)}, ctx)
    engine = ApprovalEngine(RuleStore(tmp_path), AuditLog(tmp_path), lambda: True, timeout=5)
    asked = []
    engine.notifiers.append(lambda p: asked.append(p) or engine.answer(p.id, True))
    ctx = ToolContext(workspace=tmp_path / "ws", approvals=engine, computer_use=True, generation=engine.generation)
    assert "Aykut Uçar" in registry().call("read_document", {"path": str(outside)}, ctx)
    assert asked[0].action.scope == {"folder": str(outside.parent.resolve())}


def test_word_and_excel_files_are_made_in_the_workspace_and_delivered(tmp_path):
    ctx = ToolContext(workspace=tmp_path / "ws")
    reg = registry()
    assert "reports/r.docx" in reg.call("write_word", {"path": "reports/r.docx", "content": "# Başlık\nMetin"}, ctx)
    assert "tables/t.xlsx" in reg.call("write_excel", {"path": "tables/t.xlsx", "csv": "Ad;Puan\nElif;90"}, ctx)
    assert ctx.files == ["reports/r.docx", "tables/t.xlsx"]
    assert "Elif | 90" in documents.read_xlsx(tmp_path / "ws" / "tables" / "t.xlsx")
    assert "outside the workspace" in reg.call("write_word", {"path": "../evil.docx", "content": "x"}, ctx)
