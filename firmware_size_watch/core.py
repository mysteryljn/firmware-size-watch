"""Read a documented GNU ld map subset and account address intervals once."""
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
import re


class InputError(ValueError):
    pass


@dataclass(frozen=True)
class Region:
    name: str
    origin: int
    length: int


@dataclass(frozen=True)
class Section:
    name: str
    address: int
    size: int
    load_address: int
    line: int


NUMBER = r"0x[0-9a-fA-F]+"
REGION = re.compile(r"^(\S+)\s+(" + NUMBER + r")\s+(" + NUMBER + r")(?:\s+\S+)?\s*$")
SECTION = re.compile(r"^([^\s]+)\s+(" + NUMBER + r")\s+(" + NUMBER + r")(.*)$")
CONTINUED = re.compile(r"^\s+(" + NUMBER + r")\s+(" + NUMBER + r")(.*)$")
LOAD = re.compile(r"\bload address\s+(" + NUMBER + r")")
DEFAULT_NOLOAD = (".bss", ".bss.*", ".sbss", ".sbss.*", ".noinit", ".noinit.*", ".stack", ".heap")
NONALLOC = (".debug*", ".zdebug*", ".comment", ".note.GNU-stack", ".gnu.attributes", ".ARM.attributes",
            ".symtab", ".strtab", ".shstrtab", ".stab*")


def parse_map(path):
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise InputError(f"Cannot read map {path}: {exc}") from exc
    if "Memory Configuration" not in text or "Linker script and memory map" not in text:
        raise InputError("Expected GNU ld 'Memory Configuration' and 'Linker script and memory map' headers")
    memory = text.split("Memory Configuration", 1)[1].split("Linker script and memory map", 1)[0]
    regions = []
    for line in memory.splitlines():
        match = REGION.match(line.strip())
        if match and match[1] != "*default*":
            region = Region(match[1], int(match[2], 16), int(match[3], 16))
            if region.length <= 0:
                raise InputError(f"Region {region.name} has no capacity")
            if any(r.name == region.name for r in regions):
                raise InputError(f"Duplicate region {region.name}")
            regions.append(region)
    if not regions:
        raise InputError("Map has no explicit memory regions; provide a linker script with MEMORY")
    ordered = sorted(regions, key=lambda r: r.origin)
    for left, right in zip(ordered, ordered[1:]):
        if left.origin + left.length > right.origin:
            raise InputError("Overlapping/aliased MEMORY regions are unsupported; use disjoint regions")

    sections, pending = [], None
    active = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.strip() == "Linker script and memory map":
            active = True
            continue
        if not active:
            continue
        match = SECTION.match(line)
        if match:
            name, address, size, tail = match.groups()
            pending = None
        elif pending and CONTINUED.match(line):
            match = CONTINUED.match(line)
            address, size, tail = match.groups()
            name, source_line = pending
            pending = None
            lineno = source_line
        else:
            # Output sections begin in column zero; input subsections and symbols
            # are indented. Long output section names can wrap before VMA/size.
            pending = (line.strip(), lineno) if re.fullmatch(r"[.A-Za-z_$][\w.$-]*", line) else None
            continue
        if name in {"LOAD", "OUTPUT", "/DISCARD/"} or any(fnmatchcase(name, pattern) for pattern in NONALLOC):
            continue
        load = LOAD.search(tail)
        sections.append(Section(name, int(address, 16), int(size, 16),
                                int(load[1], 16) if load else int(address, 16), lineno))
    if not sections:
        raise InputError("No supported output sections found in GNU ld map")
    return regions, sections


def _union_length(intervals):
    total, end = 0, None
    for start, stop in sorted(intervals):
        if end is None or start > end:
            total += stop - start
            end = stop
        elif stop > end:
            total += stop - end
            end = stop
    return total


def analyze(path, budgets=None, noload=()):
    regions, sections = parse_map(path)
    budgets = budgets or {}
    unknown = set(budgets) - {r.name for r in regions}
    if unknown:
        raise InputError("Unknown budget region(s): " + ", ".join(sorted(unknown)))
    for key, value in budgets.items():
        if type(value) is not int or value < 0:
            raise InputError(f"Budget for {key} must be a non-negative integer byte count")
    allocations = {r.name: [] for r in regions}
    violations, ignored_load_sections = [], []
    noload_patterns = DEFAULT_NOLOAD + tuple(noload)
    for section in sections:
        if not section.size:
            continue
        no_load = any(fnmatchcase(section.name, pattern) for pattern in noload_patterns)
        if no_load and section.load_address != section.address:
            ignored_load_sections.append(section.name)
        placements = [("runtime", section.address)]
        if section.load_address != section.address and not no_load:
            placements.append(("load", section.load_address))
        for kind, address in placements:
            region = next((r for r in regions if r.origin <= address and address + section.size <= r.origin + r.length), None)
            if region is None:
                violations.append({"code": "section_outside_regions", "section": section.name,
                                   "kind": kind, "address": address, "size": section.size, "line": section.line})
            else:
                allocations[region.name].append({"section": section.name, "kind": kind,
                                                 "address": address, "size": section.size, "line": section.line})
    output = []
    for region in regions:
        entries = allocations[region.name]
        used = _union_length([(e["address"], e["address"] + e["size"]) for e in entries])
        # Span includes holes from the origin and is informative, not a byte sum.
        span = max((e["address"] + e["size"] - region.origin for e in entries), default=0)
        budget = min(budgets.get(region.name, region.length), region.length)
        if used > budget:
            violations.append({"code": "budget_exceeded", "region": region.name, "used": used, "budget": budget})
        output.append({"name": region.name, "origin": region.origin, "capacity": region.length,
                       "used": used, "free": region.length - used, "span": span, "budget": budget,
                       "allocations": sorted(entries, key=lambda e: (-e["size"], e["section"], e["kind"]))})
    return {"schema_version": 1, "file": str(path), "ok": not violations, "regions": output,
            "violations": violations, "noload_patterns": list(noload_patterns),
            "suppressed_noload_lmas": ignored_load_sections,
            "limitations": ["GNU ld maps only; no ELF allocation/type flags are available.",
                            "Custom NOLOAD sections require --noload-section; conventional bss/noinit names are recognized.",
                            "Overlapping address intervals are counted once; input subsections are not counted again."]}


def compare(before, after, budgets=None, noload=(), max_growth=None):
    old, report = analyze(before, noload=noload), analyze(after, budgets=budgets, noload=noload)
    if old["violations"]:
        raise InputError("Baseline map contains sections outside its memory regions; cannot compare reliably")
    prior = {r["name"]: r for r in old["regions"]}
    report["baseline_file"] = str(before)
    report["removed_regions"] = sorted(set(prior) - {r["name"] for r in report["regions"]})
    if max_growth is not None and (type(max_growth) is not int or max_growth < 0):
        raise InputError("Maximum growth must be a non-negative integer byte count")
    for region in report["regions"]:
        previous = prior.get(region["name"], {"used": 0, "allocations": []})
        region["previous_used"] = previous["used"]
        region["growth"] = region["used"] - previous["used"]
        def sizes(entries):
            result = {}
            for entry in entries:
                key = (entry["section"], entry["kind"])
                result[key] = result.get(key, 0) + entry["size"]
            return result
        left, right = sizes(previous["allocations"]), sizes(region["allocations"])
        region["contributions"] = sorted(
            [{"section": key[0], "kind": key[1], "before": left.get(key, 0), "after": right.get(key, 0),
              "growth": right.get(key, 0) - left.get(key, 0)} for key in left.keys() | right.keys()
             if left.get(key, 0) != right.get(key, 0)], key=lambda x: (-x["growth"], x["section"], x["kind"]))
        if max_growth is not None and region["growth"] > max_growth:
            report["violations"].append({"code": "growth_exceeded", "region": region["name"],
                                         "growth": region["growth"], "max_growth": max_growth})
    report["ok"] = not report["violations"]
    return report
