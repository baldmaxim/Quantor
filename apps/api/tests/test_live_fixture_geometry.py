"""Геометрия страниц настоящего чертежа (промт 15).

Часть живой приёмки, которую можно выполнить без стенда: PDF читается тем же провайдером,
что и рабочий конвейер, и проверяется то, что вообще проверяемо без базы, — число страниц,
форма геометрии и перестановка сторон у повёрнутых листов.

Остальные шаги приёмки (калибровка по подписанному размеру, измерения, перезагрузка
браузера, вторая калибровка) требуют поднятого стенда и человека у экрана: известный размер
берётся с чертежа глазами, а не выводится программой. Их состояние — в
`docs/stage2a/live-acceptance.md`.

Без файла эталона тест пропускается. Выдумывать вместо него нечего.
"""

from __future__ import annotations

import os
import pathlib
import time
import zipfile
from collections.abc import Iterator

import pytest

from app.services.geometry.extract import fingerprint
from app.services.geometry.provider import PypdfGeometryProvider, RawPageGeometry

# Эталонный пакет распознавалки: 77 листов, 383 области (ADR-0008).
EXPECTED_PAGES = 77

FIXTURE_CANDIDATES = (
    "_prompts/stage2a_measurement_core/fixtures/live",
    "_prompts/stage1/fixtures/legacy",
)


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3]


def _fixture_archive() -> pathlib.Path | None:
    """Ищет эталон в порядке, объявленном в `fixtures/README.md` пакета промтов."""
    explicit = os.environ.get("QTO_LIVE_FIXTURE")
    if explicit:
        path = pathlib.Path(explicit)
        return path if path.exists() else None

    root = _repo_root()
    for relative in FIXTURE_CANDIDATES:
        directory = root / relative
        if not directory.is_dir():
            continue
        archives = sorted(directory.glob("*.zip"))
        if archives:
            return archives[0]
    return None


@pytest.fixture(scope="module")
def pages(tmp_path_factory: pytest.TempPathFactory) -> Iterator[list[RawPageGeometry]]:
    archive = _fixture_archive()
    if archive is None:
        pytest.skip(
            "эталонный чертёж не найден: положите архив в"
            " _prompts/stage1/fixtures/legacy или укажите QTO_LIVE_FIXTURE"
        )

    with zipfile.ZipFile(archive) as bundle:
        names = [name for name in bundle.namelist() if name.lower().endswith(".pdf")]
        assert names, "в пакете распознавалки нет исходного PDF"
        payload = bundle.read(names[0])

    # Провайдер читает файл, а не поток: так же он вызывается и в рабочем конвейере.
    #
    # Каталог выдаёт pytest, а не общий TEMP с постоянным именем: два одновременных прогона
    # на одной машине затирали бы файл друг друга, и падение выглядело бы как «иногда не
    # читается PDF».
    scratch = tmp_path_factory.mktemp("live-fixture") / "source.pdf"
    scratch.write_bytes(payload)

    started = time.perf_counter()
    extracted = PypdfGeometryProvider().read(scratch)
    elapsed = time.perf_counter() - started
    print(f"\nстраниц: {len(extracted)}, извлечение: {elapsed:.2f} с")
    yield extracted


class TestLiveFixtureGeometry:
    def test_page_count_matches_the_recognised_package(self, pages: list[RawPageGeometry]) -> None:
        """Число страниц PDF обязано совпасть с числом листов пакета.

        Расхождение означало бы, что области распознаны не на том файле, и все координаты
        относятся к другой странице.
        """
        assert len(pages) == EXPECTED_PAGES

    def test_every_page_has_positive_display_size(self, pages: list[RawPageGeometry]) -> None:
        for page in pages:
            assert page.display_width_pt > 0, f"страница {page.page_index}"
            assert page.display_height_pt > 0, f"страница {page.page_index}"

    def test_rotation_is_one_of_four_quarters(self, pages: list[RawPageGeometry]) -> None:
        assert {page.rotation for page in pages} <= {0, 90, 180, 270}

    def test_rotated_pages_have_their_sides_swapped(self, pages: list[RawPageGeometry]) -> None:
        """Ключевая проверка ADR-0016 на настоящем файле.

        При 90 и 270 стороны отображения обязаны быть переставлены относительно рамки в
        исходном пространстве PDF. Если бы этого не было, поворот пришлось бы применять
        второй раз при отрисовке — и все длины на этих листах разъехались бы.
        """
        rotated = [page for page in pages if page.rotation in (90, 270)]
        assert rotated, "в эталоне есть повёрнутые листы — иначе проверять нечего"

        for page in rotated:
            box = page.crop_box or page.media_box
            native_width = abs(box[2] - box[0])
            native_height = abs(box[3] - box[1])
            assert page.display_width_pt == pytest.approx(native_height, abs=0.01), (
                f"страница {page.page_index}: ширина отображения не равна высоте рамки"
            )
            assert page.display_height_pt == pytest.approx(native_width, abs=0.01), (
                f"страница {page.page_index}: высота отображения не равна ширине рамки"
            )

    def test_unrotated_pages_keep_their_sides(self, pages: list[RawPageGeometry]) -> None:
        for page in (item for item in pages if item.rotation == 0):
            box = page.crop_box or page.media_box
            assert page.display_width_pt == pytest.approx(abs(box[2] - box[0]), abs=0.01)
            assert page.display_height_pt == pytest.approx(abs(box[3] - box[1]), abs=0.01)

    def test_fingerprints_are_unique_per_distinct_geometry(
        self, pages: list[RawPageGeometry]
    ) -> None:
        """Одинаковая геометрия даёт одинаковый отпечаток, разная — разный.

        На отпечатке держится привязка калибровки к странице: совпадение у разных страниц
        означало бы, что масштаб одного листа молча принят за масштаб другого.
        """
        provider = PypdfGeometryProvider()
        by_shape: dict[tuple[str, str, int], set[str]] = {}
        for page in pages:
            shape = (str(page.display_width_pt), str(page.display_height_pt), page.rotation)
            by_shape.setdefault(shape, set()).add(fingerprint(page, provider))

        for shape, digests in by_shape.items():
            assert len(digests) == 1, f"одинаковая геометрия {shape} дала разные отпечатки"

        assert len(by_shape) == len({next(iter(v)) for v in by_shape.values()}), (
            "разные геометрии обязаны давать разные отпечатки"
        )
