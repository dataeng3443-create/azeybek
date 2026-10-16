using Microsoft.AnalysisServices.Tabular;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Intermediate;
using PbitToSsasConverter.Web.Services.Pbit;

namespace PbitToSsasConverter.Web.Services.Ssas;

public sealed class TomDataSourceBuilder(TomMetadataMapper mapper)
{
    public DataSource? Build(NormalizedDataSource source, ConversionOptions options, List<ConversionWarning> warnings)
    {
        DataSource target;
        var properties = source.Properties;
        if (source.Kind.Equals("structured", StringComparison.OrdinalIgnoreCase))
        {
            if (options.CompatibilityLevel < 1400) { TomMetadataMapper.Warn(warnings, "COMPATIBILITY", source.Name, "Structured data sources require compatibility level 1400 or higher."); return null; }
            var structured = new StructuredDataSource { Name = source.Name };
            if (properties["connectionDetails"] is System.Text.Json.Nodes.JsonObject connection)
                structured.ConnectionDetails = new ConnectionDetails(connection.ToJsonString());
            target = structured;
            properties = MetadataNormalizer.CopyExcept(properties, "connectionDetails");
        }
        else if (source.Kind.Equals("provider", StringComparison.OrdinalIgnoreCase)) target = new ProviderDataSource { Name = source.Name };
        else { TomMetadataMapper.Warn(warnings, "DATA_SOURCE_KIND", source.Name, "Unsupported data source kind; no replacement connection was generated."); return null; }
        mapper.Apply(target, properties, source.Name, options.CompatibilityLevel, options, warnings);
        TomMetadataMapper.Warn(warnings, "CREDENTIALS_REQUIRED", source.Name, "Credentials must be configured after deployment.");
        return target;
    }
}
