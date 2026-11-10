# firmware-size-watch

**Turn a GNU ld map into a ROM/RAM budget check and explain which output sections grew.**

[中文说明](README.zh-CN.md) · Python 3.10+ · MIT · Standard library only · No target hardware required

Initialized `.data` occupies RAM at runtime **and** flash in the load image. `.bss` occupies runtime memory without corresponding initialized bytes in flash. This tool accounts for both addresses, avoids counting indented input subsections twice, and makes memory budgets reviewable in CI.

## Quick start

```sh
git clone https://github.com/mysteryljn/firmware-size-watch.git
cd firmware-size-watch
python -m pip install .
python -m firmware_size_watch demo --output report.html
```

Open `report.html`. It contains the region summary and largest section changes, with no external assets or scripts. Packaged synthetic maps make the demo work from any directory after installation.

The demo grows FLASH **304 → 384 bytes (+80)** and RAM **144 → 176 bytes (+32)**. These are deliberately small, hand-written GNU ld syntax examples, not vendor firmware or a claimed capture from a real toolchain.

## Use your build output

Generate a GNU ld map through your existing GCC link step with `-Wl,-Map=firmware.map`, using a linker script that defines explicit `MEMORY` regions.

```sh
firmware-size-watch check firmware.map --budget FLASH=60000 --budget RAM=12000 --output memory.html
firmware-size-watch compare previous.map current.map --max-growth 1024 --format json --output growth.json
firmware-size-watch compare previous.map current.map --budget RAM=0x3000 --format markdown
firmware-size-watch check firmware.map --noload-section '.retained*'
```

`python -m firmware_size_watch` is equivalent to the installed command.

| Exit code | Meaning |
|---|---|
| 0 | All region/growth policies passed; or demo report generated successfully |
| 1 | Budget/growth limit exceeded, or a section placement is outside known memory regions |
| 2 | Unsupported/invalid map, invalid policy, missing input or failed output |

`--budget REGION=BYTES` sets an absolute per-region byte limit; hardware capacity remains the maximum. `--max-growth BYTES` fails if any region grows by more than that absolute amount. No percentage arithmetic or default hidden reserve is applied. Unknown region names fail, so a typo cannot silently disable a check. Outputs cannot overwrite inputs.

## Accounting model

- Only **unindented output section records** are counted. Indented object-file subsections, symbols, fill lines and discarded input records do not add the same bytes again. Output-section size already contains its internal alignment/fill.
- Each nonempty section contributes its VMA range to runtime memory. A distinct LMA contributes an additional range to load memory unless the section is classified NOLOAD.
- Address intervals in each region are unioned. Overlapping output sections are counted once in `used`; top contributor rows show their individual section sizes and therefore need not sum to the union in overlay cases.
- `span` is the distance from region origin to the highest occupied address, including holes. `used` is the allocated interval union and is the quantity checked against the budget. Neither implies a single contiguous block of free space.
- Conventional `.bss`, `.bss.*`, `.sbss`, `.sbss.*`, `.noinit`, `.noinit.*`, `.stack` and `.heap` names are treated as NOLOAD. Use `--noload-section GLOB` for custom NOLOAD sections. This is an explicit naming policy: a map alone lacks ELF section-type/allocation flags.
- Known debug/comment/attribute/symbol-table sections are excluded. A remaining nonempty placement outside every region is reported as a policy failure, not silently discarded.

## Supported scope

Version 0.1.0 supports the common **GNU ld** map structure containing `Memory Configuration`, `Linker script and memory map`, hexadecimal VMA/size fields, optional `load address`, and wrapped output section names. MEMORY regions must be explicitly named and disjoint.

This is not a universal map parser. IAR, Keil, TASKING, proprietary map dialects, overlapping/aliased MEMORY regions and the full GNU overlay semantics are outside scope. Arbitrary custom sections cannot be classified as file-backed or NOLOAD from map text alone; declare their policy. The report is a review aid, not proof that a bootloader's exact programmed image or linker layout is correct. Use ELF/program headers and your flashing tool for exact load-image validation.

Region matching between versions uses names; renaming a region appears as a new region plus a listed removed region. Contributions are output-section deltas, not object-file or source-line blame.

[Bloaty](https://github.com/google/bloaty) already provides binary size profiles and diffs. This project focuses on named MCU memory regions, explicit allocation/load placement policies, CI limits and a shareable report; it does not claim size diff itself is novel.

## Verify with a real GNU toolchain

The repository contains freestanding synthetic C and a linker script:

```sh
gcc -c -ffreestanding -fno-pie -fno-asynchronous-unwind-tables examples/main.c -o main.o
ld -T examples/layout.ld -Map=firmware.map -o firmware.elf main.o
readelf -SW firmware.elf
python -m firmware_size_watch check firmware.map --output real-map.html
```

This runs entirely on a development machine and does not execute the linked firmware. The test suite performs the same real compile/link and compares section sizes to `readelf` when GNU `gcc`, `ld` and `readelf` are present. Otherwise that test is explicitly **skipped**, not reported as validated. GitHub's Linux CI provides these tools; local Windows environments may not.

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

Other tests cover independent expected totals, VMA/LMA, NOLOAD, wrapped names, padding/gaps, malformed formats, overlapping regions, budgets, growth attribution, escaping, output safety, CLI codes and running the demo outside the checkout.

When reporting a parser issue, include a small redistributable map excerpt with its toolchain/version, MEMORY table and affected output/input section records. See [CONTRIBUTING.md](CONTRIBUTING.md).
