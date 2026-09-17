"""Skip unused path coordinates before pypdf parses text and image transforms.

Painting operators and clipping markers stay intact. Strings, hex strings and
comments are opaque; inline images/dictionaries disable this optimization.
"""

from __future__ import annotations

import re

_NUMBER = rb"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)"
_SPACE = rb"[\x00\t\n\f\r ]+"
_PATH = re.compile(
    rb"(?<![^\x00\t\n\f\r ])(?:"
    + rb"(?:"
    + _NUMBER
    + _SPACE
    + rb"){2}[ml]|"
    + rb"(?:"
    + _NUMBER
    + _SPACE
    + rb"){4}(?:re|v|y)|"
    + rb"(?:"
    + _NUMBER
    + _SPACE
    + rb"){6}c"
    + rb")(?=[\x00\t\n\f\r ]|$)"
)
_PROTECTED = re.compile(rb"[\(<%]|\bBI\b")


def without_path_coordinates(data: bytes) -> bytes:
    output: list[bytes] = []
    position = 0
    while match := _PROTECTED.search(data, position):
        start = match.start()
        output.append(_PATH.sub(b"", data[position:start]))
        if data.startswith((b"BI", b"<<"), start):
            return data
        if data[start : start + 1] == b"%":
            end = data.find(b"\n", start)
            if end < 0:
                end = len(data)
        elif data[start : start + 1] == b"<":
            end = data.find(b">", start) + 1
            if end == 0:
                return data
        else:
            depth, end = 1, start + 1
            while depth and end < len(data):
                char = data[end : end + 1]
                if char == b"\\":
                    end += 2
                    continue
                if char == b"(":
                    depth += 1
                elif char == b")":
                    depth -= 1
                end += 1
            if depth:
                return data
        output.append(data[start:end])
        position = end
    output.append(_PATH.sub(b"", data[position:]))
    return b"".join(output)
