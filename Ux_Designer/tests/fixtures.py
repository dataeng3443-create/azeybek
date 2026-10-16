"""Synthetic but realistic PBIT: multiple tables, measures, relationships, many visual kinds."""
import json, sys, zipfile

J = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
def col(src, prop): return {"Column": {"Expression": {"SourceRef": {"Source": src}}, "Property": prop}}
def mea(src, prop): return {"Measure": {"Expression": {"SourceRef": {"Source": src}}, "Property": prop}}
def agg(src, prop, f): return {"Aggregation": {"Expression": col(src, prop), "Function": f}}
def hl(src, prop, level):
    return {"HierarchyLevel": {"Expression": {"Hierarchy": {"Expression": {"PropertyVariationSource": {"Expression": {"SourceRef": {"Source": src}}, "Name": "Variation", "Property": prop}}, "Hierarchy": "Date Hierarchy"}}, "Level": level}}
N = [0]
def visual(kind, x, y, w, h, froms, selects, projections, with_query=True, extra=None, order=None, filters="[]"):
    N[0] += 1
    proto = {"Version": 2, "From": [{"Name": a, "Entity": e, "Type": 0} for a, e in froms], "Select": [dict(e, Name=n) for n, e in selects]}
    if order: proto["OrderBy"] = order
    sv = {"visualType": kind, "projections": projections, "prototypeQuery": proto, "drillFilterOtherVisuals": True}
    if extra: sv.update(extra)
    cfg = {"name": f"v{N[0]:04d}", "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": N[0]*1000, "width": w, "height": h}}], "singleVisual": sv}
    v = {"x": x, "y": y, "z": N[0]*1000, "width": w, "height": h, "config": J(cfg), "filters": filters}
    if with_query:
        v["query"] = J({"Commands": [{"SemanticQueryDataShapeCommand": {"Query": proto, "Binding": {"Primary": {"Groupings": [{"Projections": list(range(len(selects)))}]}}}}]})
        v["dataTransforms"] = J({"projectionOrdering": {k: list(range(len(v_))) for k, v_ in projections.items()}, "selects": [{"queryName": n, "displayName": n} for n, _ in selects]})
    return v
def textbox(text, x, y, w, h):
    N[0] += 1
    cfg = {"name": f"t{N[0]:04d}", "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": N[0]*1000, "width": w, "height": h}}],
           "singleVisual": {"visualType": "textbox", "drillFilterOtherVisuals": True, "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": text, "textStyle": {"fontSize": "20pt"}}]}]}}]}}}
    return {"x": x, "y": y, "z": N[0]*1000, "width": w, "height": h, "config": J(cfg)}
def plain(kind, x, y, w, h, extra=None):
    N[0] += 1
    cfg = {"name": f"p{N[0]:04d}", "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": N[0]*1000, "width": w, "height": h}}], "singleVisual": {"visualType": kind, **(extra or {})}}
    return {"x": x, "y": y, "z": N[0]*1000, "width": w, "height": h, "config": J(cfg)}
def section(name, visuals, w=1280, h=720, config=None):
    return {"name": name, "displayName": name, "filters": "[]", "ordinal": 0, "visualContainers": visuals, "config": J(config or {}), "displayOption": 1, "width": w, "height": h}

def build(path, bookmarks=False, only_measures=False):
    N[0] = 0
    s, p, c = "s", "p", "c"
    page1 = [
        textbox("Sales Performance Overview", 0, 0, 1280, 60),
        plain("image", 1150, 5, 120, 50),
        visual("card", 10, 70, 200, 100, [(s, "Sales")], [("Sales.Total Sales", mea(s, "Total Sales"))], {"Values": [{"queryRef": "Sales.Total Sales"}]}),
        visual("card", 220, 70, 200, 100, [(s, "Sales")], [("Sum(Sales.Qty)", agg(s, "Qty", 0))], {"Values": [{"queryRef": "Sum(Sales.Qty)"}]}, with_query=False),
        visual("slicer", 430, 70, 200, 100, [(s, "Sales")], [("Sales.Region", col(s, "Region"))], {"Values": [{"queryRef": "Sales.Region", "active": True}]}),
        visual("columnChart", 10, 180, 600, 260, [(c, "Calendar")] + [(s, "Sales")], [("Calendar.Year", col(c, "Year")), ("Sales.Total Sales", mea(s, "Total Sales"))], {"Category": [{"queryRef": "Calendar.Year", "active": True}], "Y": [{"queryRef": "Sales.Total Sales"}]}),
        visual("clusteredColumnChart", 620, 180, 600, 260, [(p, "Product"), (s, "Sales")], [("Product.Category", col(p, "Category")), ("Sales.Region", col(s, "Region")), ("Sales.Total Sales", mea(s, "Total Sales"))], {"Category": [{"queryRef": "Product.Category", "active": True}], "Series": [{"queryRef": "Sales.Region"}], "Y": [{"queryRef": "Sales.Total Sales"}]}),
        visual("pieChart", 10, 450, 300, 260, [(s, "Sales")], [("Sales.Region", col(s, "Region")), ("Sum(Sales.Amount)", agg(s, "Amount", 0))], {"Category": [{"queryRef": "Sales.Region", "active": True}], "Y": [{"queryRef": "Sum(Sales.Amount)"}]}),
        visual("tableEx", 320, 450, 450, 260, [(p, "Product"), (s, "Sales")], [("Product.ProductName", col(p, "ProductName")), ("Sales.Total Sales", mea(s, "Total Sales"))], {"Values": [{"queryRef": "Product.ProductName"}, {"queryRef": "Sales.Total Sales"}]}),
        visual("clusteredColumnChart", 780, 450, 490, 260, [(s, "Sales")], [("Sales.OrderDate.Variation.Date Hierarchy.Year", hl(s, "OrderDate", "Year")), ("Sales.OrderDate.Variation.Date Hierarchy.Month", hl(s, "OrderDate", "Month")), ("Sum(Sales.Amount)", agg(s, "Amount", 0))], {"Category": [{"queryRef": "Sales.OrderDate.Variation.Date Hierarchy.Year", "active": True}, {"queryRef": "Sales.OrderDate.Variation.Date Hierarchy.Month"}], "Y": [{"queryRef": "Sum(Sales.Amount)"}]}, extra={"objects": {"dataPoint": [{"selector": {"data": [{"scopeId": {}}]}, "properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": "'#FF0000'"}}}}}}}]}}),
    ]
    page2 = [  # grouped visuals
        plain("group", 0, 0, 600, 400, {}),
        visual("barChart", 10, 10, 580, 380, [(p, "Product"), (s, "Sales")], [("Product.ProductName", col(p, "ProductName")), ("Sales.Total Sales", mea(s, "Total Sales"))], {"Category": [{"queryRef": "Product.ProductName", "active": True}], "Y": [{"queryRef": "Sales.Total Sales"}]}),
    ]
    g = json.loads(page2[0]["config"]); g["singleVisualGroup"] = {"displayName": "Group 1", "groupMode": 0}; page2[0]["config"] = J(g)
    b = json.loads(page2[1]["config"]); b["parentGroupName"] = g["name"]; page2[1]["config"] = J(b)
    page4 = [
        plain("shape", 0, 0, 700, 500),
        visual("lineChart", 20, 20, 660, 460, [(p, "Product"), (s, "Sales")], [("Product.Category", col(p, "Category")), ("Sales.Margin %", mea(s, "Margin %"))], {"Category": [{"queryRef": "Product.Category", "active": True}], "Y": [{"queryRef": "Sales.Margin %"}]}),
        plain("PBI_CV_ABC123", 720, 20, 500, 400),
    ]
    tooltip = [visual("card", 0, 0, 300, 200, [(s, "Sales")], [("Sales.Total Sales", mea(s, "Total Sales"))], {"Values": [{"queryRef": "Sales.Total Sales"}]})]
    sections = [section("Overview", page1), section("Grouped", page2), section("Empty", []), section("Decor", page4), section("Tooltip", tooltip, 320, 240)]
    for i, sec in enumerate(sections): sec["ordinal"] = i
    report_cfg = {"version": "5.43", "activeSectionIndex": 0}
    if bookmarks: report_cfg["bookmarks"] = [{"name": "Bookmark1", "displayName": "B1", "explorationState": {}}]
    layout = {"id": 0, "resourcePackages": [], "sections": sections, "config": J(report_cfg), "layoutOptimization": 0}
    tables = [
        {"name": "Sales", "columns": [{"name": "OrderDate", "dataType": "dateTime"}, {"name": "Amount", "dataType": "double", "summarizeBy": "sum"}, {"name": "Qty", "dataType": "int64"}, {"name": "ProductKey", "dataType": "int64", "summarizeBy": "none", "isHidden": True}, {"name": "Region", "dataType": "string"}, {"name": "IsReturn", "dataType": "boolean"}, {"name": "CustomerID", "dataType": "string"}, {"name": "RowNumber-2662979B", "dataType": "int64", "type": "rowNumber", "isHidden": True}],
         "measures": [{"name": "Total Sales", "expression": "SUM(Sales[Amount])"}, {"name": "Margin %", "expression": "secret"}]},
        {"name": "Product", "columns": [{"name": "ProductKey", "dataType": "int64", "summarizeBy": "none"}, {"name": "ProductName", "dataType": "string"}, {"name": "Category", "dataType": "string"}]},
        {"name": "Calendar", "columns": [{"name": "Date", "dataType": "dateTime"}, {"name": "Year", "dataType": "int64", "summarizeBy": "none"}, {"name": "MonthName", "dataType": "string", "sortByColumn": "MonthNo"}, {"name": "MonthNo", "dataType": "int64", "isHidden": True}]},
        {"name": "LocalDateTable_abc", "isHidden": True, "columns": [{"name": "Date", "dataType": "dateTime"}]},
        {"name": "Unrelated", "columns": [{"name": "Note", "dataType": "string"}, {"name": "Score", "dataType": "double"}]},
    ]
    if only_measures:
        tables = [{"name": "M", "columns": [], "measures": [{"name": "KPI A", "expression": "1"}, {"name": "KPI B", "expression": "2"}]}]
    model = {"name": "x", "compatibilityLevel": 1550, "model": {"culture": "en-US", "tables": tables,
             "relationships": [{"name": "r1", "fromTable": "Sales", "fromColumn": "ProductKey", "toTable": "Product", "toColumn": "ProductKey"},
                               {"name": "r2", "fromTable": "Sales", "fromColumn": "OrderDate", "toTable": "Calendar", "toColumn": "Date"}]}}
    ct = '﻿<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="json" ContentType="" /><Override PartName="/Version" ContentType="" /><Override PartName="/DataModelSchema" ContentType="" /><Override PartName="/Report/Layout" ContentType="" /><Override PartName="/SecurityBindings" ContentType="" /></Types>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Version", "1.28".encode("utf-16-le"))
        z.writestr("[Content_Types].xml", ct.encode("utf-8"))
        z.writestr("DataModelSchema", J(model).encode("utf-16-le"))
        z.writestr("Report/Layout", J(layout).encode("utf-16-le"))
        z.writestr("SecurityBindings", b"\x01\x02")
if __name__ == "__main__":
    build(sys.argv[1], bookmarks="--bookmarks" in sys.argv, only_measures="--measures" in sys.argv)
