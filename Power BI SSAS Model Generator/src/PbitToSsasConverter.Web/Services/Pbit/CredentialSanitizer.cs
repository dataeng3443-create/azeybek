using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using PbitToSsasConverter.Web.Models.Conversion;

namespace PbitToSsasConverter.Web.Services.Pbit;

public sealed partial class CredentialSanitizer
{
    [GeneratedRegex(@"(?i)(\b(?:password|pwd|access[_-]?token|refresh[_-]?token|client[_-]?secret|api[_-]?key|accountkey|sharedaccesssignature|authorization)[""']?\s*[=:]\s*)(""(?:[^""]|"""")*""|'[^']*'|[^;\s,\}\]]+)", RegexOptions.CultureInvariant, 1000)]
    private static partial Regex SecretAssignment();
    [GeneratedRegex(@"(?i)(https?://)[^\s/:""']+:[^\s/@""']+@", RegexOptions.CultureInvariant, 1000)]
    private static partial Regex UrlCredential();
    [GeneratedRegex(@"(?i)([?&](?:sig|token|key|code|api_key|access_token)=)[^&\s""']+", RegexOptions.CultureInvariant, 1000)]
    private static partial Regex UrlSecret();
    private static readonly HashSet<string> SecretKeys = new(StringComparer.OrdinalIgnoreCase)
    { "password", "pwd", "credential", "credentials", "accessToken", "refreshToken", "clientSecret", "apiKey", "accountKey", "sharedAccessSignature", "authorization" };

    public void Sanitize(JsonNode node, List<ConversionWarning> warnings, string path = "Model")
    {
        if (node is JsonObject obj)
        {
            foreach (var pair in obj.ToList())
            {
                if (SecretKeys.Contains(pair.Key.Replace("_", "").Replace("-", "")))
                { obj.Remove(pair.Key); Warn(warnings, path); continue; }
                if (pair.Value is JsonValue v && v.TryGetValue<string>(out var value))
                {
                    var redacted = Redact(value);
                    if (redacted != value) { obj[pair.Key] = redacted; Warn(warnings, path); }
                }
                else if (pair.Value is not null) Sanitize(pair.Value, warnings, path + "." + pair.Key);
            }
        }
        else if (node is JsonArray array)
            for (var i = 0; i < array.Count; i++)
            {
                if (array[i] is JsonValue v && v.TryGetValue<string>(out var value))
                { var redacted = Redact(value); if (redacted != value) { array[i] = redacted; Warn(warnings, path); } }
                else if (array[i] is JsonNode child) Sanitize(child, warnings, path);
            }
    }
    public static string Redact(string text) => UrlSecret().Replace(UrlCredential().Replace(SecretAssignment().Replace(text, "$1\"[REDACTED]\""), "$1[REDACTED]@"), "$1[REDACTED]");
    private static void Warn(List<ConversionWarning> warnings, string path)
    {
        if (!warnings.Any(w => w.Code == "CREDENTIALS_REMOVED" && w.Object == path))
            warnings.Add(new("CREDENTIALS_REMOVED", path, "Credential material was removed. Credentials must be configured after deployment; review redacted source expressions."));
    }
}
