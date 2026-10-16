using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AnalysisServices.Tabular;
using PbitToSsasConverter.Tests;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Services.Pbit;
using PbitToSsasConverter.Web.Services.Ssas;

namespace PbitToSsasConverter.UnitTests;

public sealed class AdvancedMetadataTests
{
    [Fact]
    public void CalculationGroupsPreserveItemsAndFormatExpressions()
    {
        var schema = ModelFixture.Schema();
        schema["tables"]!.AsArray().Add(JsonNode.Parse("""
        {"name":"Time Intelligence","columns":[{"name":"Calculation","dataType":"string","sourceColumn":"Name"}],
         "partitions":[{"name":"Time Intelligence","source":{"type":"calculationGroup"}}],
         "calculationGroup":{"precedence":10,"calculationItems":[{"name":"Current","ordinal":0,"expression":"SELECTEDMEASURE()","formatStringDefinition":{"expression":"SELECTEDMEASUREFORMATSTRING()"}}]}}
        """));
        var model = new MetadataNormalizer(new()).Normalize(schema, null, default);
        using var db = ModelFixture.Builder().Build(model, new(), default);
        var group = db.Model.Tables["Time Intelligence"].CalculationGroup;
        Assert.Equal(10, group.Precedence); Assert.Equal("SELECTEDMEASURE()", group.CalculationItems[0].Expression);
        Assert.Equal("SELECTEDMEASUREFORMATSTRING()", group.CalculationItems[0].FormatStringDefinition.Expression);
        Assert.IsType<CalculationGroupSource>(db.Model.Tables["Time Intelligence"].Partitions[0].Source);
        new ModelBimSerializer(new()).SerializeAndValidate(db);
    }
    [Fact]
    public void ProviderQuerySourceAndDirectQueryArePreservedWithoutPassword()
    {
        var schema = ModelFixture.Schema();
        schema["dataSources"] = JsonNode.Parse("""
        [{"name":"SQL","type":"provider","connectionString":"Provider=MSOLEDBSQL;Data Source=SQL01;Initial Catalog=ERP;Password=test-secret","impersonationMode":"impersonateServiceAccount"}]
        """);
        schema["tables"]![0]!["partitions"]![0] = JsonNode.Parse("""
        {"name":"Sales","mode":"directQuery","source":{"type":"query","query":"SELECT CustomerId, Amount, Label FROM dbo.Sales","dataSource":"SQL"}}
        """);
        var model = new MetadataNormalizer(new()).Normalize(schema, null, default);
        using var db = ModelFixture.Builder().Build(model, new(), default);
        var partition = db.Model.Tables["Sales"].Partitions[0];
        Assert.Equal(ModeType.DirectQuery, partition.Mode);
        Assert.Equal("SELECT CustomerId, Amount, Label FROM dbo.Sales", Assert.IsType<QueryPartitionSource>(partition.Source).Query);
        Assert.Equal("SQL", Assert.IsType<QueryPartitionSource>(partition.Source).DataSource.Name);
        var bytes = new ModelBimSerializer(new()).SerializeAndValidate(db);
        Assert.DoesNotContain("test-secret", Encoding.UTF8.GetString(bytes));
        Assert.Contains(model.Warnings, w => w.Code == "CREDENTIALS_REMOVED");
    }
    [Fact]
    public void StructuredDataSourceMetadataSurvivesTomRoundTrip()
    {
        var schema = ModelFixture.Schema();
        schema["dataSources"] = JsonNode.Parse("""
        [{"name":"StructuredSQL","type":"structured","connectionDetails":{"protocol":"tds","address":{"server":"SQL01","database":"ERP"},"authentication":null,"query":null},"credential":{"AuthenticationKind":"UsernamePassword","Password":"test-secret"}}]
        """);
        var model = new MetadataNormalizer(new()).Normalize(schema, null, default);
        using var db = ModelFixture.Builder().Build(model, new(), default);
        var source = Assert.IsType<StructuredDataSource>(db.Model.DataSources[0]);
        Assert.Contains("SQL01", source.ConnectionDetails.ToJson());
        var bytes = new ModelBimSerializer(new()).SerializeAndValidate(db);
        Assert.DoesNotContain("test-secret", Encoding.UTF8.GetString(bytes));
    }
    [Fact]
    public void ObjectLevelSecurityIsPreserved()
    {
        var schema = ModelFixture.Schema();
        var permission = schema["roles"]![0]!["tablePermissions"]![0]!;
        permission["columnPermissions"] = JsonNode.Parse("""[{"name":"Amount","metadataPermission":"none"}]""");
        using var db = ModelFixture.Builder().Build(new MetadataNormalizer(new()).Normalize(schema, null, default), new(), default);
        var column = db.Model.Roles[0].TablePermissions[0].ColumnPermissions[0];
        Assert.Equal("Amount", column.Column.Name); Assert.Equal(MetadataPermission.None, column.MetadataPermission);
        new ModelBimSerializer(new()).SerializeAndValidate(db);
    }
    [Fact]
    public void DynamicFormatAndLineageDowngradeProduceCompatibilityWarnings()
    {
        var schema = ModelFixture.Schema();
        schema["tables"]![0]!["lineageTag"] = Guid.NewGuid().ToString();
        schema["tables"]![0]!["measures"]![0]!["formatStringDefinition"] = JsonNode.Parse("""{"expression":"\"#,0.00\""}""");
        var model = new MetadataNormalizer(new()).Normalize(schema, null, default);
        using var db = ModelFixture.Builder().Build(model, new() { CompatibilityLevel = 1500 }, default);
        Assert.True(model.Warnings.Count(w => w.Code == "COMPATIBILITY") >= 2);
        new ModelBimSerializer(new()).SerializeAndValidate(db);
    }
    [Fact]
    public void SortCyclesAreRejected()
    {
        var schema = ModelFixture.Schema(); schema["tables"]![0]!["columns"]![0]!["sortByColumn"] = "Label";
        using var db = ModelFixture.Builder().Build(new MetadataNormalizer(new()).Normalize(schema, null, default), new(), default);
        Assert.Throws<ConversionException>(() => new TomValidator().Validate(db));
    }
    [Fact]
    public void UnknownSecurityPropertiesBlockOutput()
    {
        var schema = ModelFixture.Schema(); schema["roles"]![0]!["tablePermissions"]![0]!["futureSecurityRestriction"] = true;
        Assert.Throws<ConversionException>(() => ModelFixture.Builder().Build(new MetadataNormalizer(new()).Normalize(schema, null, default), new(), default));
    }
    [Fact]
    public void MultiLineExpressionsKeepWhitespace()
    {
        var schema = ModelFixture.Schema();
        schema["tables"]![0]!["measures"]![0]!["expression"] = new JsonArray("VAR x = 1", "", "  RETURN x");
        using var db = ModelFixture.Builder().Build(new MetadataNormalizer(new()).Normalize(schema, null, default), new(), default);
        Assert.Equal("VAR x = 1\n\n  RETURN x", db.Model.Tables[0].Measures[0].Expression);
    }
    [Fact]
    public void EmbeddedJsonCredentialsAndUnderscoreKeysAreRedacted()
    {
        var metadata = new JsonObject { ["api_key"] = "secret-one", ["annotation"] = "{\"password\":\"secret-two\"}" };
        var warnings = new List<ConversionWarning>(); new CredentialSanitizer().Sanitize(metadata, warnings);
        Assert.DoesNotContain("secret-one", metadata.ToJsonString()); Assert.DoesNotContain("secret-two", metadata.ToJsonString());
        Assert.NotNull(JsonNode.Parse(metadata["annotation"]!.GetValue<string>()));
    }
}
