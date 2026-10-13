from loss_experience.domain import InsufficientData, Observations, Ok, Provenance, assess

SOURCE = Provenance(source="test")


def observations(*values: float | None) -> Observations:
    return Observations("F1", values, SOURCE)


def test_mean_of_valid_samples_when_coverage_is_enough() -> None:
    result = assess(observations(0.5, 0.75, None, 1.0), min_coverage=0.5)

    assert result.outcome == Ok(0.75)
    assert result.coverage_fraction == 0.75


def test_observed_zero_is_a_real_value() -> None:
    result = assess(observations(0.0, 0.0), min_coverage=0.5)

    assert result.outcome == Ok(0.0)


def test_mostly_nodata_is_insufficient_data_not_zero() -> None:
    result = assess(observations(None, None, None, 0.4), min_coverage=0.5)

    assert result.outcome == InsufficientData()
    assert result.coverage_fraction == 0.25


def test_no_samples_is_insufficient_data() -> None:
    result = assess(observations(), min_coverage=0.5)

    assert (result.outcome, result.coverage_fraction) == (InsufficientData(), 0.0)
