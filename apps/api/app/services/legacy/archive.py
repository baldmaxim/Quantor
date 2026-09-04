"""Безопасное чтение ZIP-архива распознавалки.

Архив приходит от пользователя и считается недоверенным. Стандартный `extractall` здесь
неприменим: он с радостью запишет файл по пути `../../../etc/passwd` и развернёт бомбу
сжатия, положив диск.

Правила модуля:

- ни одного обращения к файловой системе по пути из архива — имена только читаются;
- ограничены число файлов, сжатый и распакованный размер, размер отдельного файла
  и степень сжатия;
- ссылки и специальные файлы отвергаются;
- расширения по белому списку;
- имена декодируются в Unicode с запасным вариантом для архиваторов без флага UTF-8.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import IO, Final

from app.errors import DomainError, ErrorCode

# Что вообще может лежать в пакете распознавалки.
ALLOWED_EXTENSIONS: Final[frozenset[str]] = frozenset({"pdf", "json", "md", "html", "htm", "txt"})

# Признак «внешнего» атрибута с типом файла: старшие 16 бит хранят режим в стиле Unix.
_UNIX_MODE_SHIFT: Final = 16
_S_IFMT: Final = 0o170000
_S_IFREG: Final = 0o100000
_S_IFDIR: Final = 0o040000

# Флаг бита 11 в общем поле: имена внутри архива закодированы в UTF-8.
_UTF8_FLAG: Final = 0x800
# Кодировка, которой пользуются русскоязычные архиваторы без этого флага.
_LEGACY_ENCODING: Final = "cp866"


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Пределы, за которыми архив считается опасным."""

    max_files: int = 64
    max_total_uncompressed_bytes: int = 2 * 1024**3
    max_file_bytes: int = 1024**3
    # Во сколько раз распакованный файл может быть больше сжатого. Обычный PDF почти
    # не сжимается, текст сжимается в разы; тысячекратное сжатие — признак бомбы.
    max_compression_ratio: int = 200


@dataclass(frozen=True, slots=True)
class ArchiveMember:
    """Файл внутри архива, прошедший проверки."""

    name: str
    size: int
    compressed_size: int

    @property
    def extension(self) -> str:
        _, _, tail = self.name.rpartition(".")
        return tail.lower()


def decode_member_name(info: zipfile.ZipInfo) -> str:
    """Возвращает имя файла в Unicode.

    Архиватор обязан ставить флаг UTF-8, но старые программы этого не делают и пишут имена
    в кодировке DOS. Русские имена в таких архивах встречаются постоянно, поэтому нужен
    запасной вариант — иначе пакет отвергается на ровном месте.
    """
    if info.flag_bits & _UTF8_FLAG:
        return info.filename
    try:
        return info.orig_filename.encode("cp437").decode(_LEGACY_ENCODING)
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def _is_unsafe_path(name: str) -> bool:
    """Отвергает всё, что пытается выйти за пределы архива."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("//"):
        return True
    # Диск в стиле Windows: `C:/...`.
    if len(normalized) > 1 and normalized[1] == ":":
        return True
    path = PurePosixPath(normalized)
    if path.is_absolute():
        return True
    return any(part == ".." for part in path.parts)


def _is_regular_file(info: zipfile.ZipInfo) -> bool:
    """Отвергает каталоги, ссылки и устройства.

    Символическая ссылка внутри архива — способ заставить импортёр прочитать чужой файл
    на сервере, поэтому пропускаются только обычные файлы.
    """
    if info.is_dir():
        return False
    mode = info.external_attr >> _UNIX_MODE_SHIFT
    if mode == 0:
        # Архиватор не записал режим — считаем обычным файлом, других признаков нет.
        return True
    file_type = mode & _S_IFMT
    return file_type in (_S_IFREG, 0) and file_type != _S_IFDIR


def inspect(archive: zipfile.ZipFile, limits: ArchiveLimits) -> list[ArchiveMember]:
    """Проверяет содержимое архива, ничего не распаковывая.

    Все проверки выполняются по оглавлению: если архив опасен, импорт останавливается
    до того, как хоть один байт будет прочитан.
    """
    infos = archive.infolist()
    if len(infos) > limits.max_files:
        raise DomainError(
            ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
            f"В архиве больше {limits.max_files} файлов",
        )

    members: list[ArchiveMember] = []
    total_uncompressed = 0

    for info in infos:
        name = decode_member_name(info)

        if _is_unsafe_path(name):
            raise DomainError(
                ErrorCode.ARCHIVE_UNSAFE_PATH,
                "В архиве есть файл с недопустимым путём",
            )
        if not _is_regular_file(info):
            if info.is_dir():
                continue
            raise DomainError(
                ErrorCode.ARCHIVE_UNSAFE_PATH,
                "В архиве есть ссылка или специальный файл",
            )

        extension = name.rpartition(".")[2].lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise DomainError(
                ErrorCode.ARCHIVE_UNSAFE_PATH,
                f"В архиве есть файл неожиданного типа: .{extension}",
            )

        if info.file_size > limits.max_file_bytes:
            raise DomainError(
                ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                "Один из файлов архива превышает допустимый размер",
            )

        total_uncompressed += info.file_size
        if total_uncompressed > limits.max_total_uncompressed_bytes:
            raise DomainError(
                ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                "Распакованный архив превышает допустимый размер",
            )

        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > limits.max_compression_ratio:
                raise DomainError(
                    ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                    "Подозрительная степень сжатия — архив похож на бомбу",
                )

        members.append(
            ArchiveMember(name=name, size=info.file_size, compressed_size=info.compress_size)
        )

    if not members:
        raise DomainError(ErrorCode.CORRUPT_ARCHIVE, "Архив пуст")

    return members


def open_member(archive: zipfile.ZipFile, member: ArchiveMember) -> IO[bytes]:
    """Открывает файл архива на чтение по исходному имени.

    Имя ищется по оглавлению, а не подставляется в путь: так исключается разница между
    декодированным именем и тем, что лежит в архиве.
    """
    for info in archive.infolist():
        if decode_member_name(info) == member.name:
            return archive.open(info, "r")
    raise DomainError(ErrorCode.CORRUPT_ARCHIVE, f"Файл {member.name} исчез из архива")


def read_member(archive: zipfile.ZipFile, member: ArchiveMember, *, max_bytes: int) -> bytes:
    """Читает файл целиком с жёстким ограничением.

    Заявленный в оглавлении размер — это обещание архива, а не факт. Читаем на байт больше
    предела и проверяем, что лишнего не оказалось.
    """
    with open_member(archive, member) as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise DomainError(
            ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
            f"Файл {member.name} оказался больше заявленного размера",
        )
    return data


def iter_member(
    archive: zipfile.ZipFile, member: ArchiveMember, *, chunk_size: int, max_bytes: int
) -> Iterator[bytes]:
    """Читает файл архива кусками — для больших PDF, которые нельзя держать в памяти."""
    received = 0
    with open_member(archive, member) as stream:
        while chunk := stream.read(chunk_size):
            received += len(chunk)
            if received > max_bytes:
                raise DomainError(
                    ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                    f"Файл {member.name} оказался больше заявленного размера",
                )
            yield chunk
