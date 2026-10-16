using System.Text.Json.Nodes;
using Microsoft.Extensions.Options;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Pbit;

namespace PbitToSsasConverter.Web.Services.Pbit.Strategies;

public sealed class JsonModelSchemaExtractionStrategy(IOptions<ConversionLimits> limits) : IPbitModelExtractionStrategy
{
    public bool CanHandle(PbitPackageContext context) => context.Artifacts.Any(a => a.Kind == "json");
    public async Task<ExtractionResult> ExtractAsync(PbitPackageContext context, CancellationToken cancellationToken)
    {
        var models = new List<ExtractedModel>();
        var warnings = new List<ConversionWarning>();
        long inspectedBytes = 0;
        foreach (var artifact in context.Artifacts.Where(a => a.Kind == "json"))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (artifact.Length > limits.Value.MaxArtifactBytes || artifact.Length > limits.Value.MaxTotalMetadataBytes - inspectedBytes)
            {
                warnings.Add(new("ARTIFACT_LIMIT", artifact.EntryName, "Metadata artifact exceeds the per-file or aggregate parsing limit."));
                continue;
            }
            inspectedBytes += artifact.Length;
            try
            {
                var bytes = await File.ReadAllBytesAsync(artifact.Path, cancellationToken);
                var text = PbitPackageInspector.DetectEncoding(bytes).GetString(bytes).TrimStart('\uFEFF');
                var root = JsonNode.Parse(text, documentOptions: new() { MaxDepth = 128 });
                foreach (var schema in FindSchemas(root, 0))
                    models.Add(new(schema, artifact.EntryName, schema["tables"] is JsonArray ? 100 : 10));
            }
            catch (System.Text.Json.JsonException) { warnings.Add(new("METADATA_PARSE", artifact.EntryName, "A JSON artifact could not be parsed; other extraction paths will be tried.")); }
            catch (System.Text.DecoderFallbackException) { warnings.Add(new("METADATA_ENCODING", artifact.EntryName, "The metadata text encoding is unsupported.")); }
            catch (Exception ex) when (ex is ArgumentException or InvalidOperationException)
            { warnings.Add(new("METADATA_STRUCTURE", artifact.EntryName, "This artifact has an unsupported JSON structure; other artifacts will be tried.")); }
        }
        return new(models, warnings);
    }
    private static IEnumerable<JsonObject> FindSchemas(JsonNode? node, int depth)
    {
        if (depth > 5) yield break;
        if (node is JsonObject obj)
        {
            // Semantic structure, not the filename, determines whether this is a model.
            if (obj["tables"] is JsonArray tables && tables.All(t => t is JsonObject && t["name"] is JsonValue &&
                (t["columns"] is JsonArray || t["measures"] is JsonArray || t["partitions"] is JsonArray || t["calculationGroup"] is JsonObject)))
            { yield return (JsonObject)obj.DeepClone(); yield break; }
            if (obj["expressions"] is JsonArray || obj["dataSources"] is JsonArray)
                yield return (JsonObject)obj.DeepClone();
            foreach (var key in new[] { "model", "database", "schema", "semanticModel", "Model", "ModelSchema" })
                if (obj[key] is JsonNode child)
                    foreach (var model in FindSchemas(child, depth + 1)) yield return model;
        }
    }
}
