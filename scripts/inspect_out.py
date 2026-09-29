import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from smoke_test import minimal_docx
from docx_embed import DocxEmbedder

td = Path(tempfile.mkdtemp())
src = td / "in.docx"
src.write_bytes(minimal_docx("附录", 1))
attach = td / "a.txt"
attach.write_text("abc", encoding="utf-8")
emb = DocxEmbedder(src)
emb.insert_after_heading(attach, level=1)
out = td / "out.docx"
emb.save(out)
with zipfile.ZipFile(out) as zf:
    print(zf.read("word/document.xml").decode("utf-8"))
    print("---")
    print(zf.read("word/_rels/document.xml.rels").decode("utf-8"))
    print("---")
    print(zf.read("[Content_Types].xml").decode("utf-8"))
print("OUT", out)
