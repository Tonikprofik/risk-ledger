from pathlib import Path

import pytest

from loss_experience.sources import CsvObservationSource


def write_csv(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "observations.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_empty_nan_and_sentinel_cells_become_nodata(tmp_path: Path) -> None:
    path = write_csv(tmp_path, "asset_id,value\nF1,0.5\nF1,\nF1,nan\nF1,-9999\nF1,0\n")

    found = CsvObservationSource(path, nodata=-9999).observations("F1")

    assert found is not None
    assert found.values == (0.5, None, None, None, 0.0)


def test_unknown_asset_is_none(tmp_path: Path) -> None:
    source = CsvObservationSource(write_csv(tmp_path, "asset_id,value\nF1,0.5\n"))

    assert source.observations("F9") is None


def test_missing_column_fails_at_load(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"lacks columns \['value'\]"):
        CsvObservationSource(write_csv(tmp_path, "asset_id,ndvi\nF1,0.5\n"))


def test_non_numeric_value_names_the_line(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"observations\.csv:3"):
        CsvObservationSource(write_csv(tmp_path, "asset_id,value\nF1,0.5\nF1,high\n"))
