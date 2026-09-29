"""Run without pytest: python scripts/smoke_test.py"""

from __future__ import annotations

import io
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from docx_embed import DocxEmbedder
from docx_embed.cfb import build_ole10_native, build_ole_package_bin
from docx_embed.icon import build_icon_emf

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def minimal_docx(heading_text: str = "附件", heading_level: int = 1) -> bytes:
    style = f"Heading{heading_level}"
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="{style}"/></w:pPr>
      <w:r><w:t>{heading_text}</w:t></w:r>
    </w:p>
    <w:p><w:r><w:t>正文段落</w:t></w:r></w:p>
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


def main() -> None:
    payload = build_ole10_native("demo.txt", b"hello")
    assert b"demo.txt\x00" in payload
    assert b"\x00\x00\x03\x00" in payload
    assert b"hello" in payload

    blob = build_ole_package_bin("a.pdf", b"%PDF-1.4 demo")
    assert blob[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    icon, _, _ = build_icon_emf("demo.txt")
    assert b"d\x00e\x00m\x00o\x00.\x00t\x00x\x00t" in icon

    td = Path(tempfile.mkdtemp(prefix="docx-embed-"))
    src = td / "in.docx"
    src.write_bytes(minimal_docx("附录材料", 1))
    attach = td / "report.txt"
    attach.write_text("secret attachment payload", encoding="utf-8")

    emb = DocxEmbedder(src)
    new_idx = emb.insert_after_heading(attach, level=1, title="附录材料")
    assert new_idx == 1, new_idx

    out = td / "out.docx"
    emb.save(out)

    with zipfile.ZipFile(out, "r") as zf:
        names = [n.replace("\\", "/") for n in zf.namelist()]
        assert any("embeddings/oleObject" in n for n in names), names
        assert any(n.endswith(".emf") for n in names), names
        ole = next(n for n in names if "oleObject" in n)
        ole_data = zf.read(ole)
        assert b"secret attachment payload" in ole_data

        doc = ET.fromstring(zf.read("word/document.xml"))
        body = doc.find(f"{{{W}}}body")
        assert body is not None
        paras = [c for c in body if c.tag.endswith("}p")]
        assert len(paras) == 3, len(paras)
        assert any(el.tag.endswith("}object") for el in paras[1].iter())

        rels = zf.read("word/_rels/document.xml.rels").decode("utf-8")
        assert "oleObject" in rels
        assert "image" in rels.lower() or "media/" in rels

    print("ALL TESTS PASSED")
    print("sample:", out)


if __name__ == "__main__":
    main()
