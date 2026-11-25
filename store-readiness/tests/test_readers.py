"""The ELF and image readers, checked against independent references on real or independently produced data."""
import json
import unittest
from pathlib import Path

from storecheck.checks import elf_alignment
from storecheck.media import image_size

D = Path(__file__).parent / "data"


class P:                       # the only attribute elf_alignment reads
    def __init__(self, libs):
        self.native_libs = libs


class ElfReader(unittest.TestCase):
    def test_matches_readelf_on_real_libraries(self):
        exp = json.loads((D / "elf" / "expected.json").read_text(encoding="utf-8"))["libs"]
        self.assertGreaterEqual(len(exp), 5)
        for name, e in exp.items():
            head = (D / "elf" / f"{name}.head").read_bytes()
            flagged = bool(elf_alignment(P([(name, head)]), {}))
            applies = e["machine"] in ("AArch64", "Advanced Micro Devices X86-64")
            expected = applies and any(a < 0x4000 for a in e["load_aligns"])
            self.assertEqual(flagged, expected, f"{name}: {e}")

    def test_32_bit_and_truncated_input_never_crash_or_flag(self):
        self.assertEqual(elf_alignment(P([("a", b"")]), {}), [])
        self.assertEqual(elf_alignment(P([("b", b"\x7fELF\x01\x01\x01" + bytes(60))]), {}), [])
        self.assertEqual(elf_alignment(P([("c", b"not an elf")]), {}), [])


class ImageReader(unittest.TestCase):
    def test_matches_pillow_on_png_and_jpeg_variants(self):
        sizes = json.loads((D / "images" / "expected.json").read_text(encoding="utf-8"))["sizes"]
        self.assertGreaterEqual(len(sizes), 20)
        for name, size in sizes.items():
            self.assertEqual(list(image_size(D / "images" / name)), size, name)

    def test_unreadable_files_return_none(self):
        self.assertIsNone(image_size(D / "images" / "expected.json"))
        self.assertIsNone(image_size(D / "images" / "does-not-exist.png"))


if __name__ == "__main__":
    unittest.main()
