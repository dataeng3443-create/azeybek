import pytest
from pydantic import ValidationError

from models import DashboardComponent, DashboardSpec


def test_accepts_safe_dashboard_spec():
    spec = DashboardSpec(title="Test", components=[DashboardComponent(id="total", type="kpi", metric="Total Allocation", priority=1)])
    assert len(spec.kpis()) == 1


def test_rejects_unsupported_component():
    with pytest.raises(ValidationError):
        DashboardComponent(id="x", type="map", priority=1)
