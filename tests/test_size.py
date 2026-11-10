import contextlib
import io
import json
from pathlib import Path
import re
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

from firmware_size_watch.cli import main
from firmware_size_watch.core import InputError, analyze, compare, parse_map
from firmware_size_watch.report import render


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "firmware_size_watch" / "fixtures"
BEFORE, AFTER = FIXTURES / "before.map", FIXTURES / "after.map"
SOURCE = BEFORE.read_text(encoding="utf-8")


class SizeTests(unittest.TestCase):
    def modified(self, source, **kwargs):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.map"
            path.write_text(source, encoding="utf-8")
            return analyze(path, **kwargs)

    def regions(self, report):
        return {r["name"]: r for r in report["regions"]}

    def test_flash_and_ram_known_counts(self):
        r = self.regions(analyze(BEFORE))
        self.assertEqual(r["FLASH"]["used"], 304)
        self.assertEqual(r["RAM"]["used"], 144)

    def test_input_subsections_not_counted_twice(self):
        text = SOURCE.replace(' .text.main     0x0000000008000000        0xc0 build/main.o',
                              ' .text.main     0x0000000008000000        0xc0 build/main.o\n .text.fake     0x0000000008000000        0xc0 build/fake.o')
        self.assertEqual(self.regions(self.modified(text))["FLASH"]["used"], 304)

    def test_data_occupies_both_flash_and_ram(self):
        r = self.regions(analyze(BEFORE))
        self.assertTrue(any(a["section"] == ".data" and a["kind"] == "load" for a in r["FLASH"]["allocations"]))
        self.assertTrue(any(a["section"] == ".data" and a["kind"] == "runtime" for a in r["RAM"]["allocations"]))

    def test_bss_does_not_consume_flash_lma(self):
        r = self.regions(analyze(BEFORE))
        self.assertFalse(any(a["section"] == ".bss" for a in r["FLASH"]["allocations"]))

    def test_debug_and_discarded_sections_ignored(self):
        self.assertTrue(analyze(BEFORE)["ok"])
        self.assertEqual(len(parse_map(BEFORE)[1]), 4)

    def test_long_section_name_wrap(self):
        r = self.modified(SOURCE.replace('.rodata         0x', '.long_rodata\n                0x', 1))
        self.assertEqual(self.regions(r)["FLASH"]["used"], 304)

    def test_unknown_format_rejected(self):
        with self.assertRaises(InputError):
            self.modified("IAR Linker map\n.text 0x0 0x20")

    def test_no_regions_rejected(self):
        with self.assertRaises(InputError):
            self.modified("Memory Configuration\nLinker script and memory map\n.text 0x0 0x20")

    def test_zero_only_output_is_valid_empty_usage(self):
        text = re.sub(r'(?m)^\.[^\n]+', '.empty          0x0000000008000000        0x0', SOURCE)
        self.assertEqual(sum(r["used"] for r in self.modified(text)["regions"]), 0)

    def test_budget_boundary_pass_and_fail(self):
        self.assertTrue(analyze(BEFORE, {"FLASH": 304})["ok"])
        self.assertFalse(analyze(BEFORE, {"FLASH": 303})["ok"])

    def test_unknown_budget_region_rejected(self):
        with self.assertRaises(InputError):
            analyze(BEFORE, {"TYPO": 1000})

    def test_negative_budget_rejected(self):
        with self.assertRaises(InputError):
            analyze(BEFORE, {"FLASH": -1})

    def test_growth_attribution_and_gate(self):
        result = compare(BEFORE, AFTER, max_growth=79)
        r = self.regions(result)
        self.assertEqual(r["FLASH"]["growth"], 80)
        self.assertEqual(r["RAM"]["growth"], 32)
        self.assertEqual(r["FLASH"]["contributions"][0]["section"], ".text")
        self.assertFalse(result["ok"])
        self.assertTrue(compare(BEFORE, AFTER, max_growth=80)["ok"])

    def test_region_overflow_fails_policy(self):
        text = SOURCE.replace('0x0000000000010000 xr', '0x0000000000000100 xr')
        r = self.modified(text)
        self.assertFalse(r["ok"])
        self.assertTrue(any(v["code"] == "section_outside_regions" for v in r["violations"]))

    def test_overlapping_regions_rejected(self):
        with self.assertRaises(InputError):
            self.modified(SOURCE.replace('0x0000000020000000 0x0000000000004000', '0x0000000008000100 0x0000000000004000'))

    def test_overlap_of_sections_is_counted_once(self):
        r = self.modified(SOURCE + '\n.overlay 0x08000000 0x100\n')
        self.assertEqual(self.regions(r)["FLASH"]["used"], 304)

    def test_custom_noload_policy(self):
        text = SOURCE.replace('.bss', '.retained')
        normal = self.regions(self.modified(text))["FLASH"]["used"]
        noload = self.regions(self.modified(text, noload=[".retained"]))["FLASH"]["used"]
        self.assertEqual(normal - noload, 128)

    def test_gaps_not_charged_as_allocated_bytes(self):
        text = SOURCE.replace('.rodata         0x0000000008000100', '.rodata         0x0000000008000200')
        r = self.regions(self.modified(text))["FLASH"]
        self.assertEqual(r["used"], 304)
        self.assertEqual(r["span"], 544)

    def test_html_escaping(self):
        report = analyze(BEFORE)
        report["file"] = "<script>bad</script>"
        report["regions"][0]["name"] = "<img src=x>"
        html = render(report, "html")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)

    def test_json_and_markdown(self):
        report = analyze(BEFORE)
        self.assertEqual(json.loads(render(report))["regions"][0]["name"], "FLASH")
        self.assertIn("| FLASH |", render(report, "markdown"))

    def test_cli_codes_and_bad_budget(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["check", str(BEFORE)]), 0)
            self.assertEqual(main(["check", str(BEFORE), "--budget", "FLASH=1"]), 1)
            self.assertEqual(main(["check", str(BEFORE), "--budget", "FLASH=bad"]), 2)
            self.assertEqual(main(["check", str(Path(temp) / "missing")]), 2)
            self.assertEqual(main(["check", str(BEFORE), "--output", str(BEFORE)]), 2)
            path = Path(temp) / "report.html"
            self.assertEqual(main(["demo", "--output", str(path)]), 0)
            self.assertIn("<!doctype html>", path.read_text(encoding="utf-8"))

    def test_foreign_cwd_demo(self):
        with tempfile.TemporaryDirectory() as temp:
            code = "import sys;sys.path.insert(0," + repr(str(ROOT)) + ");from firmware_size_watch.cli import main;raise SystemExit(main(['demo','--output','report.html']))"
            run = subprocess.run([sys.executable, "-c", code], cwd=temp, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue((Path(temp) / "report.html").is_file())

    @unittest.skipUnless(platform.system() != "Windows" and shutil.which("gcc") and shutil.which("ld") and shutil.which("readelf"), "GNU ELF toolchain not installed")
    def test_actual_gnu_linker_map_matches_elf_sections(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            subprocess.run(["gcc", "-c", "-ffreestanding", "-fno-pie", "-fno-asynchronous-unwind-tables",
                            str(ROOT / "examples" / "main.c"), "-o", str(temp / "main.o")], check=True, capture_output=True)
            subprocess.run(["ld", "-T", str(ROOT / "examples" / "layout.ld"), "-Map=" + str(temp / "app.map"),
                            "-o", str(temp / "app.elf"), str(temp / "main.o")], check=True, capture_output=True)
            result = analyze(temp / "app.map")
            self.assertTrue(result["ok"], result["violations"])
            sections = subprocess.check_output(["readelf", "-SW", str(temp / "app.elf")], text=True)
            sizes = {}
            for name in (".text", ".rodata", ".data", ".bss"):
                match = re.search(re.escape(name) + r"\s+\S+\s+[0-9a-fA-F]+\s+[0-9a-fA-F]+\s+([0-9a-fA-F]+)", sections)
                self.assertIsNotNone(match, sections)
                sizes[name] = int(match[1], 16)
            regions = self.regions(result)
            self.assertEqual(regions["FLASH"]["used"], sizes[".text"] + sizes[".rodata"] + sizes[".data"])
            self.assertEqual(regions["RAM"]["used"], sizes[".data"] + sizes[".bss"])


if __name__ == "__main__":
    unittest.main()
