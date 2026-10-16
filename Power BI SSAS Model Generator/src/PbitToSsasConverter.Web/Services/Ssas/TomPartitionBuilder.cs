using System.Text.RegularExpressions;
using Microsoft.AnalysisServices.Tabular;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Intermediate;

namespace PbitToSsasConverter.Web.Services.Ssas;

public sealed partial class TomPartitionBuilder(TomMetadataMapper mapper)
{
    [GeneratedRegex("(?:File|Folder)\\.Contents\\(\\s*\"((?:[^\"]|\"\")*)\"", RegexOptions.CultureInvariant, 1000)]
    private static partial Regex FilePath();
    [GeneratedRegex(@"\b([A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*)\s*\(", RegexOptions.CultureInvariant, 1000)]
    private static partial Regex Functions();
    public Partition? Build(NormalizedPartition source, Database database, string path, ConversionOptions options, List<ConversionWarning> warnings)
    {
        if (source.Mode.Equals("directLake", StringComparison.OrdinalIgnoreCase))
        { TomMetadataMapper.Warn(warnings, "DIRECT_LAKE", path, "Direct Lake is a Power BI/Fabric specific storage mode and cannot be deployed directly to SQL Server Analysis Services."); return null; }
        if (!Enum.TryParse<ModeType>(source.Mode, true, out var mode) || mode is not (ModeType.Import or ModeType.DirectQuery or ModeType.Default))
        { TomMetadataMapper.Warn(warnings, "STORAGE_MODE", path, "Unsupported storage mode; the partition was omitted."); return null; }
        if (source.Kind.Equals("calculationGroup", StringComparison.OrdinalIgnoreCase))
        {
            if (options.CompatibilityLevel < 1500) { TomMetadataMapper.Warn(warnings, "COMPATIBILITY", path, "Calculation group partitions require compatibility level 1500 or higher."); return null; }
            return new Partition { Name = source.Name, Mode = mode, Source = new CalculationGroupSource() };
        }
        if (string.IsNullOrWhiteSpace(source.Expression))
        { TomMetadataMapper.Warn(warnings, "MISSING_EXPRESSION", path, "Partition metadata was detected but its source expression could not be extracted."); return null; }
        PartitionSource partitionSource;
        switch (source.Kind.ToLowerInvariant())
        {
            case "m":
                if (!options.PreservePowerQueryExpressions) { TomMetadataMapper.Warn(warnings, "M_EXCLUDED", path, "Power Query partition was excluded by conversion options."); return null; }
                if (options.CompatibilityLevel < 1400) { TomMetadataMapper.Warn(warnings, "COMPATIBILITY", path, $"M partitions cannot be represented at compatibility level {options.CompatibilityLevel}."); return null; }
                partitionSource = new MPartitionSource { Expression = source.Expression };
                InspectExpression(source.Expression, path, warnings);
                break;
            case "calculated": partitionSource = new CalculatedPartitionSource { Expression = source.Expression }; break;
            case "query":
                var dataSource = database.Model.DataSources.Find(source.DataSource ?? "");
                if (dataSource is null) { TomMetadataMapper.Warn(warnings, "MISSING_DATA_SOURCE", path, "Query partition references an unavailable data source."); return null; }
                partitionSource = new QueryPartitionSource { Query = source.Expression, DataSource = dataSource }; break;
            default: TomMetadataMapper.Warn(warnings, "UNSUPPORTED_PARTITION", path, $"Partition source '{source.Kind}' is unsupported. No substitute expression was generated."); return null;
        }
        var partition = new Partition { Name = source.Name, Mode = mode, Source = partitionSource };
        mapper.Apply(partition, source.Properties, path, options.CompatibilityLevel, options, warnings);
        mapper.Apply(partitionSource, source.SourceProperties, path + ".source", options.CompatibilityLevel, options, warnings);
        return partition;
    }
    public static void InspectExpression(string expression, string path, List<ConversionWarning> warnings)
    {
        foreach (Match match in FilePath().Matches(expression)) TomMetadataMapper.Warn(warnings, "EXTERNAL_FILE", path,
            $"External file dependency detected: {match.Groups[1].Value}. The file path must be accessible by the SSAS service account after deployment.");
        var connectors = Functions().Matches(expression).Select(m => m.Groups[1].Value)
            .Where(n => !n.StartsWith("Table.") && !n.StartsWith("List.") && !n.StartsWith("Text.") && !n.StartsWith("Record.") && !n.StartsWith("Date.") && !n.StartsWith("Number.")).Distinct().ToArray();
        if (connectors.Length > 0) TomMetadataMapper.Warn(warnings, "CONNECTOR_REVIEW", path, "M expression preserved. Connector availability, credentials and network access must be verified on the target SSAS server.");
        if (expression.Contains("powerbi://", StringComparison.OrdinalIgnoreCase) || expression.Contains("PowerBI.Dataflows", StringComparison.OrdinalIgnoreCase) || expression.Contains("AnalysisServices.Database", StringComparison.OrdinalIgnoreCase))
            TomMetadataMapper.Warn(warnings, "REMOTE_MODEL", path, "Remote semantic model or Power BI service dependency detected. The original expression was retained and requires manual deployment review.");
    }
}
