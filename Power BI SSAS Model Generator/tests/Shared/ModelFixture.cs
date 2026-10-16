using System.IO.Compression;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Extensions.Options;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Services.Pbit;
using PbitToSsasConverter.Web.Services.Ssas;

namespace PbitToSsasConverter.Tests;

internal static class ModelFixture
{
    public const string SqlM = "let\n    Source = Sql.Database(\"SQLSERVER01\", \"ERP\", [Query=\"SELECT CustomerId, Amount FROM dbo.Sales\"]),\n    Result = Source\nin\n    Result";
    public const string ExcelM = "let Source = Excel.Workbook(File.Contents(\"C:\\Reports\\Sales.xlsx\")) in Source";
    public static JsonObject Schema()
    {
        var root = JsonNode.Parse("""
        {
          "name":"SalesModel", "culture":"en-US", "defaultMode":"import",
          "annotations":[{"name":"Origin","value":"Synthetic test fixture"}],
          "tables":[
            {"name":"Sales","description":"Sales table","isHidden":false,
             "columns":[
               {"name":"CustomerId","dataType":"int64","sourceColumn":"CustomerId"},
               {"name":"Amount","dataType":"decimal","sourceColumn":"Amount","formatString":"#,0.00"},
               {"name":"Label","dataType":"string","sourceColumn":"Label","sortByColumn":"CustomerId","isHidden":true},
               {"name":"DoubleAmount","type":"calculated","dataType":"decimal","expression":"Sales[Amount] * 2"}],
             "measures":[{"name":"Total Sales","expression":"SUM(Sales[Amount])","formatString":"#,0.00","displayFolder":"Revenue","isHidden":true}],
             "partitions":[{"name":"Sales","mode":"import","source":{"type":"m","expression":"replaced in fixture"}}],
             "hierarchies":[{"name":"Customer hierarchy","isHidden":true,"levels":[{"name":"Customer","ordinal":0,"column":"CustomerId"}]}]},
            {"name":"Customer","columns":[{"name":"CustomerId","dataType":"int64","sourceColumn":"CustomerId","isKey":true}],
             "partitions":[{"name":"Customer","mode":"import","source":{"type":"m","expression":"replaced in fixture"}}]},
            {"name":"Calendar","columns":[{"name":"Date","type":"calculatedTableColumn","dataType":"dateTime","sourceColumn":"[Date]"}],
             "partitions":[{"name":"Calendar","source":{"type":"calculated","expression":"CALENDAR(DATE(2020,1,1),DATE(2030,12,31))"}}]}],
          "relationships":[{"name":"SalesCustomer","fromTable":"Sales","fromColumn":"CustomerId","toTable":"Customer","toColumn":"CustomerId","fromCardinality":"many","toCardinality":"one","crossFilteringBehavior":"oneDirection","isActive":false}],
          "roles":[{"name":"RegionalManager","modelPermission":"read","tablePermissions":[{"name":"Sales","filterExpression":"Sales[CustomerId] = 1"}]}],
          "perspectives":[{"name":"SalesView","tables":[{"name":"Sales","columns":[{"name":"CustomerId"}],"measures":[{"name":"Total Sales"}],"hierarchies":[{"name":"Customer hierarchy"}]}]}],
          "expressions":[{"name":"ServerName","kind":"m","expression":"\"SQLSERVER01\""}]
        }
        """)!.AsObject();
        root["tables"]![0]!["partitions"]![0]!["source"]!["expression"] = SqlM;
        root["tables"]![1]!["partitions"]![0]!["source"]!["expression"] = ExcelM;
        return root;
    }
    public static SsasModelBuilder Builder()
    {
        var mapper = new TomMetadataMapper();
        return new(mapper, new(mapper, new(mapper)), new(mapper), new(mapper), new(mapper));
    }
    public static MemoryStream Package(JsonObject? schema = null, string entryName = "unexpected/semantic-data", Encoding? encoding = null)
    {
        var stream = new MemoryStream();
        using (var zip = new ZipArchive(stream, ZipArchiveMode.Create, true))
        {
            using var writer = new StreamWriter(zip.CreateEntry(entryName).Open(), encoding ?? Encoding.Unicode);
            writer.Write(new JsonObject { ["model"] = schema ?? Schema() }.ToJsonString());
        }
        stream.Position = 0;
        return stream;
    }
    public static IOptions<ConversionLimits> Limits(string temp) => Options.Create(new ConversionLimits { TempRoot = temp });
}
