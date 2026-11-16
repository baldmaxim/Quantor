"""Запись GLB по разделу 7: узел на элемент, плоский материал на категорию, деление на части.

Без нормалей (просмотрщик glTF сам строит плоские), без текстур и расширений. Все вершины
узлов лежат в одном bufferView (шаг 12 байт), индексы - во втором; индексы uint16, если
вершин меньше 65 535, иначе uint32. Вывод детерминирован: одинаковые узлы - одинаковые байты.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .categories import CATEGORY_COLOR

ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963
FLOAT = 5126
UNSIGNED_SHORT = 5123
UNSIGNED_INT = 5125
NODE_JSON_BYTES = 420  # оценка JSON на узел: узел, меш, два аксессора


@dataclass(frozen=True, slots=True)
class NodeMesh:
    """Меш элемента в системе glTF: метры, Y вверх."""

    name: str
    category: str
    positions: np.ndarray  # (n, 3) float32
    indices: np.ndarray  # (m,) uint16 или uint32, m кратно 3

    @property
    def triangles(self) -> int:
        return int(self.indices.size // 3)


def to_gltf_frame(vertices_mm: np.ndarray) -> np.ndarray:
    """(x, y, z) мм в системе здания → (x/1000, z/1000, −y/1000) метры (раздел 3)."""
    v = np.asarray(vertices_mm, dtype=np.float64)
    out = np.column_stack([v[:, 0], v[:, 2], -v[:, 1]]) / 1000.0
    return np.ascontiguousarray(out, dtype=np.float32)


def make_node(name: str, category: str, vertices_mm: np.ndarray, faces: np.ndarray) -> NodeMesh:
    """Узел из вершин (мм, система здания) и треугольников; индексы ужимаются до uint16."""
    positions = to_gltf_frame(vertices_mm)
    dtype = np.uint16 if len(positions) <= 0xFFFF else np.uint32
    indices = np.ascontiguousarray(np.asarray(faces).reshape(-1), dtype=dtype)
    return NodeMesh(name, category, positions, indices)


def _pad4(n: int) -> int:
    return (4 - n % 4) % 4


def estimate_bytes(node: NodeMesh) -> int:
    idx = node.indices.nbytes
    return node.positions.nbytes + idx + _pad4(idx) + NODE_JSON_BYTES + len(node.name)


def plan_parts(nodes: Sequence[NodeMesh], limit_bytes: int) -> list[list[NodeMesh]]:
    """Жадное деление узлов по порядку на части с оценкой размера не больше предела."""
    parts: list[list[NodeMesh]] = []
    current: list[NodeMesh] = []
    size = 2048
    for node in nodes:
        cost = estimate_bytes(node)
        if current and size + cost > limit_bytes:
            parts.append(current)
            current, size = [], 2048
        current.append(node)
        size += cost
    if current:
        parts.append(current)
    return parts


def _material(category: str) -> dict[str, object]:
    r, g, b = CATEGORY_COLOR.get(category, CATEGORY_COLOR["other"])
    return {
        "name": f"cat:{category}",
        "pbrMetallicRoughness": {
            "baseColorFactor": [r, g, b, 1.0],
            "metallicFactor": 0.0,
            "roughnessFactor": 1.0,
        },
        "doubleSided": True,
    }


def _bounds(positions: np.ndarray) -> tuple[list[float], list[float]]:
    lo = positions.min(axis=0)
    hi = positions.max(axis=0)
    return [float(x) for x in lo], [float(x) for x in hi]


def write_glb(nodes: Sequence[NodeMesh], generator: str) -> bytes:
    """GLB из узлов в заданном порядке. Узлы без вершин или треугольников - ошибка вызова."""
    categories = sorted({n.category for n in nodes})
    material_index = {c: i for i, c in enumerate(categories)}
    pos_blob = bytearray()
    idx_blob = bytearray()
    accessors: list[dict[str, object]] = []
    meshes: list[dict[str, object]] = []
    gnodes: list[dict[str, object]] = []
    for i, node in enumerate(nodes):
        if not len(node.positions) or not node.indices.size:
            raise ValueError(f"узел {node.name} без вершин или треугольников")
        lo, hi = _bounds(node.positions)
        accessors.append(
            {
                "bufferView": 0,
                "byteOffset": len(pos_blob),
                "componentType": FLOAT,
                "count": len(node.positions),
                "type": "VEC3",
                "min": lo,
                "max": hi,
            }
        )
        pos_blob += node.positions.tobytes()
        ctype = UNSIGNED_SHORT if node.indices.dtype == np.uint16 else UNSIGNED_INT
        accessors.append(
            {
                "bufferView": 1,
                "byteOffset": len(idx_blob),
                "componentType": ctype,
                "count": int(node.indices.size),
                "type": "SCALAR",
            }
        )
        idx_blob += node.indices.tobytes()
        idx_blob += b"\x00" * _pad4(len(idx_blob))
        meshes.append(
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 2 * i},
                        "indices": 2 * i + 1,
                        "material": material_index[node.category],
                        "mode": 4,
                    }
                ]
            }
        )
        gnodes.append({"name": node.name, "mesh": i})
    binary = bytes(pos_blob) + bytes(idx_blob)
    doc = {
        "asset": {"version": "2.0", "generator": generator},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(gnodes)))}],
        "nodes": gnodes,
        "meshes": meshes,
        "materials": [_material(c) for c in categories],
        "accessors": accessors,
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": len(pos_blob),
                "byteStride": 12,
                "target": ARRAY_BUFFER,
            },
            {
                "buffer": 0,
                "byteOffset": len(pos_blob),
                "byteLength": len(idx_blob),
                "target": ELEMENT_ARRAY_BUFFER,
            },
        ],
        "buffers": [{"byteLength": len(binary)}],
    }
    return _pack(doc, binary)


def _pack(doc: dict[str, object], binary: bytes) -> bytes:
    text = json.dumps(doc, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    jchunk = text.encode("utf-8")
    jchunk += b" " * _pad4(len(jchunk))
    bchunk = binary + b"\x00" * _pad4(len(binary))
    total = 12 + 8 + len(jchunk) + 8 + len(bchunk)
    return b"".join(
        [
            struct.pack("<4sII", b"glTF", 2, total),
            struct.pack("<I4s", len(jchunk), b"JSON"),
            jchunk,
            struct.pack("<I4s", len(bchunk), b"BIN\x00"),
            bchunk,
        ]
    )
