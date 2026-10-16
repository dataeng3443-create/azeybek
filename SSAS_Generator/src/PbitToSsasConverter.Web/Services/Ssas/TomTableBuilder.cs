using Microsoft.AnalysisServices.Tabular;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Intermediate;
using PbitToSsasConverter.Web.Services.Pbit;

namespace PbitToSsasConverter.Web.Services.Ssas;

public sealed class TomTableBuilder(TomMetadataMapper mapper, TomPartitionBuilder partitions)
{
    public Table Build(NormalizedTable source, Database db, ConversionOptions options, List<ConversionWarning> warnings)
    {
        var table = new Table { Name = source.Name };
        db.Model.Tables.Add(table);
        mapper.Apply(table, source.Properties, source.Name, options.CompatibilityLevel, options, warnings);
        foreach (var column in source.Columns)
        {
            Column? target = column.Kind.ToLowerInvariant() switch
            {
                "data" => new DataColumn(), "calculated" => new CalculatedColumn { Expression = column.Expression },
                "calculatedtablecolumn" => new CalculatedTableColumn(), _ => null
            };
            if (target is null) { TomMetadataMapper.Warn(warnings, "COLUMN_KIND", source.Name + "." + column.Name, "Unsupported column kind; column omitted."); continue; }
            target.Name = column.Name;
            var props = MetadataNormalizer.CopyExcept(column.Properties, "dataType");
            var type = MetadataNormalizer.Text(column.Properties, "dataType") ?? "automatic";
            if (!Enum.TryParse<DataType>(type, true, out var dataType) || !Enum.IsDefined(dataType))
                throw new ConversionException("UNSUPPORTED_DATA_TYPE", $"Unsupported column data type '{type}'. A safe model cannot be generated without this mapping.");
            target.DataType = dataType;
            mapper.Apply(target, props, source.Name + "." + column.Name, options.CompatibilityLevel, options, warnings);
            table.Columns.Add(target);
        }
        foreach (var measure in source.Measures)
        {
            var target = new Measure { Name = measure.Name, Expression = measure.Expression };
            mapper.Apply(target, MetadataNormalizer.CopyExcept(measure.Properties, "formatStringDefinition"), source.Name + "." + measure.Name, options.CompatibilityLevel, options, warnings);
            if (measure.Properties["formatStringDefinition"] is System.Text.Json.Nodes.JsonObject format)
            {
                if (options.CompatibilityLevel >= 1600) target.FormatStringDefinition = new FormatStringDefinition { Expression = MetadataNormalizer.Expression(format["expression"]) };
                else TomMetadataMapper.Warn(warnings, "COMPATIBILITY", measure.Name, $"Dynamic measure format strings cannot be represented at compatibility level {options.CompatibilityLevel}.");
            }
            table.Measures.Add(target);
        }
        foreach (var partition in source.Partitions)
        {
            var target = partitions.Build(partition, db, source.Name + "." + partition.Name, options, warnings);
            if (target is not null) table.Partitions.Add(target);
        }
        if (source.Partitions.Select(p => p.Mode).Distinct(StringComparer.OrdinalIgnoreCase).Count() > 1)
            TomMetadataMapper.Warn(warnings, "HYBRID_TABLE", source.Name, "Hybrid partition modes were detected; deployment and refresh behavior must be reviewed on the target SSAS server.");
        if (source.CalculationGroup is not null)
        {
            if (options.CompatibilityLevel < 1500) TomMetadataMapper.Warn(warnings, "COMPATIBILITY", source.Name, $"Calculation groups cannot be represented at compatibility level {options.CompatibilityLevel}.");
            else
            {
                table.CalculationGroup = new CalculationGroup();
                mapper.Apply(table.CalculationGroup, MetadataNormalizer.CopyExcept(source.CalculationGroup, "calculationItems"), source.Name, options.CompatibilityLevel, options, warnings);
                foreach (var item in MetadataNormalizer.Objects(source.CalculationGroup, "calculationItems"))
                {
                    var target = new CalculationItem { Name = MetadataNormalizer.Name(item), Expression = MetadataNormalizer.Expression(item["expression"]) };
                    mapper.Apply(target, MetadataNormalizer.CopyExcept(item, "name", "expression", "formatStringDefinition"), source.Name + "." + target.Name, options.CompatibilityLevel, options, warnings);
                    if (item["formatStringDefinition"] is System.Text.Json.Nodes.JsonObject f)
                        target.FormatStringDefinition = new FormatStringDefinition { Expression = MetadataNormalizer.Expression(f["expression"]) };
                    table.CalculationGroup.CalculationItems.Add(target);
                }
            }
        }
        return table;
    }
    public void Resolve(NormalizedTable source, Table target, ConversionOptions options, List<ConversionWarning> warnings)
    {
        foreach (var c in source.Columns.Where(c => c.SortByColumn is not null))
        {
            var column = target.Columns.Find(c.Name);
            var sort = target.Columns.Find(c.SortByColumn!);
            if (column is null || sort is null) TomMetadataMapper.Warn(warnings, "SORT_REFERENCE", source.Name + "." + c.Name, "SortByColumn references an unavailable column and was omitted.");
            else column.SortByColumn = sort;
        }
        foreach (var h in source.Hierarchies)
        {
            if (h.Levels.Any(l => target.Columns.Find(l.Column) is null))
            { TomMetadataMapper.Warn(warnings, "HIERARCHY_REFERENCE", source.Name + "." + h.Name, "Hierarchy contains an unavailable column; hierarchy omitted."); continue; }
            var hierarchy = new Hierarchy { Name = h.Name };
            mapper.Apply(hierarchy, h.Properties, source.Name + "." + h.Name, options.CompatibilityLevel, options, warnings);
            foreach (var level in h.Levels.OrderBy(l => l.Ordinal))
            {
                var targetLevel = new Level { Name = level.Name, Column = target.Columns[level.Column], Ordinal = level.Ordinal };
                mapper.Apply(targetLevel, level.Properties, source.Name + "." + level.Name, options.CompatibilityLevel, options, warnings);
                hierarchy.Levels.Add(targetLevel);
            }
            target.Hierarchies.Add(hierarchy);
        }
    }
}
