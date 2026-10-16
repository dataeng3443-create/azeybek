using System.Text.Json.Nodes;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Intermediate;
using PbitToSsasConverter.Web.Models.Pbit;
using PbitToSsasConverter.Web.Services.Pbit.Strategies;

namespace PbitToSsasConverter.Web.Services.Pbit;

public interface IPbitModelExtractor
{
    Task<NormalizedPowerBiModel> ExtractAsync(PbitPackageContext context, IProgress<ConversionProgress>? progress, CancellationToken ct);
}
public sealed class PbitModelExtractor(IEnumerable<IPbitModelExtractionStrategy> strategies, MetadataNormalizer normalizer, ILogger<PbitModelExtractor> logger) : IPbitModelExtractor
{
    public async Task<NormalizedPowerBiModel> ExtractAsync(PbitPackageContext context, IProgress<ConversionProgress>? progress, CancellationToken ct)
    {
        var candidates = new List<ExtractedModel>();
        var warnings = new List<ConversionWarning>();
        foreach (var strategy in strategies.Where(s => s.CanHandle(context)))
        {
            try
            {
                var result = await strategy.ExtractAsync(context, ct);
                candidates.AddRange(result.Models);
                warnings.AddRange(result.Warnings);
            }
            catch (Exception ex) when (ex is not OperationCanceledException && ex is not OutOfMemoryException)
            {
                logger.LogWarning("EXTRACTION_STRATEGY_FAILED {Strategy} {ExceptionType}", strategy.GetType().Name, ex.GetType().Name);
                warnings.Add(new("EXTRACTION_STRATEGY_FAILED", strategy.GetType().Name, "An extraction strategy failed; available alternatives were tried."));
            }
        }
        var primary = candidates.OrderByDescending(c => c.Priority).FirstOrDefault(c => c.Schema["tables"] is JsonArray);
        if (primary is null) throw new ConversionException("UNSUPPORTED_EXTRACTION_PATH", "No readable semantic model schema was found. Binary-only, legacy and encrypted model metadata are unsupported; export a new PBIT with Power BI Desktop.");
        var merged = (JsonObject)primary.Schema.DeepClone();
        foreach (var candidate in candidates.Where(c => c != primary))
        {
            foreach (var key in new[] { "tables", "dataSources", "relationships", "expressions", "roles", "perspectives" })
            {
                if (candidate.Schema[key] is not JsonArray additions) continue;
                if (merged[key] is not JsonArray) merged[key] = new JsonArray();
                var target = (JsonArray)merged[key]!;
                foreach (var item in additions.OfType<JsonObject>())
                {
                    var match = target.OfType<JsonObject>().FirstOrDefault(x => string.Equals(x["name"]?.ToString(), item["name"]?.ToString(), StringComparison.OrdinalIgnoreCase));
                    if (match is null) target.Add(item.DeepClone());
                    else if (!JsonNode.DeepEquals(match, item)) warnings.Add(new("METADATA_CONFLICT", candidate.Artifact, $"Conflicting {key} metadata was found; the primary semantic schema was retained."));
                }
            }
        }
        logger.LogInformation("MODEL_SCHEMA_FOUND {JobId} {ArtifactCount}", context.JobId, candidates.Count);
        var model = normalizer.Normalize(merged, progress, ct);
        model.Warnings.AddRange(warnings);
        if (context.Artifacts.Any(a => a.EntryName.Contains("DataModel", StringComparison.OrdinalIgnoreCase) && a.Kind != "json"))
            model.Warnings.Add(new("BINARY_MODEL", "Package", "Binary model artifacts were detected. Conversion uses available semantic JSON; binary-only metadata cannot be recovered."));
        if (context.Artifacts.Any(a => a.EntryName.StartsWith("Report/", StringComparison.OrdinalIgnoreCase)))
            model.Warnings.Add(new("REPORT_OBJECTS", "Report", "Report visuals, layout and visual calculations are outside semantic model conversion.", IssueSeverity.Info));
        return model;
    }
}
