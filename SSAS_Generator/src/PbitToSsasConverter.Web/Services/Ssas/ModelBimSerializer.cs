using System.Text;
using System.Text.Json;
using Microsoft.AnalysisServices;
using Microsoft.AnalysisServices.Tabular;
using TomJson = Microsoft.AnalysisServices.Tabular.JsonSerializer;
using Database = Microsoft.AnalysisServices.Tabular.Database;

namespace PbitToSsasConverter.Web.Services.Ssas;

public sealed class ModelBimSerializer(TomValidator validator)
{
    public byte[] SerializeAndValidate(Database database)
    {
        validator.Validate(database);
        var json = TomJson.SerializeDatabase(database, new SerializeOptions { IgnoreTimestamps = true, SplitMultilineStrings = true, IncludeRestrictedInformation = false });
        using var document = JsonDocument.Parse(json);
        // Formatting only; the JSON schema and values are produced by TOM.
        var bytes = System.Text.Json.JsonSerializer.SerializeToUtf8Bytes(document.RootElement, new JsonSerializerOptions { WriteIndented = true });
        using var roundTrip = TomJson.DeserializeDatabase(Encoding.UTF8.GetString(bytes), mode: CompatibilityMode.AnalysisServices);
        validator.Validate(roundTrip);
        return bytes;
    }
}
