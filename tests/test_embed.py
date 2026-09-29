from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from docx_embed import DocxEmbedder
from docx_embed.cfb import build_ole10_native, build_ole_package_bin, read_streams
from docx_embed.document import find_heading_paragraph_index
from docx_embed.icon import build_icon_emf

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _qn(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _minimal_docx(heading_text: str = "附件", heading_level: int = 1) -> bytes:
    """Build a tiny valid docx with one heading and one body paragraph."""
    style = f"Heading{heading_level}"
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="{style}"/></w:pPr>
      <w:r><w:t>{heading_text}</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>正文段落</w:t></w:r>
    </w:p>
    <w:sectPr/>
  </w:body>
</w:document>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>
"""
    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
</Relationships>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
    return buf.getvalue()


def test_ole10_native_roundtrip_size():
    payload = build_ole10_native("demo.txt", b"hello", source_path=r"C:\docs\demo.txt")
    assert payload[:4] == (len(payload) - 4).to_bytes(4, "little")
    assert payload[4:6] == b"\x02\x00"
    assert b"demo.txt\x00" in payload
    assert b"hello" in payload
    # flags2=0, unknown=3 must be 00 00 03 00, not a single DWORD 3
    assert b"\x00\x00\x03\x00" in payload[:80]


def test_ole_package_has_cfb_magic():
    blob = build_ole_package_bin("a.pdf", b"%PDF-1.4 demo", source_path=r"C:\docs\a.pdf")
    assert blob[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    streams = read_streams(blob)
    native = streams["\x01Ole10Native"]
    assert native.startswith(b"\x02\x00") is False
    assert b"a.pdf\x00" in native
    assert b"%PDF-1.4 demo" in native
    assert streams["\x01CompObj"]
    icon, width_pt, height_pt = build_icon_emf("a.pdf")
    assert len(icon) > 64
    assert width_pt > 0 and height_pt > 0
    assert "a.pdf".encode("utf-16le") in icon


def test_insert_after_heading(tmp_path: Path):
    src = tmp_path / "in.docx"
    src.write_bytes(_minimal_docx("附录材料", 1))
    attach = tmp_path / "report.txt"
    attach.write_text("secret attachment payload", encoding="utf-8")

    emb = DocxEmbedder(src)
    new_idx = emb.insert_after_heading(attach, level=1, title="附录材料")
    assert new_idx == 1

    out = tmp_path / "out.docx"
    emb.save(out)

    with zipfile.ZipFile(out, "r") as zf:
        names = zf.namelist()
        assert any(n.startswith("word/embeddings/oleObject") for n in names)
        assert any(n.endswith(".emf") for n in names)
        ole = next(n for n in names if "oleObject" in n)
        ole_data = zf.read(ole)
        assert ole_data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        assert b"secret attachment payload" in ole_data

        doc = ET.fromstring(zf.read("word/document.xml"))
        body = doc.find(_qn("body"))
        assert body is not None
        paras = [c for c in body if c.tag.endswith("}p") or c.tag == "p"]
        assert len(paras) == 3
        # inserted paragraph should contain w:object
        inserted = paras[1]
        assert any(el.tag.endswith("}object") for el in inserted.iter())


def test_insert_at_paragraph(tmp_path: Path):
    src = tmp_path / "in.docx"
    src.write_bytes(_minimal_docx())
    attach = tmp_path / "x.bin"
    attach.write_bytes(b"\x00\x01\x02")

    emb = DocxEmbedder(src)
    emb.insert_at_paragraph(attach, index=0, after=True)
    data = emb.bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert "word/embeddings/oleObject1.bin" in [n.replace("\\", "/") for n in zf.namelist()]


def test_heading_lookup_missing():
    root = ET.fromstring(
        f'<w:document xmlns:w="{W}"><w:body>'
        f'<w:p><w:r><w:t>no heading</w:t></w:r></w:p>'
        f"</w:body></w:document>"
    )
    body = root.find(_qn("body"))
    with pytest.raises(LookupError):
        find_heading_paragraph_index(body, 1)
