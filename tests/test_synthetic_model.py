from synthetic_model import build_synthetic_model


def test_model_has_expected_tables_relationships_and_realistic_data():
    model = build_synthetic_model(7)
    assert {table.name for table in model.schema.tables} == {"Fund", "Date", "Investor", "Asset", "Market", "Allocation"}
    assert len(model.schema.relationships) == 5
    assert len(model.funds) == 30
    assert model.dates.Date.min().year == 2024
    assert model.dates.Date.max().year == 2026
    assert len(model.allocation) > 10_000
    assert (model.allocation.AllocationAmount > 0).all()
