"""Decode the protobuf XML (aapt2 `aapt.pb.XmlNode`) used for manifests inside an Android App Bundle (AAB).

Schema: AOSP frameworks/base/tools/aapt2/Resources.proto (XmlNode, XmlElement, XmlAttribute). Only the fields needed to
read a manifest are decoded: element name and namespace, attribute namespace, name and the original `value` text.
No protobuf library is needed; this reads the wire format directly and skips unknown fields.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET


class PbxmlError(ValueError):
    pass


def _varint(b: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        if i >= len(b):
            raise PbxmlError("truncated varint")
        c = b[i]
        i += 1
        result |= (c & 0x7F) << shift
        if not c & 0x80:
            return result, i
        shift += 7
        if shift > 63:
            raise PbxmlError("varint too long")


def _fields(b: bytes):
    """Yield (field number, wire type, value) where value is int for varint/fixed and bytes for length-delimited."""
    i = 0
    while i < len(b):
        tag, i = _varint(b, i)
        num, wt = tag >> 3, tag & 7
        if wt == 0:
            v, i = _varint(b, i)
        elif wt == 2:
            n, i = _varint(b, i)
            if i + n > len(b):
                raise PbxmlError("truncated field")
            v, i = b[i:i + n], i + n
        elif wt == 1:
            v, i = int.from_bytes(b[i:i + 8], "little"), i + 8
        elif wt == 5:
            v, i = int.from_bytes(b[i:i + 4], "little"), i + 4
        else:
            raise PbxmlError(f"unsupported wire type {wt}")
        yield num, wt, v


def _element(b: bytes, depth: int = 0) -> ET.Element:
    if depth > 200:
        raise PbxmlError("nesting too deep")
    name = ""
    attrs: list[tuple[str, str, str]] = []
    children: list[bytes] = []
    for num, wt, v in _fields(b):
        if wt != 2:
            continue
        if num == 3:
            name = v.decode("utf-8", "replace")
        elif num == 4:
            ns = an = val = ""
            for n2, w2, v2 in _fields(v):
                if w2 == 2 and n2 == 1:
                    ns = v2.decode("utf-8", "replace")
                elif w2 == 2 and n2 == 2:
                    an = v2.decode("utf-8", "replace")
                elif w2 == 2 and n2 == 3:
                    val = v2.decode("utf-8", "replace")
            attrs.append((ns, an, val))
        elif num == 5:
            children.append(v)
    el = ET.Element(name)
    for ns, an, val in attrs:
        if an:
            el.set(f"{{{ns}}}{an}" if ns else an, val)
    for c in children:
        for num, wt, v in _fields(c):
            if num == 1 and wt == 2:        # XmlNode.element; text nodes (field 2) are ignored
                el.append(_element(v, depth + 1))
    return el


def decode_proto_manifest(b: bytes) -> ET.Element:
    for num, wt, v in _fields(b):
        if num == 1 and wt == 2:
            return _element(v)
    raise PbxmlError("no root element")
