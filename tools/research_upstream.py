"""Inspect the upstream Windows executable without executing it.

This research helper is not part of the installed skill. It records PE metadata
and can unpack the observed ``KAY`` + Zstandard RCDATA container for
interoperability analysis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import pefile
import zstandard


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resource_rows(pe: pefile.PE) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        return rows
    image = pe.get_memory_mapped_image()
    for type_entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if not hasattr(type_entry, "directory"):
            continue
        resource_type = str(type_entry.name or type_entry.struct.Id)
        for name_entry in type_entry.directory.entries:
            if not hasattr(name_entry, "directory"):
                continue
            resource_name = str(name_entry.name or name_entry.struct.Id)
            for language_entry in name_entry.directory.entries:
                data = language_entry.data.struct
                payload = image[data.OffsetToData : data.OffsetToData + data.Size]
                rows.append(
                    {
                        "type": resource_type,
                        "name": resource_name,
                        "language": int(language_entry.struct.Id),
                        "offset": int(data.OffsetToData),
                        "size": int(data.Size),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "prefix_hex": payload[:16].hex(),
                    }
                )
    return sorted(rows, key=lambda row: int(row["size"]), reverse=True)


def inspect(executable: Path) -> tuple[dict[str, object], bytes]:
    pe = pefile.PE(str(executable), fast_load=False)
    resources = resource_rows(pe)
    imports: list[str] = []
    if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
        imports = sorted(entry.dll.decode("ascii", errors="replace") for entry in pe.DIRECTORY_ENTRY_IMPORT)
    sections = [
        {
            "name": section.Name.rstrip(b"\0").decode("ascii", errors="replace"),
            "virtual_size": int(section.Misc_VirtualSize),
            "raw_size": int(section.SizeOfRawData),
            "entropy": round(float(section.get_entropy()), 3),
        }
        for section in pe.sections
    ]
    largest = resources[0] if resources else None
    payload = b""
    if largest:
        image = pe.get_memory_mapped_image()
        start = int(largest["offset"])
        payload = image[start : start + int(largest["size"])]
    report = {
        "path": str(executable.resolve()),
        "size": executable.stat().st_size,
        "sha256": sha256(executable),
        "machine": hex(pe.FILE_HEADER.Machine),
        "timestamp": int(pe.FILE_HEADER.TimeDateStamp),
        "entry_point": hex(pe.OPTIONAL_HEADER.AddressOfEntryPoint),
        "image_base": hex(pe.OPTIONAL_HEADER.ImageBase),
        "subsystem": int(pe.OPTIONAL_HEADER.Subsystem),
        "sections": sections,
        "imports": imports,
        "resources": resources,
    }
    return report, payload


def unpack(payload: bytes, output: Path) -> dict[str, object]:
    if not payload.startswith(b"KAY\x28\xb5\x2f\xfd"):
        raise RuntimeError("largest resource does not use the observed KAY + Zstandard container")
    compressed = payload[3:]
    output.parent.mkdir(parents=True, exist_ok=True)
    decompressor = zstandard.ZstdDecompressor().decompressobj()
    with output.open("wb") as target:
        for start in range(0, len(compressed), 1024 * 1024):
            target.write(decompressor.decompress(compressed[start : start + 1024 * 1024]))
            if decompressor.eof:
                break
    prefix = output.read_bytes()[:64]
    return {
        "output": str(output.resolve()),
        "size": output.stat().st_size,
        "sha256": sha256(output),
        "prefix_hex": prefix.hex(),
        "prefix_ascii": "".join(chr(value) if 32 <= value < 127 else "." for value in prefix),
    }


def extract_archive(archive: Path, output_dir: Path) -> dict[str, object]:
    """Extract the simple UTF-16 name + uint64 size KAY file table."""

    data = archive.read_bytes()
    output_dir.mkdir(parents=True, exist_ok=True)
    offset = 0
    entries: list[dict[str, object]] = []
    root = output_dir.resolve()
    while offset + 10 <= len(data):
        name_end = offset
        while name_end + 1 < len(data) and data[name_end : name_end + 2] != b"\0\0":
            name_end += 2
        if name_end == offset or name_end + 10 > len(data):
            break
        try:
            name = data[offset:name_end].decode("utf-16le")
        except UnicodeDecodeError:
            break
        size = struct.unpack_from("<Q", data, name_end + 2)[0]
        content_start = name_end + 10
        content_end = content_start + size
        if content_end > len(data):
            break
        relative = Path(name.replace("\\", "/"))
        target = (root / relative).resolve()
        if root not in target.parents:
            raise RuntimeError(f"unsafe archive path: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data[content_start:content_end])
        entries.append(
            {
                "name": name,
                "size": size,
                "sha256": hashlib.sha256(data[content_start:content_end]).hexdigest(),
                "prefix_hex": data[content_start : content_start + 8].hex(),
            }
        )
        offset = content_end
    return {
        "output_dir": str(root),
        "entries": entries,
        "entry_count": len(entries),
        "parsed_bytes": offset,
        "archive_bytes": len(data),
        "trailing_bytes": len(data) - offset,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--unpack", type=Path)
    parser.add_argument("--extract-dir", type=Path)
    parser.add_argument("--dump-largest", type=Path)
    args = parser.parse_args()
    report, payload = inspect(args.executable)
    if args.dump_largest:
        args.dump_largest.parent.mkdir(parents=True, exist_ok=True)
        args.dump_largest.write_bytes(payload)
        report["dumped_largest"] = {
            "path": str(args.dump_largest.resolve()),
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    if args.unpack:
        report["unpacked"] = unpack(payload, args.unpack)
        if args.extract_dir:
            report["archive"] = extract_archive(args.unpack, args.extract_dir)
    elif args.extract_dir:
        raise SystemExit("--extract-dir requires --unpack")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
