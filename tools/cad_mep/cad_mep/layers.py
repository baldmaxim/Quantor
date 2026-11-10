"""Слои выходного DXF: имена, цвета AutoCAD (ACI) и принадлежность системам."""

from __future__ import annotations

# слой -> (система, цвет ACI)
ROUTE_LAYERS: dict[str, tuple[str, int]] = {
    "M-OV-T1": ("heating", 1),
    "M-OV-T2": ("heating", 5),
    "M-PT-VPV": ("fire", 6),
    "M-PT-AUP": ("fire", 30),
    "M-VK-V1": ("water", 3),
    "M-VK-T3": ("water", 40),
    "M-VK-T4": ("water", 150),
    "M-VK-K1": ("sewer", 2),
}
MARK_LAYERS: dict[str, int] = {"M-NODE": 4, "M-RISER": 7}
WALL_LAYER = "A-WALL"
WALL_PDF_LAYER = "A-WALL-PDF"
ANNO_LAYER = "M-ANNO"

SYSTEM_OF_LAYER: dict[str, str] = {k: v[0] for k, v in ROUTE_LAYERS.items()}
SYSTEMS = ("heating", "fire", "water", "sewer")
