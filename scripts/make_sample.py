"""Generate samples/demo.docx so you can open it in Word or WPS."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from docx_embed import DocxEmbedder
from smoke_test import minimal_docx

OUT_DIR = ROOT / "samples"


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    src = OUT_DIR / "input.docx"
    note = OUT_DIR / "note.txt"
    out = OUT_DIR / "demo.docx"

    src.write_bytes(minimal_docx("附录", 1))
    note.write_text("这是嵌入的附件内容。\n如果能打开本文件，说明 OLE 嵌入成功。\n", encoding="utf-8")

    emb = DocxEmbedder(src)
    emb.insert_after_heading(note, level=1, title="附录", display_name="note.txt")
    emb.save(out)
    print(out)


if __name__ == "__main__":
    main()
