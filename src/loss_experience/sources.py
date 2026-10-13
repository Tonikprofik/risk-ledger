"""Adapters that read observations. Input is parsed and validated here, once.

Swap `CsvObservationSource` for a raster, Parquet or PostGIS adapter with the same method.
"""

import csv
from pathlib import Path
from typing import Protocol

from loss_experience.domain import Observations, Provenance

REQUIRED_COLUMNS = ("asset_id", "value")


class ObservationSource(Protocol):
    def observations(self, asset_id: str) -> Observations | None:
        """Observations for the Asset, or None when the Asset is unknown."""
        ...

    def all_observations(self) -> list[Observations]:
        """Observations for every Asset, ordered by asset_id."""
        ...


class CsvObservationSource:
    """CSV with `asset_id,value` rows. An empty cell or the `nodata` sentinel is nodata."""

    def __init__(self, path: Path, *, nodata: float | None = None) -> None:
        self._provenance = Provenance(source=path.name)
        self._values: dict[str, list[float | None]] = {}
        with path.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or ())
            if missing:
                raise ValueError(f"{path.name} lacks columns {sorted(missing)}")
            for line, row in enumerate(reader, start=2):
                self._values.setdefault(row["asset_id"], []).append(
                    _parse_value(row["value"], nodata, f"{path.name}:{line}")
                )

    def observations(self, asset_id: str) -> Observations | None:
        values = self._values.get(asset_id)
        if values is None:
            return None
        return Observations(asset_id, tuple(values), self._provenance)

    def all_observations(self) -> list[Observations]:
        return [
            Observations(asset_id, tuple(values), self._provenance)
            for asset_id, values in sorted(self._values.items())
        ]


def _parse_value(raw: str, nodata: float | None, where: str) -> float | None:
    text = raw.strip()
    if text == "" or text.lower() == "nan":
        return None
    try:
        value = float(text)
    except ValueError as error:
        raise ValueError(f"{where}: value {raw!r} is not a number") from error
    return None if value == nodata else value
