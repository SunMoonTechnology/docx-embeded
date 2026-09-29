"""Icon shown for an embedded attachment: document glyph plus filename."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

_ICON_DIB = Path(__file__).with_name("package_icon.dib")
_ICON_PX = 32


def _emf_record(record_type: int, payload: bytes = b"") -> bytes:
    size = 8 + len(payload)
    pad = (4 - (size % 4)) % 4
    if pad:
        payload += b"\x00" * pad
        size = 8 + len(payload)
    return struct.pack("<II", record_type, size) + payload


def build_default_icon_emf(label: str = "FILE") -> bytes:
    """Fallback page icon used when GDI is unavailable. ``label`` is unused."""
    del label
    records: list[bytes] = []
    header_payload = b"".join(
        [
            struct.pack("<iiii", 0, 0, 47, 55),
            struct.pack("<iiii", 0, 0, 1200, 1400),
            struct.pack("<I", 0x464D4520),
            struct.pack("<I", 0x00010000),
            struct.pack("<II", 0, 0),
            struct.pack("<HH", 2, 0),
            struct.pack("<II", 0, 0),
            struct.pack("<I", 0),
            struct.pack("<ii", 96, 96),
            struct.pack("<ii", 320, 240),
        ]
    )
    records.append(_emf_record(1, header_payload))
    records.append(_emf_record(10, struct.pack("<ii", 0, 0)))
    records.append(_emf_record(9, struct.pack("<ii", 48, 56)))
    records.append(_emf_record(39, struct.pack("<IIII", 1, 0, 0x00FFFFFF, 0)))
    records.append(_emf_record(37, struct.pack("<I", 1)))
    records.append(_emf_record(38, struct.pack("<IIiiI", 2, 0, 1, 0, 0x00000000)))
    records.append(_emf_record(37, struct.pack("<I", 2)))
    records.append(_emf_record(43, struct.pack("<iiii", 12, 2, 36, 34)))
    records.append(_emf_record(43, struct.pack("<iiii", 16, 8, 32, 10)))
    records.append(_emf_record(43, struct.pack("<iiii", 16, 13, 32, 15)))
    records.append(_emf_record(43, struct.pack("<iiii", 16, 18, 28, 20)))
    records.append(_emf_record(14, struct.pack("<III", 0, 16, 0)))
    body = bytearray(b"".join(records))
    struct.pack_into("<I", body, 48, len(body))
    struct.pack_into("<I", body, 52, len(records))
    return bytes(body)


def build_icon_emf(label: str) -> tuple[bytes, float, float]:
    """Return ``(emf_bytes, width_pt, height_pt)`` for the attachment icon."""
    name = (label or "file").replace("/", "\\").split("\\")[-1] or "file"
    if sys.platform == "win32":
        try:
            return _build_icon_emf_gdi(name)
        except OSError:
            pass
    emf = build_default_icon_emf(name)
    return emf, 48.0, 56.0


def _build_icon_emf_gdi(label: str) -> tuple[bytes, float, float]:
    import ctypes
    from ctypes import wintypes

    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    msimg32 = ctypes.WinDLL("msimg32", use_last_error=True)

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    class LOGFONTW(ctypes.Structure):
        _fields_ = [
            ("lfHeight", ctypes.c_long),
            ("lfWidth", ctypes.c_long),
            ("lfEscapement", ctypes.c_long),
            ("lfOrientation", ctypes.c_long),
            ("lfWeight", ctypes.c_long),
            ("lfItalic", ctypes.c_byte),
            ("lfUnderline", ctypes.c_byte),
            ("lfStrikeOut", ctypes.c_byte),
            ("lfCharSet", ctypes.c_byte),
            ("lfOutPrecision", ctypes.c_byte),
            ("lfClipPrecision", ctypes.c_byte),
            ("lfQuality", ctypes.c_byte),
            ("lfPitchAndFamily", ctypes.c_byte),
            ("lfFaceName", ctypes.c_wchar * 32),
        ]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [
            ("BlendOp", ctypes.c_byte),
            ("BlendFlags", ctypes.c_byte),
            ("SourceConstantAlpha", ctypes.c_byte),
            ("AlphaFormat", ctypes.c_byte),
        ]

    gdi32.CreateEnhMetaFileW.argtypes = [
        wintypes.HDC,
        wintypes.LPCWSTR,
        ctypes.POINTER(RECT),
        wintypes.LPCWSTR,
    ]
    gdi32.CreateEnhMetaFileW.restype = wintypes.HDC
    gdi32.CloseEnhMetaFile.argtypes = [wintypes.HDC]
    gdi32.CloseEnhMetaFile.restype = wintypes.HENHMETAFILE
    gdi32.GetEnhMetaFileBits.argtypes = [wintypes.HENHMETAFILE, wintypes.UINT, ctypes.c_void_p]
    gdi32.GetEnhMetaFileBits.restype = wintypes.UINT
    gdi32.DeleteEnhMetaFile.argtypes = [wintypes.HENHMETAFILE]
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC,
        ctypes.c_void_p,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.GetDeviceCaps.restype = ctypes.c_int
    gdi32.CreateFontIndirectW.argtypes = [ctypes.POINTER(LOGFONTW)]
    gdi32.CreateFontIndirectW.restype = wintypes.HFONT
    gdi32.GetTextExtentPoint32W.argtypes = [
        wintypes.HDC,
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.POINTER(SIZE),
    ]
    gdi32.GetTextExtentPoint32W.restype = wintypes.BOOL
    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    gdi32.TextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
    gdi32.TextOutW.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    msimg32.AlphaBlend.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        BLENDFUNCTION,
    ]
    msimg32.AlphaBlend.restype = wintypes.BOOL

    dib = _ICON_DIB.read_bytes()
    bmi = dib[:52]
    bits = dib[52:]
    if len(bits) != _ICON_PX * _ICON_PX * 4:
        raise OSError("package icon bitmap is incomplete")

    screen = user32.GetDC(None)
    if not screen:
        raise OSError("GetDC failed")
    try:
        # Use the reference device's real pixel size. LOGPIXELSX is often
        # virtualized (96) and clips the filename out of the metafile frame.
        horz_res = gdi32.GetDeviceCaps(screen, 8) or 1920
        vert_res = gdi32.GetDeviceCaps(screen, 10) or 1080
        horz_mm = gdi32.GetDeviceCaps(screen, 4) or 698
        vert_mm = gdi32.GetDeviceCaps(screen, 6) or 393

        font = _create_font(gdi32, LOGFONTW)
        measure_dc = gdi32.CreateCompatibleDC(screen)
        if not measure_dc or not font:
            raise OSError("font setup failed")
        old_font = gdi32.SelectObject(measure_dc, font)
        text_size = SIZE()
        if not gdi32.GetTextExtentPoint32W(measure_dc, label, len(label), ctypes.byref(text_size)):
            raise OSError("GetTextExtentPoint32W failed")
        gdi32.SelectObject(measure_dc, old_font)
        gdi32.DeleteDC(measure_dc)

        pad_x = 4
        gap = 1
        width_px = max(_ICON_PX, int(text_size.cx)) + pad_x * 2
        height_px = _ICON_PX + gap + int(text_size.cy) + 2

        def to_himetric(px: int, res: int, mm: int) -> int:
            return max(1, int(round(px * mm * 100 / res)))

        frame = RECT(
            0,
            0,
            to_himetric(width_px, horz_res, horz_mm),
            to_himetric(height_px, vert_res, vert_mm),
        )
        meta_dc = gdi32.CreateEnhMetaFileW(screen, None, ctypes.byref(frame), None)
        if not meta_dc:
            raise OSError("CreateEnhMetaFileW failed")

        bits_ptr = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(
            screen, bmi, 0, ctypes.byref(bits_ptr), None, 0
        )
        if not bitmap or not bits_ptr:
            gdi32.CloseEnhMetaFile(meta_dc)
            raise OSError("CreateDIBSection failed")
        ctypes.memmove(bits_ptr, bits, len(bits))

        mem_dc = gdi32.CreateCompatibleDC(screen)
        old_bmp = gdi32.SelectObject(mem_dc, bitmap)
        icon_x = (width_px - _ICON_PX) // 2
        blend = BLENDFUNCTION(0, 0, 255, 1)
        if not msimg32.AlphaBlend(
            meta_dc, icon_x, 0, _ICON_PX, _ICON_PX, mem_dc, 0, 0, _ICON_PX, _ICON_PX, blend
        ):
            gdi32.SelectObject(mem_dc, old_bmp)
            gdi32.DeleteDC(mem_dc)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteObject(font)
            gdi32.CloseEnhMetaFile(meta_dc)
            raise OSError("AlphaBlend failed")

        gdi32.SelectObject(meta_dc, font)
        gdi32.SetBkMode(meta_dc, 1)  # TRANSPARENT
        gdi32.SetTextColor(meta_dc, 0)
        text_x = (width_px - int(text_size.cx)) // 2
        text_y = _ICON_PX + gap
        if not gdi32.TextOutW(meta_dc, text_x, text_y, label, len(label)):
            raise OSError("TextOutW failed")

        gdi32.SelectObject(mem_dc, old_bmp)
        gdi32.DeleteDC(mem_dc)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteObject(font)

        hemf = gdi32.CloseEnhMetaFile(meta_dc)
        if not hemf:
            raise OSError("CloseEnhMetaFile failed")
        size = gdi32.GetEnhMetaFileBits(hemf, 0, None)
        if not size:
            gdi32.DeleteEnhMetaFile(hemf)
            raise OSError("GetEnhMetaFileBits failed")
        buf = ctypes.create_string_buffer(size)
        got = gdi32.GetEnhMetaFileBits(hemf, size, buf)
        gdi32.DeleteEnhMetaFile(hemf)
        if got != size:
            raise OSError("incomplete EMF")
    finally:
        user32.ReleaseDC(None, screen)

    width_pt = frame.right * 72 / 2540
    height_pt = frame.bottom * 72 / 2540
    return buf.raw, width_pt, height_pt


def _create_font(gdi32, logfont_type):
    for face in ("Microsoft YaHei UI", "Microsoft YaHei", "SimSun", "Arial"):
        lf = logfont_type()
        lf.lfHeight = -12
        lf.lfWeight = 400
        lf.lfCharSet = 1
        lf.lfQuality = 5
        lf.lfFaceName = face
        font = gdi32.CreateFontIndirectW(ctypes_byref(lf))
        if font:
            return font
    raise OSError("CreateFontIndirectW failed")


def ctypes_byref(obj):
    import ctypes

    return ctypes.byref(obj)
