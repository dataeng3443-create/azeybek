using Microsoft.AnalysisServices.Tabular;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Intermediate;

namespace PbitToSsasConverter.Web.Services.Ssas;

public sealed class TomValidator
{
    // Supported on-premises SSAS levels. Custom input is validated against this set.
    public static readonly int[] SupportedLevels = [1200, 1400, 1500, 1600, 1700];
    public static void ValidateOptions(ConversionOptions options)
    {
        if (!SupportedLevels.Contains(options.CompatibilityLevel)) throw new ConversionException("COMPATIBILITY_LEVEL", "Choose a supported SQL Server Analysis Services level: 1200, 1400, 1500, 1600 or 1700.");
    }
    public static void ValidateNormalized(NormalizedPowerBiModel model, ConversionOptions options)
    {
        ValidateOptions(options);
        Require(!string.IsNullOrWhiteSpace(model.Name), "Database name is missing.");
        Require(model.Tables.Count > 0, "No semantic model tables were extracted.");
        Unique(model.Tables.Select(t => t.Name), "tables");
        Unique(model.DataSources.Select(t => t.Name), "data sources");
        Unique(model.Relationships.Select(t => t.Name), "relationships");
        Unique(model.Roles.Select(t => t.Name), "roles");
        Unique(model.Perspectives.Select(t => t.Name), "perspectives");
        Unique(model.Expressions.Select(t => t.Name), "expressions");
        Unique(model.Tables.SelectMany(t => t.Measures.Select(m => m.Name)), "model measures");
        foreach (var table in model.Tables)
        {
            Unique(table.Columns.Select(c => c.Name), table.Name + " columns");
            Unique(table.Partitions.Select(c => c.Name), table.Name + " partitions");
            Unique(table.Hierarchies.Select(c => c.Name), table.Name + " hierarchies");
            foreach (var h in table.Hierarchies) Unique(h.Levels.Select(l => l.Name), h.Name + " levels");
        }
    }
    public void Validate(Database db)
    {
        Require(!string.IsNullOrWhiteSpace(db.Name), "Database name is missing.");
        Require(SupportedLevels.Contains(db.CompatibilityLevel), "Compatibility level is invalid.");
        Require(db.Model is not null, "Model is missing.");
        foreach (var table in db.Model!.Tables)
        {
            Require(table.Columns.Count > 0 || table.Measures.Count > 0, $"Table '{table.Name}' has no columns or measures.");
            Require(table.Partitions.Count > 0 || table.CalculationGroup is not null, $"Table '{table.Name}' has no usable partition. Source metadata must be provided before a deployable model can be generated.");
            foreach (var column in table.Columns)
            {
                if (column is CalculatedColumn calculated) Require(!string.IsNullOrWhiteSpace(calculated.Expression), "Calculated column expression is missing.");
                if (column is DataColumn data) Require(!string.IsNullOrWhiteSpace(data.SourceColumn), "Data column sourceColumn is missing.");
                if (column.SortByColumn is not null) Require(column.SortByColumn.Table == table && column.SortByColumn != column, "SortByColumn reference is invalid.");
                var visited = new HashSet<Column>();
                for (Column? current = column; current is not null; current = current.SortByColumn) Require(visited.Add(current), "SortByColumn contains a dependency cycle.");
            }
            foreach (var measure in table.Measures) Require(!string.IsNullOrWhiteSpace(measure.Expression), "Measure expression is missing.");
            foreach (var p in table.Partitions)
            {
                Require(p.Source is not null, "Partition source is missing.");
                if (p.Source is MPartitionSource m) Require(!string.IsNullOrWhiteSpace(m.Expression), "M expression is missing.");
                if (p.Source is CalculatedPartitionSource c) Require(!string.IsNullOrWhiteSpace(c.Expression), "Calculated table expression is missing.");
                if (p.Source is QueryPartitionSource q) Require(q.DataSource is not null && db.Model.DataSources.Contains(q.DataSource.Name) && !string.IsNullOrWhiteSpace(q.Query), "Query partition data source or SQL is missing.");
            }
            foreach (var h in table.Hierarchies)
            {
                Require(h.Levels.Select(l => l.Ordinal).Distinct().Count() == h.Levels.Count, "Hierarchy level ordinals must be unique.");
                foreach (var l in h.Levels) Require(l.Column is not null && l.Column.Table == table, "Hierarchy level reference is invalid.");
            }
        }
        foreach (var r in db.Model.Relationships.OfType<SingleColumnRelationship>())
            Require(r.FromColumn?.Table?.Model == db.Model && r.ToColumn?.Table?.Model == db.Model, "Relationship reference is invalid.");
    }
    private static void Unique(IEnumerable<string> names, string collection)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var name in names) Require(!string.IsNullOrWhiteSpace(name) && seen.Add(name), $"Missing or duplicate names in {collection}.");
    }
    private static void Require(bool valid, string message) { if (!valid) throw new ConversionException("MODEL_VALIDATION", message); }
}
