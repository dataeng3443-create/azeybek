import pytest

from dax_validator import DaxValidationError, DaxValidator
from synthetic_provider import SyntheticProvider


@pytest.fixture(scope="module")
def validator():
    return DaxValidator(SyntheticProvider().get_schema())


def test_accepts_read_only_evaluate_query(validator):
    query = 'EVALUATE SUMMARIZECOLUMNS(\'Fund\'[FundName], "Total Allocation", [Total Allocation]) ORDER BY [Total Allocation] DESC'
    assert validator.validate(query).startswith("EVALUATE")


@pytest.mark.parametrize("query", ["SUMMARIZECOLUMNS()", "EVALUATE; DELETE FROM Fund", "EVALUATE SUMMARIZECOLUMNS('Fund'[NotAField])"])
def test_rejects_unsafe_or_invalid_queries(validator, query):
    with pytest.raises(DaxValidationError):
        validator.validate(query)
