using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.AnalysisServices;
using Microsoft.AnalysisServices.Tabular;
using PbitToSsasConverter.Tests;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Services.Conversion;
using PbitToSsasConverter.Web.Services.Pbit;
using PbitToSsasConverter.Web.Services.Ssas;
using TomJson = Microsoft.AnalysisServices.Tabular.JsonSerializer;
using DataType = Microsoft.AnalysisServices.Tabular.DataType;

namespace PbitToSsasConverter.UnitTests;

public sealed class ModelConversionTests
{
    [Theory]
    [InlineData("report.pbit")][InlineData("REPORT.PBIT")]
    public void AcceptsPbitExtension(string name) => ModelConversionService.ValidateFile(name);
    [Theory]
    [InlineData("report.pbix")][InlineData("report.zip")][InlineData("report.pbit.exe")][InlineData("")]
    public void RejectsOtherExtensions(string name) => Assert.Throws<ConversionException>(() => ModelConversionService.ValidateFile(name));
    [Theory]
    [InlineData(1000)][InlineData(1599)][InlineData(9999)]
    public void RejectsInvalidCompatibility(int level) => Assert.Throws<ConversionException>(() => TomValidator.ValidateOptions(new() { CompatibilityLevel = level }));
    [Fact]
    public void PreservesTablesColumnsMeasuresDaxAndMAndDependencies()
    {
        var model = new MetadataNormalizer(new()).Normalize(ModelFixture.Schema(), null, default);
        using var db = ModelFixture.Builder().Build(model, new(), default);
        Assert.Equal(3, db.Model.Tables.Count);
        var sales = db.Model.Tables["Sales"];
        Assert.Equal(DataType.Decimal, sales.Columns["Amount"].DataType);
        Assert.Equal("#,0.00", sales.Columns["Amount"].FormatString);
        Assert.Equal("SUM(Sales[Amount])", sales.Measures["Total Sales"].Expression);
        Assert.Equal("Revenue", sales.Measures["Total Sales"].DisplayFolder);
        Assert.True(sales.Measures["Total Sales"].IsHidden);
        Assert.Equal("Sales[Amount] * 2", Assert.IsType<CalculatedColumn>(sales.Columns["DoubleAmount"]).Expression);
        Assert.Same(sales.Columns["CustomerId"], sales.Columns["Label"].SortByColumn);
        Assert.True(sales.Columns["Label"].IsHidden);
        Assert.True(sales.Hierarchies["Customer hierarchy"].IsHidden);
        Assert.Same(sales.Columns["CustomerId"], sales.Hierarchies["Customer hierarchy"].Levels[0].Column);
        Assert.Equal(ModelFixture.SqlM, Assert.IsType<MPartitionSource>(sales.Partitions[0].Source).Expression);
        Assert.Equal(ModelFixture.ExcelM, Assert.IsType<MPartitionSource>(db.Model.Tables["Customer"].Partitions[0].Source).Expression);
        Assert.Contains(model.Warnings, w => w.Code == "EXTERNAL_FILE" && w.Message.Contains("C:\\Reports\\Sales.xlsx"));
        Assert.Equal("CALENDAR(DATE(2020,1,1),DATE(2030,12,31))", Assert.IsType<CalculatedPartitionSource>(db.Model.Tables["Calendar"].Partitions[0].Source).Expression);
        var relation = Assert.IsType<SingleColumnRelationship>(db.Model.Relationships[0]);
        Assert.False(relation.IsActive);
        Assert.Equal(RelationshipEndCardinality.Many, relation.FromCardinality);
        Assert.Equal("Sales[CustomerId] = 1", db.Model.Roles[0].TablePermissions[0].FilterExpression);
        Assert.Single(db.Model.Perspectives[0].PerspectiveTables[0].PerspectiveMeasures);
        Assert.Equal("Synthetic test fixture", db.Model.Annotations["Origin"].Value);
        var bytes = new ModelBimSerializer(new()).SerializeAndValidate(db);
        using var document = JsonDocument.Parse(bytes);
        Assert.Equal(1600, document.RootElement.GetProperty("compatibilityLevel").GetInt32());
        using var copy = TomJson.DeserializeDatabase(Encoding.UTF8.GetString(bytes), mode: CompatibilityMode.AnalysisServices);
        Assert.Equal(ModelFixture.SqlM, Assert.IsType<MPartitionSource>(copy.Model.Tables["Sales"].Partitions[0].Source).Expression);
        Assert.DoesNotContain("createOrReplace", Encoding.UTF8.GetString(bytes));
    }
    [Theory]
    [InlineData("int64", DataType.Int64)][InlineData("double", DataType.Double)][InlineData("decimal", DataType.Decimal)]
    [InlineData("string", DataType.String)][InlineData("dateTime", DataType.DateTime)][InlineData("boolean", DataType.Boolean)]
    [InlineData("binary", DataType.Binary)][InlineData("variant", DataType.Variant)]
    public void MapsColumnTypes(string type, DataType expected)
    {
        var schema = ModelFixture.Schema(); schema["tables"]![0]!["columns"]![1]!["dataType"] = type;
        using var db = ModelFixture.Builder().Build(new MetadataNormalizer(new()).Normalize(schema, null, default), new(), default);
        Assert.Equal(expected, db.Model.Tables["Sales"].Columns["Amount"].DataType);
    }
    [Fact]
    public void ManyToManyAndActiveRelationshipArePreserved()
    {
        var schema = ModelFixture.Schema();
        schema["relationships"]![0]!["toCardinality"] = "many"; schema["relationships"]![0]!["isActive"] = true;
        schema["relationships"]![0]!["crossFilteringBehavior"] = "both";
        using var db = ModelFixture.Builder().Build(new MetadataNormalizer(new()).Normalize(schema, null, default), new(), default);
        var r = Assert.IsType<SingleColumnRelationship>(db.Model.Relationships[0]);
        Assert.True(r.IsActive); Assert.Equal(RelationshipEndCardinality.Many, r.ToCardinality); Assert.Equal(CrossFilteringBehavior.BothDirections, r.CrossFilteringBehavior);
        new ModelBimSerializer(new()).SerializeAndValidate(db);
    }
    [Fact]
    public void MissingRelationshipIsReportedWithoutLosingModel()
    {
        var schema = ModelFixture.Schema(); schema["relationships"]![0]!["toColumn"] = "Missing";
        var model = new MetadataNormalizer(new()).Normalize(schema, null, default);
        using var db = ModelFixture.Builder().Build(model, new(), default);
        Assert.Empty(db.Model.Relationships); Assert.Contains(model.Warnings, w => w.Code == "RELATIONSHIP_REFERENCE");
        new ModelBimSerializer(new()).SerializeAndValidate(db);
    }
    [Fact]
    public void UnknownFeatureAndRefreshPolicyProduceWarnings()
    {
        var schema = ModelFixture.Schema(); schema["futurePowerBiFeature"] = new JsonObject { ["enabled"] = true };
        schema["tables"]![0]!["refreshPolicy"] = new JsonObject();
        var model = new MetadataNormalizer(new()).Normalize(schema, null, default);
        using var db = ModelFixture.Builder().Build(model, new(), default);
        Assert.Contains(model.Warnings, w => w.Code == "UNSUPPORTED_METADATA"); Assert.Contains(model.Warnings, w => w.Code == "POWER_BI_FEATURE");
    }
    [Fact]
    public void MissingPartitionBlocksDownloadInsteadOfInventingAnExpression()
    {
        var schema = ModelFixture.Schema(); schema["tables"]![0]!["partitions"]![0]!["source"]!["expression"] = null;
        var model = new MetadataNormalizer(new()).Normalize(schema, null, default);
        using var db = ModelFixture.Builder().Build(model, new(), default);
        Assert.Contains(model.Warnings, w => w.Code == "MISSING_EXPRESSION");
        Assert.Throws<ConversionException>(() => new ModelBimSerializer(new()).SerializeAndValidate(db));
    }
    [Fact]
    public void MissingSecurityReferenceIsFatal()
    {
        var schema = ModelFixture.Schema(); schema["roles"]![0]!["tablePermissions"]![0]!["name"] = "Missing";
        var ex = Assert.Throws<ConversionException>(() => ModelFixture.Builder().Build(new MetadataNormalizer(new()).Normalize(schema, null, default), new(), default));
        Assert.Equal("SECURITY_REFERENCE", ex.Code);
    }
    [Fact]
    public void DuplicateNamesAreRejectedCaseInsensitively()
    {
        var schema = ModelFixture.Schema(); schema["tables"]![1]!["name"] = "SALES";
        Assert.Throws<ConversionException>(() => ModelFixture.Builder().Build(new MetadataNormalizer(new()).Normalize(schema, null, default), new(), default));
    }
    [Fact]
    public void CredentialsAreRemovedFromConnectionMetadataAndExpressions()
    {
        var schema = ModelFixture.Schema();
        schema["credential"] = new JsonObject { ["password"] = "do-not-keep" };
        schema["test"] = "Server=x;Password=super-secret;User ID=foo";
        schema["url"] = "https://user:secret@example.com?sig=private-token";
        var warnings = new List<ConversionWarning>(); new CredentialSanitizer().Sanitize(schema, warnings);
        Assert.DoesNotContain("super-secret", schema.ToJsonString()); Assert.DoesNotContain("do-not-keep", schema.ToJsonString());
        Assert.DoesNotContain("private-token", schema.ToJsonString()); Assert.Null(schema["credential"]);
        Assert.Contains(warnings, w => w.Code == "CREDENTIALS_REMOVED");
    }
    [Fact]
    public void DirectLakeIsNotConvertedToImport()
    {
        var schema = ModelFixture.Schema(); schema["tables"]![0]!["partitions"]![0]!["mode"] = "directLake";
        var model = new MetadataNormalizer(new()).Normalize(schema, null, default);
        using var db = ModelFixture.Builder().Build(model, new(), default);
        Assert.Empty(db.Model.Tables["Sales"].Partitions); Assert.Contains(model.Warnings, w => w.Code == "DIRECT_LAKE");
        Assert.Throws<ConversionException>(() => new TomValidator().Validate(db));
    }
}
