"""Decode Android binary XML (the AndroidManifest.xml inside an APK) into an ElementTree element.

Format: Android's AXML (ResXMLTree): a string pool, an optional resource-id map, then
start/end namespace and element chunks. Attribute names normally live in the string pool;
when they don't, the resource-id map names them (a few well-known ids are built in below).

Only APKs are supported. An AAB stores its manifest as protobuf (aapt2), which this module does
not read.
"""
from __future__ import annotations

import struct
import xml.etree.ElementTree as ET

ANDROID_NS = "http://schemas.android.com/apk/res/android"

RES_XML = 0x0003
RES_STRING_POOL = 0x0001
RES_XML_RESOURCE_MAP = 0x0180
RES_XML_START_NAMESPACE = 0x0100
RES_XML_END_NAMESPACE = 0x0101
RES_XML_START_ELEMENT = 0x0102
RES_XML_END_ELEMENT = 0x0103

TYPE_REFERENCE, TYPE_FLOAT, TYPE_STRING = 0x01, 0x04, 0x03
TYPE_INT_DEC, TYPE_INT_HEX, TYPE_INT_BOOLEAN = 0x10, 0x11, 0x12

# attribute resource ids -> names, used only when the string pool has no name for an attribute
KNOWN_ATTR_IDS = {
    0x01010003: "name", 0x0101000F: "debuggable", 0x01010010: "exported", 0x0101020C: "minSdkVersion",
    0x01010270: "targetSdkVersion", 0x010104EC: "usesCleartextTraffic", 0x01010599: "foregroundServiceType",
    0x0101021B: "versionCode", 0x0101021C: "versionName", 0x01010001: "label", 0x01010002: "icon",
}


class AxmlError(ValueError):
    pass


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _string_pool(b: bytes, off: int) -> tuple[list[str], int]:
    size = _u32(b, off + 4)
    count, _styles, flags, str_start = struct.unpack_from("<IIII", b, off + 8)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from(f"<{count}I", b, off + 28)
    base = off + str_start
    out = []
    for o in offsets:
        p = base + o
        if utf8:
            n = b[p]
            p += 1
            if n & 0x80:
                n = ((n & 0x7F) << 8) | b[p]
                p += 1
            n2 = b[p]
            p += 1
            if n2 & 0x80:
                n2 = ((n2 & 0x7F) << 8) | b[p]
                p += 1
            out.append(b[p:p + n2].decode("utf-8", errors="replace"))
        else:
            n = _u16(b, p)
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | _u16(b, p)
                p += 2
            out.append(b[p:p + n * 2].decode("utf-16-le", errors="replace"))
    return out, size


def _value(strings: list[str], raw: int, dtype: int, data: int) -> str:
    if dtype == TYPE_STRING:
        idx = raw if raw != 0xFFFFFFFF else data
        return strings[idx] if idx < len(strings) else ""
    if dtype == TYPE_INT_BOOLEAN:
        return "true" if data != 0 else "false"
    if dtype == TYPE_INT_DEC:
        return str(struct.unpack("<i", struct.pack("<I", data))[0])
    if dtype == TYPE_INT_HEX:
        return f"0x{data:x}"
    if dtype == TYPE_REFERENCE:
        return f"@0x{data:08x}"
    return str(data)


def decode_axml(b: bytes) -> ET.Element:
    if len(b) < 8 or _u16(b, 0) != RES_XML:
        raise AxmlError("not an Android binary XML file")
    strings: list[str] = []
    res_ids: list[int] = []
    ns_uri: dict[int, str] = {}
    stack: list[ET.Element] = []
    root: ET.Element | None = None
    off = _u16(b, 2)
    total = min(_u32(b, 4), len(b))
    while off + 8 <= total:
        ctype, hsize, csize = _u16(b, off), _u16(b, off + 2), _u32(b, off + 4)
        if csize < 8:
            raise AxmlError("corrupt chunk size")
        if ctype == RES_STRING_POOL:
            strings, _ = _string_pool(b, off)
        elif ctype == RES_XML_RESOURCE_MAP:
            res_ids = list(struct.unpack_from(f"<{(csize - hsize) // 4}I", b, off + hsize))
        elif ctype == RES_XML_START_NAMESPACE:
            prefix, uri = struct.unpack_from("<II", b, off + 16)
            ns_uri[prefix] = uri
            ns_uri[("uri", uri)] = strings[uri] if uri < len(strings) else ""
        elif ctype == RES_XML_START_ELEMENT:
            ns, name, a_start, a_size, a_count = struct.unpack_from("<IIHHH", b, off + 16)
            el = ET.Element(strings[name] if name < len(strings) else "?")
            base = off + 16 + a_start
            for i in range(a_count):
                ao = base + i * (a_size or 20)
                ans, aname, raw, _sz, _r0, dtype, data = struct.unpack_from("<IIIHBBI", b, ao)
                an = strings[aname] if aname < len(strings) else ""
                if not an and aname < len(res_ids):
                    an = KNOWN_ATTR_IDS.get(res_ids[aname], "")
                if not an:
                    continue
                uri = strings[ans] if ans != 0xFFFFFFFF and ans < len(strings) else ""
                key = f"{{{uri}}}{an}" if uri else an
                el.set(key, _value(strings, raw, dtype, data))
            if stack:
                stack[-1].append(el)
            else:
                root = el
            stack.append(el)
        elif ctype == RES_XML_END_ELEMENT:
            if stack:
                stack.pop()
        off += csize
    if root is None:
        raise AxmlError("no root element")
    return root
