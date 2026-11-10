import argparse
from importlib.resources import files
from pathlib import Path
import sys

from .core import InputError, analyze, compare
from .report import render


def byte_count(value):
    try:
        number = int(value, 0) if value.lower().startswith("0x") else int(value)
        if number < 0:
            raise ValueError
        return number
    except ValueError:
        raise argparse.ArgumentTypeError("Expected a non-negative byte count (decimal or 0x hexadecimal)")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check GNU ld map region budgets and firmware growth.")
    parser.add_argument("--version", action="version", version="firmware-size-watch 0.1.0")
    subs = parser.add_subparsers(dest="command", required=True)
    check = subs.add_parser("check")
    check.add_argument("map", type=Path)
    comparison = subs.add_parser("compare")
    comparison.add_argument("before", type=Path)
    comparison.add_argument("after", type=Path)
    comparison.add_argument("--max-growth", type=byte_count, help="Fail if any region grows by more than this many bytes")
    demo = subs.add_parser("demo", help="Generate an offline report using packaged synthetic GNU ld maps")
    for command in (check, comparison, demo):
        command.add_argument("--budget", action="append", default=[], metavar="REGION=BYTES")
        command.add_argument("--noload-section", action="append", default=[], metavar="GLOB",
                             help="Additional custom NOLOAD section names/globs whose LMA must not count")
        command.add_argument("--format", choices=("json", "markdown", "html"))
        command.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        budgets = {}
        for spec in args.budget:
            name, separator, count = spec.partition("=")
            if not separator or not name or name in budgets:
                raise InputError("Each --budget must uniquely name REGION=BYTES")
            try:
                budgets[name] = byte_count(count)
            except argparse.ArgumentTypeError as exc:
                raise InputError(str(exc)) from exc
        inputs = []
        if args.command == "check":
            inputs = [args.map]
            report = analyze(args.map, budgets, args.noload_section)
        elif args.command == "compare":
            inputs = [args.before, args.after]
            report = compare(args.before, args.after, budgets, args.noload_section, args.max_growth)
        else:
            fixture = files("firmware_size_watch").joinpath("fixtures")
            report = compare(fixture.joinpath("before.map"), fixture.joinpath("after.map"), budgets, args.noload_section)
        format = args.format or ("html" if args.output and args.output.suffix.lower() == ".html" else "json")
        output = render(report, format)
        if args.output:
            if args.output.resolve() in [p.resolve() for p in inputs]:
                raise InputError("Output must not overwrite an input map")
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
        return 0 if args.command == "demo" or report["ok"] else 1
    except (InputError, OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
