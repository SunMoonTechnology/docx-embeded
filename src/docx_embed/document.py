"""OOXML helpers: locate headings and inject OLE icon objects into document.xml."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import BinaryIO
from xml.etree import ElementTree as ET

from .cfb import build_ole_package_bin
from .icon import build_icon_emf

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
V_NS = "urn:schemas-microsoft-com:vml"
O_NS = "urn:schemas-microsoft-com:office:office"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

NSMAP = {
    "w": W_NS,
    "r": R_NS,
    "v": V_NS,
    "o": O_NS,
}

for prefix, uri in NSMAP.items():
    ET.register_namespace(prefix, uri)

REL_OLE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject"
REL_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
CT_OLE = "application/vnd.openxmlformats-officedocument.oleObject"
CT_EMF = "image/x-emf"

HEADING_STYLE_RE = re.compile(r"^(?:Heading|标题)\s*(\d+)$", re.I)


def _qn(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _paragraphs(body: ET.Element) -> list[ET.Element]:
    return [c for c in list(body) if _local(c.tag) == "p"]


def _paragraph_style(p: ET.Element) -> str | None:
    pPr = p.find(_qn(W_NS, "pPr"))
    if pPr is None:
        return None
    pStyle = pPr.find(_qn(W_NS, "pStyle"))
    if pStyle is None:
        return None
    return pStyle.get(_qn(W_NS, "val")) or pStyle.get("val")


def _outline_level(p: ET.Element) -> int | None:
    pPr = p.find(_qn(W_NS, "pPr"))
    if pPr is not None:
        outline = pPr.find(_qn(W_NS, "outlineLvl"))
        if outline is not None:
            raw = outline.get(_qn(W_NS, "val")) or outline.get("val")
            if raw is not None:
                try:
                    return int(raw) + 1
                except ValueError:
                    pass
    style = _paragraph_style(p)
    if style:
        m = HEADING_STYLE_RE.match(style.strip())
        if m:
            return int(m.group(1))
    return None


def _paragraph_text(p: ET.Element) -> str:
    return "".join(
        node.text
        for node in p.iter()
        if _local(node.tag) == "t" and node.text
    )


def find_heading_paragraph_index(
    body: ET.Element,
    level: int,
    title: str | None = None,
    occurrence: int = 1,
) -> int:
    if not 1 <= level <= 9:
        raise ValueError("heading level must be 1..9")
    if occurrence < 1:
        raise ValueError("occurrence must be >= 1")

    matched = 0
    for idx, p in enumerate(_paragraphs(body)):
        if _outline_level(p) != level:
            continue
        if title is not None and _paragraph_text(p).strip() != title.strip():
            continue
        matched += 1
        if matched == occurrence:
            return idx
    raise LookupError(
        f"heading not found: level={level!r}, title={title!r}, occurrence={occurrence}"
    )


def _next_rid(rels_root: ET.Element) -> str:
    max_id = 0
    for rel in rels_root:
        if _local(rel.tag) != "Relationship":
            continue
        rid = rel.get("Id") or ""
        m = re.match(r"rId(\d+)$", rid)
        if m:
            max_id = max(max_id, int(m.group(1)))
    return f"rId{max_id + 1}"


def _ensure_override(ct_root: ET.Element, part_name: str, content_type: str) -> None:
    for ov in ct_root:
        if _local(ov.tag) == "Override" and ov.get("PartName") == part_name:
            ov.set("ContentType", content_type)
            return
    ET.SubElement(
        ct_root,
        _qn(CT_NS, "Override"),
        {"PartName": part_name, "ContentType": content_type},
    )


def _ensure_default(ct_root: ET.Element, extension: str, content_type: str) -> None:
    for d in ct_root:
        if _local(d.tag) == "Default" and (d.get("Extension") or "").lower() == extension.lower():
            return
    ET.SubElement(
        ct_root,
        _qn(CT_NS, "Default"),
        {"Extension": extension, "ContentType": content_type},
    )


def _next_media_names(existing: list[str]) -> tuple[str, str]:
    ole_n = 1
    emf_n = 1
    for name in existing:
        norm = name.replace("\\", "/")
        m = re.search(r"word/embeddings/oleObject(\d+)\.bin$", norm)
        if m:
            ole_n = max(ole_n, int(m.group(1)) + 1)
        m = re.search(r"word/media/image(\d+)\.emf$", norm, re.I)
        if m:
            emf_n = max(emf_n, int(m.group(1)) + 1)
    return f"word/embeddings/oleObject{ole_n}.bin", f"word/media/image{emf_n}.emf"


def _build_object_paragraph(
    image_rid: str,
    ole_rid: str,
    shape_id: str,
    object_id: str,
    width_pt: float = 57.75,
    height_pt: float = 62.25,
) -> ET.Element:
    p = ET.Element(_qn(W_NS, "p"))
    r = ET.SubElement(p, _qn(W_NS, "r"))
    obj = ET.SubElement(
        r,
        _qn(W_NS, "object"),
        {
            _qn(W_NS, "dxaOrig"): str(int(width_pt * 20)),
            _qn(W_NS, "dyaOrig"): str(int(height_pt * 20)),
        },
    )

    shapetype = ET.SubElement(
        obj,
        _qn(V_NS, "shapetype"),
        {
            "id": "_x0000_t75",
            "coordsize": "21600,21600",
            _qn(O_NS, "spt"): "75",
            _qn(O_NS, "preferrelative"): "t",
            "path": "m@4@5l@4@11@9@11@9@5xe",
            "filled": "f",
            "stroked": "f",
        },
    )
    ET.SubElement(shapetype, _qn(V_NS, "stroke"), {"joinstyle": "miter"})
    formulas = ET.SubElement(shapetype, _qn(V_NS, "formulas"))
    for eqn in (
        "if lineDrawn pixelLineWidth 0",
        "sum @0 1 0",
        "sum 0 0 @1",
        "prod @2 1 2",
        "prod @3 21600 pixelWidth",
        "prod @3 21600 pixelHeight",
        "sum @0 0 1",
        "prod @6 1 2",
        "prod @7 21600 pixelWidth",
        "sum @8 21600 0",
        "prod @7 21600 pixelHeight",
        "sum @10 21600 0",
    ):
        ET.SubElement(formulas, _qn(V_NS, "f"), {"eqn": eqn})
    ET.SubElement(
        shapetype,
        _qn(V_NS, "path"),
        {
            _qn(O_NS, "extrusionok"): "f",
            "gradientshapeok": "t",
            _qn(O_NS, "connecttype"): "rect",
        },
    )
    ET.SubElement(
        shapetype, _qn(O_NS, "lock"), {_qn(V_NS, "ext"): "edit", "aspectratio": "t"}
    )

    shape = ET.SubElement(
        obj,
        _qn(V_NS, "shape"),
        {
            "id": shape_id,
            "type": "#_x0000_t75",
            "style": f"width:{width_pt:g}pt;height:{height_pt:g}pt",
            _qn(O_NS, "ole"): "",
        },
    )
    ET.SubElement(
        shape,
        _qn(V_NS, "imagedata"),
        {_qn(R_NS, "id"): image_rid, _qn(O_NS, "title"): ""},
    )
    ET.SubElement(
        obj,
        _qn(O_NS, "OLEObject"),
        {
            "Type": "Embed",
            "ProgID": "Package",
            "ShapeID": shape_id,
            "DrawAspect": "Icon",
            "ObjectID": object_id,
            _qn(R_NS, "id"): ole_rid,
        },
    )
    return p


def _serialize_opc_xml(root: ET.Element, default_ns: str) -> bytes:
    """Serialize OPC XML using a default xmlns (no prefix), as Word expects."""
    raw = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    text = raw.decode("utf-8")
    text = text.replace("xmlns:ns0=", "xmlns=")
    text = text.replace("<ns0:", "<").replace("</ns0:", "</")
    text = text.replace("xmlns:ct=", "xmlns=")
    text = text.replace("<ct:", "<").replace("</ct:", "</")
    if f'xmlns="{default_ns}"' not in text:
        text = re.sub(
            r"(<\?xml[^?]*\?>\s*<)([A-Za-z_][\w.-]*)",
            rf'\1\2 xmlns="{default_ns}"',
            text,
            count=1,
        )
    return text.encode("utf-8")


class DocxEmbedder:
    """Embed OLE Package attachments into an existing .docx file."""

    def __init__(self, source: str | Path | BinaryIO):
        if hasattr(source, "read"):
            self._buffer = io.BytesIO(source.read())
        else:
            self._buffer = io.BytesIO(Path(source).read_bytes())
        self._object_counter = 0

    def insert_at_paragraph(
        self,
        file_path: str | Path,
        index: int,
        *,
        display_name: str | None = None,
        after: bool = True,
    ) -> int:
        """
        Insert an attachment icon relative to a 0-based ``w:p`` index.

        Default: new paragraph *after* the indexed paragraph.
        Returns the index of the inserted paragraph.
        """
        path = Path(file_path)
        return self._insert(
            path.read_bytes(),
            display_name or path.name,
            paragraph_index=index,
            after=after,
            source_path=str(path),
        )

    def insert_after_heading(
        self,
        file_path: str | Path,
        level: int,
        *,
        title: str | None = None,
        occurrence: int = 1,
        display_name: str | None = None,
    ) -> int:
        """
        Insert attachment as body content immediately after a heading.

        ``level`` is 1..9 (``Heading1`` / ``标题1`` / ``outlineLvl``).
        """
        path = Path(file_path)
        self._buffer.seek(0)
        with zipfile.ZipFile(self._buffer, "r") as zf:
            doc_xml = zf.read("word/document.xml")
        root = ET.fromstring(doc_xml)
        body = root.find(_qn(W_NS, "body"))
        if body is None:
            raise ValueError("document.xml has no w:body")
        heading_idx = find_heading_paragraph_index(
            body, level, title=title, occurrence=occurrence
        )
        return self._insert(
            path.read_bytes(),
            display_name or path.name,
            paragraph_index=heading_idx,
            after=True,
            source_path=str(path),
        )

    def _insert(
        self,
        file_data: bytes,
        filename: str,
        *,
        paragraph_index: int,
        after: bool,
        source_path: str | None,
    ) -> int:
        self._buffer.seek(0)
        with zipfile.ZipFile(self._buffer, "r") as zin:
            parts = {n.replace("\\", "/"): zin.read(n) for n in zin.namelist()}

        doc_root = ET.fromstring(parts["word/document.xml"])
        body = doc_root.find(_qn(W_NS, "body"))
        if body is None:
            raise ValueError("document.xml has no w:body")

        paras = _paragraphs(body)
        if paragraph_index < 0 or paragraph_index >= len(paras):
            raise IndexError(
                f"paragraph index {paragraph_index} out of range (0..{max(len(paras) - 1, 0)})"
            )

        rels_path = "word/_rels/document.xml.rels"
        rels_root = ET.fromstring(parts[rels_path])
        ct_root = ET.fromstring(parts["[Content_Types].xml"])

        ole_zip, emf_zip = _next_media_names(list(parts))
        image_rid = _next_rid(rels_root)
        ET.SubElement(
            rels_root,
            _qn(PKG_REL_NS, "Relationship"),
            {
                "Id": image_rid,
                "Type": REL_IMAGE,
                "Target": emf_zip[len("word/") :],
            },
        )
        ole_rid = _next_rid(rels_root)
        ET.SubElement(
            rels_root,
            _qn(PKG_REL_NS, "Relationship"),
            {
                "Id": ole_rid,
                "Type": REL_OLE,
                "Target": ole_zip[len("word/") :],
            },
        )

        _ensure_default(ct_root, "bin", CT_OLE)
        _ensure_default(ct_root, "emf", CT_EMF)
        _ensure_override(ct_root, "/" + ole_zip, CT_OLE)
        _ensure_override(ct_root, "/" + emf_zip, CT_EMF)

        self._object_counter += 1
        shape_id = f"_x0000_i{1024 + self._object_counter}"
        object_id = f"_{1500000000 + self._object_counter}"
        icon_emf, icon_w, icon_h = build_icon_emf(filename)
        new_p = _build_object_paragraph(
            image_rid, ole_rid, shape_id, object_id, width_pt=icon_w, height_pt=icon_h
        )

        target = paras[paragraph_index]
        body_children = list(body)
        insert_pos = body_children.index(target) + (1 if after else 0)

        sect = None
        if body_children and _local(body_children[-1].tag) == "sectPr":
            sect = body_children[-1]
            body.remove(sect)

        # Recompute insert_pos after possible sectPr removal
        body_children = list(body)
        target = paras[paragraph_index]
        insert_pos = body_children.index(target) + (1 if after else 0)
        body.insert(insert_pos, new_p)
        if sect is not None:
            body.append(sect)

        parts["word/document.xml"] = ET.tostring(
            doc_root, encoding="utf-8", xml_declaration=True
        )
        parts[rels_path] = _serialize_opc_xml(rels_root, default_ns=PKG_REL_NS)
        parts["[Content_Types].xml"] = _serialize_opc_xml(ct_root, default_ns=CT_NS)
        parts[ole_zip] = build_ole_package_bin(
            filename, file_data, source_path=source_path
        )
        parts[emf_zip] = icon_emf

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            if "[Content_Types].xml" in parts:
                zout.writestr("[Content_Types].xml", parts["[Content_Types].xml"])
            for name, data in parts.items():
                if name == "[Content_Types].xml":
                    continue
                zout.writestr(name, data)

        self._buffer = out
        return paragraph_index + 1 if after else paragraph_index

    def save(self, destination: str | Path | BinaryIO) -> None:
        data = self.bytes()
        if hasattr(destination, "write"):
            destination.write(data)
        else:
            Path(destination).write_bytes(data)

    def bytes(self) -> bytes:
        self._buffer.seek(0)
        return self._buffer.read()
