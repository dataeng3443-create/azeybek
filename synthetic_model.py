from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from models import ColumnSchema, MeasureSchema, RelationshipSchema, SemanticSchema, TableSchema


@dataclass(frozen=True)
class SyntheticModel:
    funds: pd.DataFrame
    dates: pd.DataFrame
    investors: pd.DataFrame
    assets: pd.DataFrame
    market: pd.DataFrame
    allocation: pd.DataFrame
    schema: SemanticSchema


MEASURES = [
    ("Total Allocation", "SUM(Allocation[AllocationAmount])", "Allocated capital across selected records."),
    ("Average Allocation", "AVERAGE(Allocation[AllocationAmount])", "Mean allocation per position."),
    ("Total Target Allocation", "SUM(Allocation[TargetAllocation])", "Target allocation across selected records."),
    ("Allocation Variance", "SUM(Allocation[ActualAllocation]) - SUM(Allocation[TargetAllocation])", "Actual minus target allocation."),
    ("Allocation Variance %", "DIVIDE([Allocation Variance], [Total Target Allocation])", "Variance relative to target."),
    ("Average Return %", "AVERAGE(Allocation[ReturnPercent])", "Average monthly position return."),
    ("Total Units", "SUM(Allocation[Units])", "Total units held."),
    ("Average NAV", "AVERAGE(Allocation[NAV])", "Average net asset value."),
    ("Fund Count", "DISTINCTCOUNT(Fund[FundID])", "Number of funds in scope."),
    ("Investor Count", "DISTINCTCOUNT(Investor[InvestorID])", "Number of investors in scope."),
    ("Asset Count", "DISTINCTCOUNT(Asset[AssetID])", "Number of assets in scope."),
    ("YTD Allocation", "TOTALYTD([Total Allocation], Date[Date])", "Allocation for the current year."),
    ("Previous Month Allocation", "CALCULATE([Total Allocation], PREVIOUSMONTH(Date[Date]))", "Previous month's allocation."),
    ("MoM Growth %", "DIVIDE([Total Allocation] - [Previous Month Allocation], [Previous Month Allocation])", "Month-over-month growth."),
    ("Previous Year Allocation", "CALCULATE([Total Allocation], SAMEPERIODLASTYEAR(Date[Date]))", "Prior-year allocation."),
    ("YoY Growth %", "DIVIDE([Total Allocation] - [Previous Year Allocation], [Previous Year Allocation])", "Year-over-year growth."),
    ("Top Fund Allocation", "MAXX(VALUES(Fund[FundName]), [Total Allocation])", "Highest individual fund allocation."),
    ("Total Net Flow", "SUM(Allocation[NetFlow])", "Net subscriptions and redemptions."),
    ("Average Fee %", "AVERAGE(Allocation[ManagementFeePercent])", "Average annual management fee."),
    ("Average Exposure %", "AVERAGE(Allocation[ExposurePercent])", "Average portfolio exposure weight."),
]


def build_synthetic_model(seed: int = 42) -> SyntheticModel:
    rng = np.random.default_rng(seed)
    fund_types = ["Equity", "Bond", "Money Market", "Mixed", "Alternative", "Commodity"]
    risk_by_type = {"Equity": "High", "Bond": "Low", "Money Market": "Low", "Mixed": "Medium", "Alternative": "Very High", "Commodity": "High"}
    managers = ["Aster Capital", "Northstar", "Marmara Asset", "Pioneer", "Atlas Partners"]
    regions = ["Türkiye", "Europe", "North America", "Global"]
    fund_rows = []
    for index in range(30):
        fund_type = fund_types[index % len(fund_types)]
        fund_rows.append({"FundID": f"F{index + 1:03d}", "FundName": f"{['Atlas', 'Nova', 'Orion', 'Luna', 'Vertex'][index % 5]} {fund_type} {index + 1}", "FundType": fund_type, "RiskLevel": risk_by_type[fund_type], "Currency": "TRY" if index % 3 else "USD", "Manager": managers[index % len(managers)], "Region": regions[index % len(regions)], "Strategy": ["Core", "Growth", "Income", "Defensive"][index % 4], "Benchmark": {"Equity": "BIST 100", "Bond": "Govt Bond Index", "Money Market": "TRYREF", "Mixed": "Balanced 60/40", "Alternative": "Alternatives Index", "Commodity": "Commodity Index"}[fund_type], "AUMBand": ["Small", "Mid", "Large"][index % 3], "LaunchDate": pd.Timestamp("2015-01-01") + pd.DateOffset(months=index * 4)})
    funds = pd.DataFrame(fund_rows)

    dates = pd.date_range("2024-01-01", "2026-12-01", freq="MS")
    date_df = pd.DataFrame({"Date": dates})
    date_df["Year"] = date_df.Date.dt.year
    date_df["Quarter"] = "Q" + date_df.Date.dt.quarter.astype(str)
    date_df["Month"] = date_df.Date.dt.month_name().str[:3]
    date_df["MonthNumber"] = date_df.Date.dt.month
    date_df["YearMonth"] = date_df.Date.dt.strftime("%Y-%m")
    date_df["Week"] = date_df.Date.dt.isocalendar().week.astype(int)

    investor_types = ["Retail", "Institutional", "Corporate", "Private Banking"]
    investor_rows = []
    for index in range(64):
        investor_type = investor_types[index % 4]
        investor_rows.append({"InvestorID": f"I{index + 1:03d}", "InvestorType": investor_type, "Segment": "Mass Affluent" if investor_type == "Retail" else investor_type, "Region": regions[index % len(regions)], "AgeGroup": ["25-34", "35-44", "45-54", "55+"][index % 4], "TenureBand": ["< 1 year", "1-3 years", "3-5 years", "5+ years"][index % 4], "ESGPreference": ["Low", "Medium", "High"][index % 3]})
    investors = pd.DataFrame(investor_rows)

    asset_definitions = [("Equity", "Technology"), ("Equity", "Financials"), ("Bond", "Government"), ("Bond", "Corporate"), ("Cash", "Cash"), ("Gold", "Precious Metals"), ("Silver", "Precious Metals"), ("Commodity", "Energy"), ("ETF", "Global Equity"), ("Alternative", "Real Estate")]
    assets = pd.DataFrame([{"AssetID": f"A{i + 1:03d}", "AssetName": f"{sector} {asset_class} {i + 1}", "AssetClass": asset_class, "Sector": sector, "Country": ["Türkiye", "US", "Germany", "Global"][i % 4], "Currency": "TRY" if i % 3 else "USD", "CreditRating": "AAA" if asset_class == "Bond" and i % 2 == 0 else ("AA" if asset_class == "Bond" else "N/A"), "LiquidityTier": ["Daily", "Weekly", "Monthly"][i % 3]} for i, (asset_class, sector) in enumerate(asset_definitions * 2)])

    market = date_df[["Date", "YearMonth"]].copy()
    market["MarketRegime"] = ["Risk-off" if 12 <= i <= 15 else ("Recovery" if 16 <= i <= 23 else "Expansion") for i in range(len(market))]
    market["BISTReturnPercent"] = [round(float(rng.normal(-0.035 if regime == "Risk-off" else (0.022 if regime == "Recovery" else 0.009), 0.025)), 4) for regime in market.MarketRegime]
    market["InterestRate"] = [round(0.34 + (0.12 if regime == "Risk-off" else 0) + float(rng.normal(0, 0.01)), 4) for regime in market.MarketRegime]
    market["FXChangePercent"] = [round(float(rng.normal(0.012, 0.018)), 4) for _ in market.itertuples()]

    volatility = {"Equity": 0.09, "Bond": 0.025, "Money Market": 0.008, "Mixed": 0.05, "Alternative": 0.12, "Commodity": 0.11}
    return_bias = {"Equity": 0.010, "Bond": 0.004, "Money Market": 0.0025, "Mixed": 0.007, "Alternative": 0.009, "Commodity": 0.006}
    rows: list[dict[str, object]] = []
    for month_index, date in enumerate(dates):
        market_cycle = -0.065 if 12 <= month_index <= 15 else (0.045 if 16 <= month_index <= 23 else 0.0)
        for fund in funds.itertuples(index=False):
            size = 2_500_000 * (1 + (int(fund.FundID[1:]) % 10) / 3)
            type_weight = {"Equity": 1.25, "Bond": 1.1, "Money Market": 0.9, "Mixed": 1.05, "Alternative": 0.75, "Commodity": 0.65}[fund.FundType]
            for investor in investors.itertuples(index=False):
                if rng.random() > 0.30:
                    continue
                investor_weight = {"Retail": 0.65, "Institutional": 2.1, "Corporate": 1.45, "Private Banking": 1.15}[investor.InvestorType]
                for asset_id in rng.choice(assets.AssetID.to_numpy(), size=2, replace=False):
                    asset = assets.loc[assets.AssetID.eq(asset_id)].iloc[0]
                    expected_return = return_bias[fund.FundType] + market_cycle
                    monthly_return = float(np.clip(rng.normal(expected_return, volatility[fund.FundType] / np.sqrt(12)), -0.25, 0.30))
                    target = size * type_weight * investor_weight * rng.uniform(0.008, 0.028)
                    actual = target * (1 + monthly_return + rng.normal(0, 0.025))
                    nav = max(0.5, 100 * (1 + monthly_return) * rng.uniform(0.94, 1.06))
                    net_flow = target * rng.normal(0.016 if market_cycle >= 0 else -0.009, 0.018)
                    rows.append({"Date": date, "FundID": fund.FundID, "InvestorID": investor.InvestorID, "AssetID": asset.AssetID, "AllocationAmount": round(actual, 2), "TargetAllocation": round(target, 2), "ActualAllocation": round(actual, 2), "Units": round(actual / nav, 2), "NAV": round(nav, 2), "ReturnPercent": monthly_return, "NetFlow": round(net_flow, 2), "ManagementFeePercent": round({"Equity": .018, "Bond": .011, "Money Market": .006, "Mixed": .014, "Alternative": .022, "Commodity": .019}[fund.FundType], 4), "ExposurePercent": round(float(rng.uniform(.01, .08)), 4)})
    allocation = pd.DataFrame(rows)
    schema = SemanticSchema(model="FundAllocation", tables=[
        TableSchema(name="Fund", columns=[ColumnSchema(name=name, data_type=kind) for name, kind in [("FundID", "string"), ("FundName", "string"), ("FundType", "string"), ("RiskLevel", "string"), ("Currency", "string"), ("Manager", "string"), ("Region", "string"), ("Strategy", "string"), ("Benchmark", "string"), ("AUMBand", "string"), ("LaunchDate", "date")]]),
        TableSchema(name="Date", columns=[ColumnSchema(name=name, data_type=kind) for name, kind in [("Date", "date"), ("Year", "integer"), ("Quarter", "string"), ("Month", "string"), ("MonthNumber", "integer"), ("YearMonth", "string"), ("Week", "integer")]]),
        TableSchema(name="Investor", columns=[ColumnSchema(name=name, data_type="string") for name in ["InvestorID", "InvestorType", "Segment", "Region", "AgeGroup", "TenureBand", "ESGPreference"]]),
        TableSchema(name="Asset", columns=[ColumnSchema(name=name, data_type="string") for name in ["AssetID", "AssetName", "AssetClass", "Sector", "Country", "Currency", "CreditRating", "LiquidityTier"]]),
        TableSchema(name="Market", columns=[ColumnSchema(name="Date", data_type="date"), ColumnSchema(name="YearMonth", data_type="string"), ColumnSchema(name="MarketRegime", data_type="string"), ColumnSchema(name="BISTReturnPercent", data_type="number"), ColumnSchema(name="InterestRate", data_type="number"), ColumnSchema(name="FXChangePercent", data_type="number")]),
        TableSchema(name="Allocation", columns=[ColumnSchema(name=name, data_type=kind) for name, kind in [("Date", "date"), ("FundID", "string"), ("InvestorID", "string"), ("AssetID", "string"), ("AllocationAmount", "number"), ("TargetAllocation", "number"), ("ActualAllocation", "number"), ("Units", "number"), ("NAV", "number"), ("ReturnPercent", "number"), ("NetFlow", "number"), ("ManagementFeePercent", "number"), ("ExposurePercent", "number")]], measures=[MeasureSchema(name=name, expression=expression, description=description) for name, expression, description in MEASURES]),
    ], relationships=[
        RelationshipSchema(from_table="Date", from_column="Date", to_table="Allocation", to_column="Date"),
        RelationshipSchema(from_table="Fund", from_column="FundID", to_table="Allocation", to_column="FundID"),
        RelationshipSchema(from_table="Investor", from_column="InvestorID", to_table="Allocation", to_column="InvestorID"),
        RelationshipSchema(from_table="Asset", from_column="AssetID", to_table="Allocation", to_column="AssetID"),
        RelationshipSchema(from_table="Market", from_column="Date", to_table="Allocation", to_column="Date"),
    ])
    return SyntheticModel(funds=funds, dates=date_df, investors=investors, assets=assets, market=market, allocation=allocation, schema=schema)
