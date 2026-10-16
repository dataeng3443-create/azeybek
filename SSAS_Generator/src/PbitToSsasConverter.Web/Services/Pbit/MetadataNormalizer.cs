using System.Text.Json.Nodes;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Intermediate;

namespace PbitToSsasConverter.Web.Services.Pbit;

public sealed class MetadataNormalizer(CredentialSanitizer sanitizer)
{
    public NormalizedPowerBiModel Normalize(JsonObject schema, IProgress<ConversionProgress>? progress, CancellationToken ct)
    {
        var model = new NormalizedPowerBiModel { Name = Text(schema, "name") ?? "SemanticModel", Culture = Text(schema, "culture") ?? "en-US" };
        var clean = (JsonObject)schema.DeepClone();
        sanitizer.Sanitize(clean, model.Warnings);
        model.Properties = CopyExcept(clean, "name", "culture", "tables", "relationships", "dataSources", "roles", "perspectives", "expressions");
        foreach (var table in Objects(clean, "tables"))
        {
            ct.ThrowIfCancellationRequested();
            var normalized = new NormalizedTable { Name = Name(table), Properties = CopyExcept(table, "name", "columns", "measures", "partitions", "hierarchies", "calculationGroup"), CalculationGroup = table["calculationGroup"]?.DeepClone() as JsonObject };
            foreach (var c in Objects(table, "columns")) normalized.Columns.Add(new()
            {
                Name = Name(c), Kind = Text(c, "type") ?? (c["expression"] is null ? "data" : "calculated"),
                Expression = Expression(c["expression"]), SortByColumn = Text(c, "sortByColumn"),
                Properties = CopyExcept(c, "name", "type", "expression", "sortByColumn")
            });
            foreach (var m in Objects(table, "measures")) normalized.Measures.Add(new()
            { Name = Name(m), Expression = Expression(m["expression"]), Properties = CopyExcept(m, "name", "expression") });
            foreach (var p in Objects(table, "partitions"))
            {
                var source = p["source"] as JsonObject ?? new();
                normalized.Partitions.Add(new()
                {
                    Name = Name(p), Kind = Text(source, "type") ?? "", Mode = Text(p, "mode") ?? Text(clean, "defaultMode") ?? "import",
                    Expression = Expression(source["expression"] ?? source["query"]), DataSource = Text(source, "dataSource"),
                    Properties = CopyExcept(p, "name", "source", "mode"), SourceProperties = CopyExcept(source, "type", "expression", "query", "dataSource")
                });
            }
            foreach (var h in Objects(table, "hierarchies"))
            {
                var hierarchy = new NormalizedHierarchy { Name = Name(h), Properties = CopyExcept(h, "name", "levels") };
                var i = 0;
                foreach (var level in Objects(h, "levels")) hierarchy.Levels.Add(new()
                { Name = Name(level), Column = Text(level, "column") ?? "", Ordinal = level["ordinal"]?.GetValue<int>() ?? i++, Properties = CopyExcept(level, "name", "column", "ordinal") });
                normalized.Hierarchies.Add(hierarchy);
            }
            model.Tables.Add(normalized);
            if (normalized.Name.StartsWith("LocalDateTable_", StringComparison.OrdinalIgnoreCase) || normalized.Name.StartsWith("DateTableTemplate_", StringComparison.OrdinalIgnoreCase))
                model.Warnings.Add(new("AUTO_DATE_TIME", normalized.Name, "Power BI automatic date/time table was retained. Review its dependencies before deployment."));
        }
        progress?.Report(new(30, "tables", "Tables extracted"));
        progress?.Report(new(35, "columns", "Tables and columns extracted"));
        progress?.Report(new(40, "measures", "DAX measures extracted"));
        foreach (var r in Objects(clean, "relationships")) model.Relationships.Add(new()
        {
            Name = Name(r), FromTable = Text(r, "fromTable") ?? "", FromColumn = Text(r, "fromColumn") ?? "",
            ToTable = Text(r, "toTable") ?? "", ToColumn = Text(r, "toColumn") ?? "",
            Properties = CopyExcept(r, "name", "fromTable", "fromColumn", "toTable", "toColumn")
        });
        progress?.Report(new(45, "relationships", "Relationships extracted"));
        foreach (var s in Objects(clean, "dataSources")) model.DataSources.Add(new()
        { Name = Name(s), Kind = Text(s, "type") ?? "provider", Properties = CopyExcept(s, "name", "type") });
        foreach (var e in Objects(clean, "expressions")) model.Expressions.Add(new()
        { Name = Name(e), Expression = Expression(e["expression"]), Properties = CopyExcept(e, "name", "expression") });
        foreach (var r in Objects(clean, "roles")) model.Roles.Add(new()
        { Name = Name(r), Properties = CopyExcept(r, "name", "tablePermissions"), TablePermissions = r["tablePermissions"]?.DeepClone() as JsonArray ?? [] });
        foreach (var p in Objects(clean, "perspectives")) model.Perspectives.Add(new()
        { Name = Name(p), Properties = CopyExcept(p, "name", "tables"), Tables = p["tables"]?.DeepClone() as JsonArray ?? [] });
        progress?.Report(new(50, "partitions", "Power Query and partition metadata extracted"));
        progress?.Report(new(55, "sources", "Data sources extracted"));
        return model;
    }
    public static string? Expression(JsonNode? value) => value switch
    {
        JsonArray a => string.Join("\n", a.Select(x => x?.GetValue<string>() ?? "")),
        JsonValue v => v.GetValue<string>(), null => null,
        _ => throw new ConversionException("METADATA_PARSE", "An expression has an unsupported metadata representation.")
    };
    public static string? Text(JsonObject obj, string key) => obj[key]?.GetValue<string>();
    public static string Name(JsonObject obj) => Text(obj, "name") ?? "";
    public static IEnumerable<JsonObject> Objects(JsonObject obj, string key)
    {
        if (obj[key] is null) return [];
        if (obj[key] is not JsonArray array || array.Any(x => x is not JsonObject))
            throw new ConversionException("METADATA_PARSE", $"The {key} collection has an unsupported structure.");
        return array.Cast<JsonObject>();
    }
    public static JsonObject CopyExcept(JsonObject obj, params string[] excluded)
    {
        var result = new JsonObject();
        foreach (var pair in obj) if (!excluded.Contains(pair.Key)) result[pair.Key] = pair.Value?.DeepClone();
        return result;
    }
}
