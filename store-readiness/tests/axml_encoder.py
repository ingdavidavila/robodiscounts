"""Tiny Android binary-XML encoder used only by tests (UTF-8 or UTF-16 string pools, typed attributes)."""
import struct

ANDROID = "http://schemas.android.com/apk/res/android"
RES_IDS = {"name": 0x01010003, "debuggable": 0x0101000F, "exported": 0x01010010,
           "targetSdkVersion": 0x01010270, "foregroundServiceType": 0x01010599,
           "usesCleartextTraffic": 0x010104EC}


def _pool(strings, utf8):
    blobs = []
    for s in strings:
        if utf8:
            raw = s.encode("utf-8")
            blobs.append(bytes([len(s) & 0x7F, len(raw) & 0x7F]) + raw + b"\0")
        else:
            blobs.append(struct.pack("<H", len(s)) + s.encode("utf-16-le") + b"\0\0")
    offsets, body, pos = [], b"", 0
    for bl in blobs:
        offsets.append(pos)
        body += bl
        pos += len(bl)
    body += b"\0" * (-len(body) % 4)
    hdr = 28 + 4 * len(strings)
    chunk = struct.pack("<HHIIIIII", 1, 28, hdr + len(body), len(strings), 0, 0x100 if utf8 else 0, hdr, 0)
    return chunk + b"".join(struct.pack("<I", o) for o in offsets) + body


def encode(root, utf8=True):
    """root = (tag, [(name, 'str'|'int'|'bool', value)], [children]); attribute names are android: attrs."""
    res_names = list(RES_IDS)
    strings = list(res_names) + ["android", ANDROID]
    idx = {s: i for i, s in enumerate(strings)}

    def sid(s):
        if s not in idx:
            idx[s] = len(strings)
            strings.append(s)
        return idx[s]

    def walk_collect(node):
        sid(node[0])
        for n, t, v in node[1]:
            if t == "str":
                sid(v)
        for c in node[2]:
            walk_collect(c)
    walk_collect(root)
    body = b""
    body += struct.pack("<HHIII", 0x0100, 16, 24, 1, 0xFFFFFFFF) + struct.pack("<II", idx["android"], idx[ANDROID])

    def emit(node):
        out = b""
        tag, attrs, children = node
        a = b""
        for n, t, v in attrs:
            if t == "str":
                a += struct.pack("<IIIHBBI", idx[ANDROID], idx[n], idx[v], 8, 0, 0x03, idx[v])
            elif t == "int":
                a += struct.pack("<IIIHBBI", idx[ANDROID], idx[n], 0xFFFFFFFF, 8, 0, 0x10, v)
            else:
                a += struct.pack("<IIIHBBI", idx[ANDROID], idx[n], 0xFFFFFFFF, 8, 0, 0x12, 0xFFFFFFFF if v else 0)
        out += struct.pack("<HHIII", 0x0102, 16, 36 + len(a), 1, 0xFFFFFFFF)
        out += struct.pack("<IIHHHHHH", 0xFFFFFFFF, idx[tag], 20, 20, len(attrs), 0, 0, 0) + a
        for c in children:
            out += emit(c)
        out += struct.pack("<HHIII", 0x0103, 16, 24, 1, 0xFFFFFFFF) + struct.pack("<II", 0xFFFFFFFF, idx[tag])
        return out
    body += emit(root)
    body += struct.pack("<HHIII", 0x0101, 16, 24, 1, 0xFFFFFFFF) + struct.pack("<II", idx["android"], idx[ANDROID])
    rmap = struct.pack("<HHI", 0x0180, 8, 8 + 4 * len(res_names)) + b"".join(struct.pack("<I", RES_IDS[n]) for n in res_names)
    pool = _pool(strings, utf8)
    total = 8 + len(pool) + len(rmap) + len(body)
    return struct.pack("<HHI", 0x0003, 8, total) + pool + rmap + body


SAMPLE = ("manifest", [], [
    ("uses-sdk", [("targetSdkVersion", "int", 33)], []),
    ("application", [("debuggable", "bool", True), ("usesCleartextTraffic", "bool", False)], [
        ("activity", [("name", "str", ".Main"), ("exported", "bool", True)], []),
        ("service", [("name", "str", ".Svc")], [
            ("intent-filter", [], [("action", [("name", "str", "com.x.START")], [])])]),
        ("service", [("name", "str", "ünï.Fgs"), ("exported", "bool", False),
                     ("foregroundServiceType", "str", "location")], []),
    ]),
])
