using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using PbitToSsasConverter.Tests;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Pbit;
using PbitToSsasConverter.Web.Services.Pbit;
using PbitToSsasConverter.Web.Services.Pbit.Strategies;

namespace PbitToSsasConverter.UnitTests;

public sealed class ExtractionStrategyTests : IDisposable
{
    private readonly string root = Path.Combine(Path.GetTempPath(), "pbit-extraction-tests-" + Guid.NewGuid().ToString("N"));
    public ExtractionStrategyTests() => Directory.CreateDirectory(root);
    [Fact]
    public async Task MalformedArtifactDoesNotDiscardReadableSemanticModel()
    {
        var broken = await Artifact("unrelated.json", "{invalid json");
        var good = await Artifact("unknown-artifact", ModelFixture.Schema().ToJsonString());
        var result = await Strategy().ExtractAsync(new(Guid.NewGuid(), root, [broken, good]), default);
        Assert.Single(result.Models); Assert.Contains(result.Warnings, w => w.Code == "METADATA_PARSE");
    }
    [Fact]
    public async Task AggregateMetadataLimitIsEnforced()
    {
        var one = await Artifact("one", ModelFixture.Schema().ToJsonString());
        var two = await Artifact("two", ModelFixture.Schema().ToJsonString());
        var strategy = new JsonModelSchemaExtractionStrategy(Options.Create(new ConversionLimits { MaxTotalMetadataBytes = one.Length + 1 }));
        var result = await strategy.ExtractAsync(new(Guid.NewGuid(), root, [one, two]), default);
        Assert.Single(result.Models); Assert.Contains(result.Warnings, w => w.Code == "ARTIFACT_LIMIT");
    }
    [Fact]
    public async Task PipelineMergesComplementaryObjectsAndReportsConflicts()
    {
        var schema = ModelFixture.Schema();
        var main = await Artifact("primary", schema.ToJsonString());
        var supplementary = await Artifact("extra", """{"expressions":[{"name":"Extra","kind":"m","expression":"42"},{"name":"ServerName","kind":"m","expression":"\"DIFFERENT\""}]}""");
        var extractor = new PbitModelExtractor([Strategy(), new MashupExtractionStrategy()], new(new()), NullLogger<PbitModelExtractor>.Instance);
        var result = await extractor.ExtractAsync(new(Guid.NewGuid(), root, [main, supplementary]), null, default);
        Assert.Equal(2, result.Expressions.Count);
        Assert.Equal("\"SQLSERVER01\"", result.Expressions.Single(e => e.Name == "ServerName").Expression);
        Assert.Contains(result.Warnings, w => w.Code == "METADATA_CONFLICT");
    }
    [Fact]
    public async Task BinaryMashupProducesAnExplicitWarningAlongsideJsonExtraction()
    {
        var good = await Artifact("schema", ModelFixture.Schema().ToJsonString());
        var binary = new PbitArtifact("DataMashup", "unused", 20, "binary-or-text", null);
        var extractor = new PbitModelExtractor([Strategy(), new MashupExtractionStrategy()], new(new()), NullLogger<PbitModelExtractor>.Instance);
        var result = await extractor.ExtractAsync(new(Guid.NewGuid(), root, [binary, good]), null, default);
        Assert.Equal(3, result.Tables.Count); Assert.Contains(result.Warnings, w => w.Code == "UNSUPPORTED_EXTRACTION_PATH");
    }
    [Fact]
    public async Task Utf16InspectionHandlesSampleEndingInsideSurrogatePair()
    {
        var path = Path.Combine(root, "unicode");
        // BOM (2 bytes), 2046 chars (4092 bytes), then the high surrogate at byte 4094.
        var text = "{" + new string(' ', 2045) + "😀\"name\":\"test\"}";
        await File.WriteAllTextAsync(path, text, Encoding.Unicode);
        var artifact = await new PbitPackageInspector().InspectAsync("unicode", path, new FileInfo(path).Length, default);
        Assert.Equal("json", artifact.Kind);
    }
    private JsonModelSchemaExtractionStrategy Strategy() => new(ModelFixture.Limits(root));
    private async Task<PbitArtifact> Artifact(string name, string text)
    {
        var path = Path.Combine(root, name); await File.WriteAllTextAsync(path, text);
        return await new PbitPackageInspector().InspectAsync(name, path, new FileInfo(path).Length, default);
    }
    public void Dispose() => Directory.Delete(root, true);
}
