using System.Globalization;
using System.Reflection;
using System.Text.Json.Nodes;
using Microsoft.AnalysisServices.Tabular;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Services.Pbit;

namespace PbitToSsasConverter.Web.Services.Ssas;

public sealed class TomMetadataMapper
{
    private static readonly HashSet<string> PowerBiOnly = new(StringComparer.OrdinalIgnoreCase)
    { "queryGroups", "refreshPolicy", "sourceLineageTag", "changedProperties", "PBI_RemovedChildren", "visualCalculations", "bindingInfo", "remoteSource", "sourceQueryCulture", "defaultPowerBIDataSourceVersion" };
    public void Apply(object target, JsonObject properties, string path, int compatibility, ConversionOptions options, List<ConversionWarning> warnings)
    {
        foreach (var (key, value) in properties)
        {
            if (value is null) continue;
            if (key == "annotations") { Annotations(target, value, path, options, warnings); continue; }
            if (key == "lineageTag" && compatibility < 1540) { Warn(warnings, "COMPATIBILITY", path, $"lineageTag cannot be represented at compatibility level {compatibility}."); continue; }
            if (PowerBiOnly.Contains(key)) { Warn(warnings, "POWER_BI_FEATURE", path, $"Power BI metadata '{key}' cannot be deployed directly to SQL Server Analysis Services and was omitted."); continue; }
            var property = target.GetType().GetProperty(key, BindingFlags.Instance | BindingFlags.Public | BindingFlags.IgnoreCase);
            if (property?.CanWrite != true || value is not JsonValue scalar)
            {
                if (target is ModelRole or TablePermission or ColumnPermission)
                    throw new ConversionException("SECURITY_MAPPING", $"Security metadata '{key}' could not be represented. Download is blocked.");
                Warn(warnings, "UNSUPPORTED_METADATA", path, $"Metadata '{key}' could not be represented on {target.GetType().Name}."); continue;
            }
            try
            {
                var type = Nullable.GetUnderlyingType(property.PropertyType) ?? property.PropertyType;
                object? converted;
                if (type == typeof(string)) converted = scalar.GetValue<string>();
                else if (type.IsEnum)
                {
                    var name = scalar.ToString();
                    if (key == "crossFilteringBehavior") name = name.Equals("single", StringComparison.OrdinalIgnoreCase) ? "OneDirection" : name.Equals("both", StringComparison.OrdinalIgnoreCase) ? "BothDirections" : name;
                    if (!Enum.TryParse(type, name, true, out converted) || !Enum.IsDefined(type, converted!)) throw new ArgumentException("Unknown enum value");
                }
                else if (type == typeof(bool) || type == typeof(int) || type == typeof(long) || type == typeof(double)) converted = Convert.ChangeType(scalar.ToString(), type, CultureInfo.InvariantCulture);
                else { Warn(warnings, "UNSUPPORTED_METADATA", path, $"Metadata '{key}' requires a specialized mapping and was omitted."); continue; }
                property.SetValue(target, converted);
            }
            catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or FormatException or TargetInvocationException or OverflowException)
            {
                // Dropping a security restriction must never silently widen access.
                if (target is ModelRole or TablePermission or ColumnPermission || key.Contains("permission", StringComparison.OrdinalIgnoreCase) || key.Contains("security", StringComparison.OrdinalIgnoreCase))
                    throw new ConversionException("SECURITY_MAPPING", "Security metadata could not be preserved. Download is blocked.", ex);
                if (key is "fromCardinality" or "toCardinality" or "isActive" or "crossFilteringBehavior" or "defaultMode")
                    throw new ConversionException("STRUCTURAL_METADATA", $"Model property '{key}' could not be preserved safely.", ex);
                Warn(warnings, "PROPERTY_CONVERSION", path, $"Metadata '{key}' could not be applied at compatibility level {compatibility}.");
            }
        }
    }
    private static void Annotations(object target, JsonNode value, string path, ConversionOptions options, List<ConversionWarning> warnings)
    {
        if (!options.PreserveAnnotations) { Warn(warnings, "ANNOTATIONS_EXCLUDED", path, "Annotations were excluded by conversion options."); return; }
        if (target.GetType().GetProperty("Annotations")?.GetValue(target) is not IEnumerable<Annotation> annotations || value is not JsonArray array)
        { Warn(warnings, "UNSUPPORTED_METADATA", path, "Annotations could not be represented."); return; }
        foreach (var a in array.OfType<JsonObject>())
        {
            var name = MetadataNormalizer.Name(a);
            if (string.IsNullOrWhiteSpace(name)) { Warn(warnings, "ANNOTATION_INVALID", path, "An annotation has no name."); continue; }
            if (annotations.Any(x => x.Name.Equals(name, StringComparison.OrdinalIgnoreCase))) { Warn(warnings, "ANNOTATION_DUPLICATE", path, "A duplicate annotation was omitted."); continue; }
            annotations.GetType().GetMethod("Add", [typeof(Annotation)])!.Invoke(annotations, [new Annotation { Name = name, Value = a["value"] is JsonValue v ? v.ToString() : a["value"]?.ToJsonString() ?? "" }]);
            if (name.StartsWith("PBI_", StringComparison.OrdinalIgnoreCase) || name.Contains("ParameterMetadata", StringComparison.OrdinalIgnoreCase))
                Warn(warnings, "POWER_BI_ANNOTATION", path, $"Annotation '{name}' was preserved, but its Power BI behavior is not guaranteed in SSAS.");
        }
    }
    public static void Warn(List<ConversionWarning> warnings, string code, string path, string message) => warnings.Add(new(code, path, message));
}
