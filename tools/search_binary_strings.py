"""Search printable ASCII and UTF-16LE strings in a binary research artifact."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ASCII = re.compile(rb"[\x20-\x7e]{4,}")
UTF16 = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")
UTF8 = re.compile(rb"[\x20-\x7e\x80-\xff]{4,512}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("patterns", nargs="+")
    parser.add_argument("--context", type=int, default=0)
    parser.add_argument("--near-bytes", type=int, default=0)
    args = parser.parse_args()
    data = args.binary.read_bytes()
    matcher = re.compile("|".join(f"(?:{item})" for item in args.patterns), flags=re.IGNORECASE)
    strings: list[tuple[int, int, str, str]] = []
    for kind, expression, encoding in (("ascii", ASCII, "ascii"), ("utf16", UTF16, "utf-16le")):
        for match in expression.finditer(data):
            strings.append((match.start(), match.end(), kind, match.group().decode(encoding, errors="replace")))
    for match in UTF8.finditer(data):
        if all(value < 0x80 for value in match.group()):
            continue
        try:
            value = match.group().decode("utf-8")
        except UnicodeDecodeError:
            continue
        strings.append((match.start(), match.end(), "utf8", value))
    strings.sort()
    if args.near_bytes:
        anchors = [item for item in strings if matcher.search(item[3])]
        emitted: set[tuple[int, str, str]] = set()
        for anchor in anchors:
            print(f"=== anchor 0x{anchor[0]:x} [{anchor[2]}] {anchor[3]} ===")
            for start, _end, kind, value in strings:
                if abs(start - anchor[0]) <= args.near_bytes and (start, kind, value) not in emitted:
                    emitted.add((start, kind, value))
                    print(f"0x{start:x} [{kind}] {value}")
        return
    found: set[tuple[str, str]] = set()
    for start, end, kind, value in strings:
        if matcher.search(value):
            if args.context:
                context_start = max(0, start - args.context)
                context_end = min(len(data), end + args.context)
                encoding = "utf-16le" if kind == "utf16" else ("utf-8" if kind == "utf8" else "ascii")
                context = data[context_start:context_end].decode(encoding, errors="replace")
                value = f"{value} || {context}"
            found.add((kind, value))
    for kind, value in sorted(found):
        print(f"[{kind}] {value}")


if __name__ == "__main__":
    main()
