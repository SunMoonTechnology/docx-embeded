"""Minimal Compound File Binary (MS-CFB) writer for OLE Package objects."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field


SECTOR_SIZE = 512
MINI_SECTOR_SIZE = 64
MINI_STREAM_CUTOFF = 4096
DIR_ENTRY_SIZE = 128

FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD

STGTY_STORAGE = 1
STGTY_STREAM = 2
STGTY_ROOT = 5
COLOR_RED = 0
COLOR_BLACK = 1

# OLE Package class: {0003000C-0000-0000-C000-000000000046}
PACKAGE_CLSID = bytes.fromhex("0C00030000000000C000000000000046")


def _u16(n: int) -> bytes:
    return struct.pack("<H", n)


def _u32(n: int) -> bytes:
    return struct.pack("<I", n & 0xFFFFFFFF)


def _i32(n: int) -> bytes:
    return struct.pack("<i", n)


def _pad(data: bytes, size: int) -> bytes:
    rem = len(data) % size
    if rem == 0:
        return data
    return data + b"\x00" * (size - rem)


@dataclass
class _DirEntry:
    name: str
    obj_type: int
    color: int = COLOR_BLACK
    left: int = -1
    right: int = -1
    child: int = -1
    clsid: bytes = field(default_factory=lambda: b"\x00" * 16)
    state: int = 0
    start_sector: int = ENDOFCHAIN
    size: int = 0
    data: bytes = b""


def _dir_entry_bytes(entry: _DirEntry) -> bytes:
    name_utf16 = entry.name.encode("utf-16le") + b"\x00\x00" if entry.name else b""
    if len(name_utf16) > 64:
        raise ValueError(f"CFB name too long: {entry.name!r}")
    name_field = name_utf16.ljust(64, b"\x00")
    name_len = len(name_utf16) if entry.name else 0
    return b"".join(
        [
            name_field,
            _u16(name_len),
            bytes([entry.obj_type & 0xFF, entry.color & 0xFF]),
            _i32(entry.left),
            _i32(entry.right),
            _i32(entry.child),
            entry.clsid,
            _u32(entry.state),
            _u32(0),
            _u32(0),  # create time
            _u32(0),
            _u32(0),  # modify time
            _u32(entry.start_sector),
            _u32(entry.size),
            _u32(0),
        ]
    )


def _unused_dir_entry() -> bytes:
    return (
        b"\x00" * 64
        + _u16(0)
        + b"\x00\x00"
        + _i32(-1)
        + _i32(-1)
        + _i32(-1)
        + b"\x00" * 16
        + _u32(0)
        + _u32(0)
        + _u32(0)
        + _u32(0)
        + _u32(0)
        + _u32(0)
        + _u32(0)
        + _u32(0)
    )


def _cfb_sort_key(name: str) -> tuple[int, ...]:
    def norm(ch: str) -> int:
        o = ord(ch)
        if "a" <= ch <= "z":
            o -= 32
        if o < 0x20:
            return o + 0x10000
        return o

    return tuple(norm(ch) for ch in name)


def _cfb_cmp(a: str, b: str) -> int:
    """MS-CFB name order: code units < 0x20 sort after every other character."""

    def norm(ch: str) -> int:
        o = ord(ch)
        if "a" <= ch <= "z":
            o -= 32
        if o < 0x20:
            return o + 0x10000
        return o

    ia, ib = 0, 0
    while ia < len(a) and ib < len(b):
        da, db = norm(a[ia]), norm(b[ib])
        if da != db:
            return -1 if da < db else 1
        ia += 1
        ib += 1
    if len(a) == len(b):
        return 0
    return -1 if len(a) < len(b) else 1


def _link_red_black(entries: list[_DirEntry]) -> int:
    """Build a valid red-black sibling tree. Returns the root directory index."""
    if len(entries) <= 1:
        return -1

    nodes: dict[int, dict] = {
        i: {"left": None, "right": None, "parent": None, "color": COLOR_RED}
        for i in range(1, len(entries))
    }
    root: int | None = None

    def rotate_left(x: int) -> None:
        nonlocal root
        y = nodes[x]["right"]
        nodes[x]["right"] = nodes[y]["left"]
        if nodes[y]["left"] is not None:
            nodes[nodes[y]["left"]]["parent"] = x
        nodes[y]["parent"] = nodes[x]["parent"]
        if nodes[x]["parent"] is None:
            root = y
        elif x == nodes[nodes[x]["parent"]]["left"]:
            nodes[nodes[x]["parent"]]["left"] = y
        else:
            nodes[nodes[x]["parent"]]["right"] = y
        nodes[y]["left"] = x
        nodes[x]["parent"] = y

    def rotate_right(x: int) -> None:
        nonlocal root
        y = nodes[x]["left"]
        nodes[x]["left"] = nodes[y]["right"]
        if nodes[y]["right"] is not None:
            nodes[nodes[y]["right"]]["parent"] = x
        nodes[y]["parent"] = nodes[x]["parent"]
        if nodes[x]["parent"] is None:
            root = y
        elif x == nodes[nodes[x]["parent"]]["right"]:
            nodes[nodes[x]["parent"]]["right"] = y
        else:
            nodes[nodes[x]["parent"]]["left"] = y
        nodes[y]["right"] = x
        nodes[x]["parent"] = y

    def fixup(z: int) -> None:
        while nodes[z]["parent"] is not None and nodes[nodes[z]["parent"]]["color"] == COLOR_RED:
            parent = nodes[z]["parent"]
            grand = nodes[parent]["parent"]
            if grand is not None and parent == nodes[grand]["left"]:
                uncle = nodes[grand]["right"]
                if uncle is not None and nodes[uncle]["color"] == COLOR_RED:
                    nodes[parent]["color"] = COLOR_BLACK
                    nodes[uncle]["color"] = COLOR_BLACK
                    nodes[grand]["color"] = COLOR_RED
                    z = grand
                else:
                    if z == nodes[parent]["right"]:
                        z = parent
                        rotate_left(z)
                        parent = nodes[z]["parent"]
                        grand = nodes[parent]["parent"]
                    nodes[parent]["color"] = COLOR_BLACK
                    if grand is not None:
                        nodes[grand]["color"] = COLOR_RED
                        rotate_right(grand)
            else:
                uncle = nodes[grand]["left"] if grand is not None else None
                if uncle is not None and nodes[uncle]["color"] == COLOR_RED:
                    nodes[parent]["color"] = COLOR_BLACK
                    nodes[uncle]["color"] = COLOR_BLACK
                    if grand is not None:
                        nodes[grand]["color"] = COLOR_RED
                        z = grand
                else:
                    if z == nodes[parent]["left"]:
                        z = parent
                        rotate_right(z)
                        parent = nodes[z]["parent"]
                        grand = nodes[parent]["parent"]
                    nodes[parent]["color"] = COLOR_BLACK
                    if grand is not None:
                        nodes[grand]["color"] = COLOR_RED
                        rotate_left(grand)
        if root is not None:
            nodes[root]["color"] = COLOR_BLACK

    for idx in range(1, len(entries)):
        nodes[idx]["left"] = None
        nodes[idx]["right"] = None
        nodes[idx]["parent"] = None
        nodes[idx]["color"] = COLOR_RED
        y = None
        x = root
        while x is not None:
            y = x
            x = (
                nodes[x]["left"]
                if _cfb_cmp(entries[idx].name, entries[x].name) < 0
                else nodes[x]["right"]
            )
        nodes[idx]["parent"] = y
        if y is None:
            root = idx
        elif _cfb_cmp(entries[idx].name, entries[y].name) < 0:
            nodes[y]["left"] = idx
        else:
            nodes[y]["right"] = idx
        fixup(idx)

    for idx, node in nodes.items():
        entries[idx].left = -1 if node["left"] is None else node["left"]
        entries[idx].right = -1 if node["right"] is None else node["right"]
        entries[idx].color = node["color"]
    return -1 if root is None else root


class CompoundFileWriter:
    def __init__(self) -> None:
        self._streams: dict[str, bytes] = {}

    def add_stream(self, name: str, data: bytes) -> None:
        self._streams[name] = data

    def dumps(self) -> bytes:
        names = sorted(self._streams, key=lambda n: _cfb_sort_key(n))
        entries: list[_DirEntry] = [
            _DirEntry(name="Root Entry", obj_type=STGTY_ROOT, clsid=PACKAGE_CLSID),
        ]
        for name in names:
            data = self._streams[name]
            entries.append(
                _DirEntry(
                    name=name,
                    obj_type=STGTY_STREAM,
                    size=len(data),
                    data=data,
                )
            )
        entries[0].child = _link_red_black(entries)

        sectors: list[bytes] = []
        fat: list[int] = []

        def alloc(data: bytes) -> int:
            if not data:
                return ENDOFCHAIN
            start = len(sectors)
            blob = _pad(data, SECTOR_SIZE)
            count = len(blob) // SECTOR_SIZE
            for i in range(count):
                sectors.append(blob[i * SECTOR_SIZE : (i + 1) * SECTOR_SIZE])
                fat.append(ENDOFCHAIN if i == count - 1 else start + i + 1)
            return start

        # Mini stream assembly
        mini_stream = bytearray()
        mini_fat: list[int] = []

        def alloc_mini(data: bytes) -> int:
            if not data:
                return ENDOFCHAIN
            start = len(mini_fat)
            blob = _pad(data, MINI_SECTOR_SIZE)
            count = len(blob) // MINI_SECTOR_SIZE
            for i in range(count):
                mini_stream.extend(blob[i * MINI_SECTOR_SIZE : (i + 1) * MINI_SECTOR_SIZE])
                mini_fat.append(ENDOFCHAIN if i == count - 1 else start + i + 1)
            return start

        for entry in entries[1:]:
            if entry.size < MINI_STREAM_CUTOFF:
                entry.start_sector = alloc_mini(entry.data)
            else:
                entry.start_sector = alloc(entry.data)

        entries[0].size = len(mini_stream)
        entries[0].start_sector = alloc(bytes(mini_stream)) if mini_stream else ENDOFCHAIN

        mini_fat_start = ENDOFCHAIN
        mini_fat_count = 0
        if mini_fat:
            mf = b"".join(_u32(x) for x in mini_fat)
            mini_fat_start = alloc(mf)
            mini_fat_count = len(_pad(mf, SECTOR_SIZE)) // SECTOR_SIZE

        dir_blob = b"".join(_dir_entry_bytes(e) for e in entries)
        while len(dir_blob) % SECTOR_SIZE:
            dir_blob += _unused_dir_entry()
        dir_start = alloc(dir_blob)

        # FAT sectors (version 3, max 109 FAT sectors via header DIFAT)
        fat_count = 0
        while True:
            needed = (len(sectors) + fat_count + 127) // 128
            if needed == fat_count:
                break
            fat_count = needed
            if fat_count > 109:
                raise ValueError("attachment too large for minimal CFB writer")

        fat_first = len(sectors)
        # Placeholder FAT chain entries for the FAT sectors themselves
        for _ in range(fat_count):
            sectors.append(b"\x00" * SECTOR_SIZE)  # filled below
            fat.append(FATSECT)

        while len(fat) % 128:
            fat.append(FREESECT)

        for i in range(fat_count):
            chunk = fat[i * 128 : (i + 1) * 128]
            sectors[fat_first + i] = b"".join(_u32(x) for x in chunk)

        difat = [fat_first + i for i in range(fat_count)] + [FREESECT] * (109 - fat_count)

        header = bytearray(SECTOR_SIZE)
        header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        header[24:26] = _u16(0x003E)
        header[26:28] = _u16(0x0003)
        header[28:30] = _u16(0xFFFE)
        header[30:32] = _u16(9)
        header[32:34] = _u16(6)
        header[44:48] = _u32(fat_count)
        header[48:52] = _u32(dir_start)
        header[56:60] = _u32(MINI_STREAM_CUTOFF)
        header[60:64] = _u32(mini_fat_start)
        header[64:68] = _u32(mini_fat_count)
        header[68:72] = _u32(ENDOFCHAIN)
        header[72:76] = _u32(0)
        for i, s in enumerate(difat):
            header[76 + 4 * i : 80 + 4 * i] = _u32(s)

        return bytes(header) + b"".join(sectors)


def _ansi_z(text: str) -> bytes:
    """Null-terminated ANSI string. Chinese Windows uses GBK (mbcs)."""
    for encoding in ("mbcs", "gbk", "cp1252"):
        try:
            return text.encode(encoding) + b"\x00"
        except (LookupError, UnicodeEncodeError):
            continue
    return text.encode("ascii", "replace") + b"\x00"


def _utf16_prefixed(text: str) -> bytes:
    raw = text.encode("utf-16le")
    return _u32(len(raw) // 2) + raw


def build_ole10_native(filename: str, file_data: bytes, source_path: str | None = None) -> bytes:
    """OLE Package native stream, matching the layout Word's Packager writes.

    Layout after the leading size DWORD:
    flags1 (2), label\\0, original path\\0, flags2 (2), unknown (2),
    length-prefixed command path, data size, data, then UTF-16 command/label/path.
    """
    base = filename.replace("/", "\\")
    label = base.split("\\")[-1] or "file.bin"
    original = (source_path or base).replace("/", "\\")
    # Packager writes the embedded bytes to this path, then opens it.
    temp_root = os.environ.get("TEMP") or os.environ.get("TMP") or r"C:\Windows\Temp"
    command = os.path.join(temp_root, label).replace("/", "\\")

    command_ansi = _ansi_z(command)
    body = bytearray()
    body += _u16(2)  # flags1: embedded file
    body += _ansi_z(label)
    body += _ansi_z(original)
    body += _u16(0)  # flags2
    body += _u16(3)  # unknown1; together these are the 00000300 marker
    body += _u32(len(command_ansi))
    body += command_ansi
    body += _u32(len(file_data))
    body += file_data
    body += _utf16_prefixed(command)
    body += _utf16_prefixed(label)
    body += _utf16_prefixed(original)
    return _u32(len(body)) + bytes(body)


def build_comp_obj_stream() -> bytes:
    """\\x01CompObj identifying this storage as an OLE Package."""
    user_type = b"OLE Package\x00"
    clipboard = b"Package\x00"
    return b"".join(
        [
            bytes.fromhex("0100FEFF"),  # header reserved
            _u32(0x00000A03),
            _u32(0xFFFFFFFF),
            _u32(len(user_type)),
            user_type,
            _u32(len(clipboard)),
            clipboard,
            _u32(0),
        ]
    )


def build_obj_info_stream() -> bytes:
    # Embedded object, displayed as an icon.
    return b"\x00\x00\x03\x00\x01\x00"


def read_streams(blob: bytes) -> dict[str, bytes]:
    """Read stream name → bytes from a compound file this module wrote."""
    if blob[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("not a compound file")

    def u32_at(offset: int) -> int:
        return struct.unpack_from("<I", blob, offset)[0]

    sector_shift = struct.unpack_from("<H", blob, 0x1E)[0]
    sector_size = 1 << sector_shift
    mini_shift = struct.unpack_from("<H", blob, 0x20)[0]
    mini_size = 1 << mini_shift
    fat_count = u32_at(0x2C)
    dir_start = u32_at(0x30)
    mini_cutoff = u32_at(0x38)
    mini_fat_start = u32_at(0x3C)
    mini_fat_count = u32_at(0x40)

    def sector_offset(index: int) -> int:
        return (index + 1) * sector_size

    fat: list[int] = []
    for i in range(fat_count):
        sec = u32_at(0x4C + i * 4)
        base = sector_offset(sec)
        for j in range(sector_size // 4):
            fat.append(u32_at(base + j * 4))

    def read_chain(start: int, size: int) -> bytes:
        if start == ENDOFCHAIN or size == 0:
            return b""
        out = bytearray()
        sec = start
        seen = set()
        while sec != ENDOFCHAIN and sec != FREESECT and len(out) < size + sector_size:
            if sec in seen or sec >= len(fat):
                break
            seen.add(sec)
            out.extend(blob[sector_offset(sec) : sector_offset(sec) + sector_size])
            sec = fat[sec]
        return bytes(out[:size])

    mini_fat: list[int] = []
    if mini_fat_start != ENDOFCHAIN and mini_fat_count:
        raw = read_chain(mini_fat_start, mini_fat_count * sector_size)
        for i in range(0, len(raw), 4):
            mini_fat.append(struct.unpack_from("<I", raw, i)[0])

    dir_data = read_chain(dir_start, sector_size * 8)
    entries = []
    for i in range(0, len(dir_data), DIR_ENTRY_SIZE):
        chunk = dir_data[i : i + DIR_ENTRY_SIZE]
        if len(chunk) < DIR_ENTRY_SIZE:
            break
        name_len = struct.unpack_from("<H", chunk, 64)[0]
        name = chunk[: max(name_len - 2, 0)].decode("utf-16le", "replace") if name_len >= 2 else ""
        obj_type = chunk[66]
        left, right, child = struct.unpack_from("<iii", chunk, 68)
        start = struct.unpack_from("<I", chunk, 116)[0]
        size = struct.unpack_from("<I", chunk, 120)[0]
        entries.append(
            {
                "name": name,
                "type": obj_type,
                "left": left,
                "right": right,
                "child": child,
                "start": start,
                "size": size,
            }
        )
        if obj_type == 0 and name == "":
            break

    root = entries[0]
    mini_stream = read_chain(root["start"], root["size"])

    def read_mini(start: int, size: int) -> bytes:
        out = bytearray()
        sec = start
        seen = set()
        while sec != ENDOFCHAIN and sec != FREESECT and len(out) < size + mini_size:
            if sec in seen or sec >= len(mini_fat):
                break
            seen.add(sec)
            begin = sec * mini_size
            out.extend(mini_stream[begin : begin + mini_size])
            sec = mini_fat[sec]
        return bytes(out[:size])

    streams: dict[str, bytes] = {}

    def walk(idx: int) -> None:
        if idx < 0 or idx >= len(entries):
            return
        entry = entries[idx]
        walk(entry["left"])
        if entry["type"] == STGTY_STREAM:
            if entry["size"] < mini_cutoff:
                streams[entry["name"]] = read_mini(entry["start"], entry["size"])
            else:
                streams[entry["name"]] = read_chain(entry["start"], entry["size"])
        walk(entry["right"])

    walk(root["child"])
    return streams


def build_ole_package_bin(
    filename: str, file_data: bytes, source_path: str | None = None
) -> bytes:
    # Do not add a \\x01Ole stream. WPS treats that stream as the activation
    # record; an empty moniker makes the object name and file type blank.
    writer = CompoundFileWriter()
    writer.add_stream("\x01CompObj", build_comp_obj_stream())
    writer.add_stream("\x03ObjInfo", build_obj_info_stream())
    writer.add_stream(
        "\x01Ole10Native",
        build_ole10_native(filename, file_data, source_path=source_path),
    )
    return writer.dumps()
