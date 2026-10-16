from synthetic_provider import SyntheticProvider


def test_aggregates_and_orders_by_fund():
    provider = SyntheticProvider()
    result = provider.execute_dax('EVALUATE TOPN(5, SUMMARIZECOLUMNS(\'Fund\'[FundName], "Total Allocation", [Total Allocation]), [Total Allocation], DESC) ORDER BY [Total Allocation] DESC')
    assert len(result) == 5
    assert result["Total Allocation"].is_monotonic_decreasing


def test_applies_dimension_filters():
    provider = SyntheticProvider()
    result = provider.execute_dax('EVALUATE SUMMARIZECOLUMNS(\'Fund\'[RiskLevel], "Total Allocation", [Total Allocation])', {"FundType": "Bond"})
    assert set(result.RiskLevel) == {"Low"}


def test_orders_time_series_chronologically():
    provider = SyntheticProvider()
    result = provider.execute_dax('EVALUATE SUMMARIZECOLUMNS(\'Date\'[YearMonth], "Total Allocation", [Total Allocation]) ORDER BY [YearMonth] ASC')
    assert result.YearMonth.is_monotonic_increasing
