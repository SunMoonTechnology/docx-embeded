"""Basic usage example (requires an existing input.docx)."""

from pathlib import Path

from docx_embed import DocxEmbedder


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    # Replace with your files
    docx_path = root / "input.docx"
    attachment = root / "attachment.pdf"
    if not docx_path.exists() or not attachment.exists():
        print("Place input.docx and attachment.pdf in the project root, then re-run.")
        return

    emb = DocxEmbedder(docx_path)
    emb.insert_after_heading(attachment, level=1)
    emb.save(root / "output.docx")
    print("wrote output.docx")


if __name__ == "__main__":
    main()
