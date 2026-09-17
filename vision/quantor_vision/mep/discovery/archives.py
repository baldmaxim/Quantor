"""Preflight every member before streaming any payload. Never use extractall."""

from __future__ import annotations

import asyncio
import shutil
import stat
import struct
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

from .common import DiscoveryRefusedError, copy_bounded


@dataclass(frozen=True)
class Limits:
    max_members: int = 100_000
    max_archive_bytes: int = 32 * 1024**3
    max_file_bytes: int = 2 * 1024**3
    max_total_bytes: int = 100 * 1024**3
    max_ratio: int = 200
    max_depth: int = 2


@dataclass
class Member:
    path: str
    size: int
    compressed_size: int | None
    crc: str | None
    encrypted: bool
    directory: bool
    link: bool
    name_bytes_hex: str | None
    encoding: str
    original_name: str


@dataclass
class Archive:
    sha256: str
    source: str
    depth: int
    status: str = "LISTED"
    reasons: list[str] = field(default_factory=list)
    members: list[Member] = field(default_factory=list)


def safe_name(name: str) -> str:
    path = PureWindowsPath(name)
    parts = name.replace("\\", "/").rstrip("/").split("/")
    if path.drive or path.root or not parts or any(p in ("", ".", "..") for p in parts):
        raise DiscoveryRefusedError("unsafe_path")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10))
    for part in parts:
        if any(ord(c) < 32 or c in ':<>"|?*' for c in part):
            raise DiscoveryRefusedError("unsafe_path")
        if part.endswith((".", " ")) or part.split(".")[0].upper() in reserved:
            raise DiscoveryRefusedError("unsafe_windows_path")
    return "/".join(parts)


def decode_name(info: zipfile.ZipInfo, legacy: str) -> tuple[str, str, str]:
    if info.flag_bits & 0x800:
        raw = info.orig_filename.encode("utf-8")
        return info.orig_filename, raw.hex(), "utf-8"
    raw = info.orig_filename.encode("cp437")
    extra = info.extra
    while len(extra) >= 4:
        kind, length = struct.unpack("<HH", extra[:4])
        value, extra = extra[4 : 4 + length], extra[4 + length :]
        if kind == 0x7075 and len(value) >= 5:
            version, crc = struct.unpack("<BL", value[:5])
            if version == 1 and crc == zlib.crc32(raw):
                return value[5:].decode("utf-8"), raw.hex(), "zip_unicode_extra"
    if raw.isascii():
        return raw.decode("ascii"), raw.hex(), "ascii"
    # Explicit, recorded choice: an unflagged ZIP cannot prove its code page.
    return raw.decode(legacy, errors="strict"), raw.hex(), legacy


def zip_listing(path: Path, legacy: str) -> list[Member]:
    with zipfile.ZipFile(path) as archive:
        members = []
        for info in archive.infolist():
            name, raw, encoding = decode_name(info, legacy)
            mode = stat.S_IFMT(info.external_attr >> 16)
            members.append(
                Member(
                    name,
                    info.file_size,
                    info.compress_size,
                    f"{info.CRC:08x}",
                    bool(info.flag_bits & 1),
                    info.is_dir(),
                    mode not in (0, stat.S_IFREG, stat.S_IFDIR) or bool(info.external_attr & 0x400),
                    raw,
                    encoding,
                    info.filename,
                )
            )
        return members


def seven_zip() -> str:
    for name in ("7z", "7za", "7zz"):
        executable = shutil.which(name)
        if executable:
            return executable
    raise DiscoveryRefusedError("seven_zip_unavailable")


async def _command(args: list[str], limit: int, output: Path | None) -> bytes:
    # No shell; -spd disables wildcards and -- separates archive/member arguments.
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        stdin=asyncio.subprocess.DEVNULL,
    )
    chunks: list[bytes] = []
    received = 0
    stream = output.open("xb") if output else None
    try:
        async with asyncio.timeout(300):
            if proc.stdout is None:
                raise DiscoveryRefusedError("seven_zip_no_stdout")
            while chunk := await proc.stdout.read(1024 * 1024):
                received += len(chunk)
                if received > limit:
                    raise DiscoveryRefusedError("seven_zip_output_limit")
                if stream:
                    stream.write(chunk)
                else:
                    chunks.append(chunk)
            if await proc.wait() != 0:
                raise DiscoveryRefusedError("seven_zip_failed")
            if output and received != limit:
                raise DiscoveryRefusedError("actual_size_differs_from_listing")
    finally:
        if stream:
            stream.close()
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    return b"".join(chunks)


def seven_listing(path: Path) -> list[Member]:
    data = asyncio.run(
        _command(
            [seven_zip(), "l", "-slt", "-ba", "-sccUTF-8", "--", str(path)],
            64 * 1024**2,
            None,
        )
    ).decode("utf-8", errors="strict")
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in [*data.splitlines(), ""]:
        if not line.strip():
            if current:
                records.append(current)
                current = {}
        elif " = " in line:
            key, value = line.split(" = ", 1)
            current[key] = value
    members = []
    for entry in records:
        if "Path" not in entry:
            raise DiscoveryRefusedError("invalid_seven_zip_listing")
        packed = entry.get("Packed Size", "")
        members.append(
            Member(
                entry["Path"],
                int(entry.get("Size", "0") or "0"),
                int(packed) if packed else None,
                entry.get("CRC"),
                entry.get("Encrypted") == "+",
                entry.get("Folder") == "+" or entry.get("Attributes", "").startswith("D"),
                any(k in entry for k in ("Symbolic Link", "Hard Link", "Reparse"))
                or "l" in entry.get("Attributes", ""),
                None,
                "7z_unicode_original_bytes_unavailable",
                entry["Path"],
            )
        )
    return members


def validate(members: list[Member], archive_size: int, limits: Limits) -> None:
    if len(members) > limits.max_members:
        raise DiscoveryRefusedError("member_count_limit")
    total = sum(member.size for member in members)
    if total > limits.max_archive_bytes:
        raise DiscoveryRefusedError("archive_size_limit")
    if total / max(archive_size, 1) > limits.max_ratio:
        raise DiscoveryRefusedError("archive_ratio_limit")
    names: dict[str, bool] = {}
    for member in members:
        normalized = unicodedata.normalize("NFC", safe_name(member.path)).casefold()
        if normalized in names:
            raise DiscoveryRefusedError("duplicate_or_case_colliding_path")
        names[normalized] = member.directory
        if member.link:
            raise DiscoveryRefusedError("link_or_special_file")
        if member.encrypted:
            raise DiscoveryRefusedError("encrypted_member")
        if member.size < 0 or member.size > limits.max_file_bytes:
            raise DiscoveryRefusedError("file_size_limit")
        if (
            member.compressed_size is not None
            and member.size / max(member.compressed_size, 1) > limits.max_ratio
        ):
            raise DiscoveryRefusedError("member_ratio_limit")
    for name in names:
        parts = name.split("/")
        if any(names.get("/".join(parts[:n])) is False for n in range(1, len(parts))):
            raise DiscoveryRefusedError("file_directory_collision")


def extract_member(archive: Path, member: Member, target: Path) -> None:
    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive) as container, container.open(member.original_name) as source:
            copy_bounded(source, target, member.size)
    else:
        asyncio.run(
            _command(
                [seven_zip(), "x", "-so", "-spd", "-y", "--", str(archive), member.original_name],
                member.size,
                target,
            )
        )


def extract_members(archive: Path, members: list[Member], staging: Path) -> None:
    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive) as container:
            for i, member in enumerate(members):
                if not member.directory:
                    with container.open(member.original_name) as stream:
                        copy_bounded(stream, staging / str(i), member.size)
    else:
        for i, member in enumerate(members):
            if not member.directory:
                extract_member(archive, member, staging / str(i))
