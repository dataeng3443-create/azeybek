using System.Net;
using System.Text;
using System.Text.Json;
using System.IO.Compression;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using PbitToSsasConverter.Tests;
using PbitToSsasConverter.Web.Infrastructure;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Services.Conversion;

namespace PbitToSsasConverter.IntegrationTests;

public sealed class ConversionPipelineTests : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly WebApplicationFactory<Program> factory;
    public ConversionPipelineTests(WebApplicationFactory<Program> factory) => this.factory = factory;
    [Theory]
    [InlineData(1500)][InlineData(1600)][InlineData(1700)]
    public async Task ConvertsRealZipThroughTomAndServesDownloads(int compatibility)
    {
        using var scope = factory.Services.CreateScope();
        using var package = ModelFixture.Package();
        var service = scope.ServiceProvider.GetRequiredService<IModelConversionService>();
        var progress = new RecordingProgress();
        var result = await service.ConvertAsync(package, "Sales.pbit", new() { CompatibilityLevel = compatibility }, progress, default);
        Assert.True(result.Success, string.Join("; ", result.Errors.Select(e => e.Code + ": " + e.Message)));
        Assert.Equal(3, result.Statistics.Tables); Assert.Equal(1, result.Statistics.Relationships);
        Assert.Equal(100, progress.Values.Last().Percentage);
        Assert.Equal(progress.Values.Select(p => p.Percentage).Order(), progress.Values.Select(p => p.Percentage));
        using var doc = JsonDocument.Parse(result.ConversionReport!);
        Assert.True(doc.RootElement.GetProperty("validation").GetProperty("tomRoundTrip").GetBoolean());
        var jobs = scope.ServiceProvider.GetRequiredService<ConversionJobManager>();
        var token = jobs.Retain(result);
        using var client = factory.CreateClient();
        var download = await client.GetAsync($"/downloads/{token}/model");
        Assert.Equal(HttpStatusCode.OK, download.StatusCode);
        Assert.Contains("Model.bim", download.Content.Headers.ContentDisposition!.ToString());
        Assert.Equal(result.ModelBim, await download.Content.ReadAsByteArrayAsync());
        Assert.True(download.Headers.CacheControl!.NoStore);
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync($"/downloads/{token}/report")).StatusCode);
        jobs.Remove(token);
        Assert.Equal(HttpStatusCode.NotFound, (await client.GetAsync($"/downloads/{token}/model")).StatusCode);
    }
    [Fact]
    public async Task InvalidUploadReturnsSafeFailureAndReport()
    {
        using var scope = factory.Services.CreateScope();
        using var source = new MemoryStream(Encoding.UTF8.GetBytes("broken"));
        var result = await scope.ServiceProvider.GetRequiredService<IModelConversionService>().ConvertAsync(source, "bad.pbit", new(), null, default);
        Assert.False(result.Success); Assert.Null(result.ModelBim); Assert.NotNull(result.ConversionReport);
        Assert.Equal("UNSUPPORTED_PACKAGE", Assert.Single(result.Errors).Code);
        var jobs = scope.ServiceProvider.GetRequiredService<ConversionJobManager>();
        var token = jobs.Retain(result);
        using var client = factory.CreateClient();
        Assert.Equal(HttpStatusCode.NotFound, (await client.GetAsync($"/downloads/{token}/model")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync($"/downloads/{token}/report")).StatusCode);
        jobs.Remove(token);
    }
    [Fact]
    public async Task BinaryOnlyPackageFailsWithExplicitUnsupportedPath()
    {
        using var source = new MemoryStream();
        using (var zip = new ZipArchive(source, ZipArchiveMode.Create, true)) { using var writer = new StreamWriter(zip.CreateEntry("DataMashup").Open()); writer.Write("binary content"); }
        source.Position = 0;
        using var scope = factory.Services.CreateScope();
        var result = await scope.ServiceProvider.GetRequiredService<IModelConversionService>().ConvertAsync(source, "binary.pbit", new(), null, default);
        Assert.False(result.Success); Assert.Equal("UNSUPPORTED_EXTRACTION_PATH", Assert.Single(result.Errors).Code);
    }
    [Fact]
    public async Task HomeAndLocalStylesAreServed()
    {
        using var client = factory.CreateClient();
        var page = await client.GetStringAsync("/");
        Assert.Contains("Power BI", page); Assert.Contains("Generate SSAS Model", page);
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/lib/bootstrap/bootstrap.min.css")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/css/app.css")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/health")).StatusCode);
    }
    [Fact]
    public void RetentionCapacityAndUnknownTokensAreEnforced()
    {
        using var jobs = new ConversionJobManager(Options.Create(new ConversionLimits { MaxRetainedOutputBytes = 10 }));
        Assert.Null(jobs.Get("unknown", "model"));
        Assert.Throws<ConversionException>(() => jobs.Retain(new() { ModelBim = new byte[11] }));
        var token = jobs.Retain(new() { Success = true, ModelBim = new byte[5] });
        Assert.NotNull(jobs.Get(token, "model")); Assert.Null(jobs.Get(token, "unrecognized"));
        jobs.Remove(token); Assert.Null(jobs.Get(token, "model"));
    }
    private sealed class RecordingProgress : IProgress<ConversionProgress>
    {
        public List<ConversionProgress> Values { get; } = [];
        public void Report(ConversionProgress value) => Values.Add(value);
    }
    [Fact]
    public void ExpiredDownloadsAreRemovedAndReleaseCapacity()
    {
        var clock = new TestClock();
        using var jobs = new ConversionJobManager(Options.Create(new ConversionLimits { MaxRetainedOutputBytes = 5, DownloadRetentionMinutes = 1 }), clock);
        var token = jobs.Retain(new() { Success = true, ModelBim = new byte[5] });
        Assert.NotNull(jobs.Get(token, "model"));
        clock.UtcNow += TimeSpan.FromMinutes(2);
        Assert.Null(jobs.Get(token, "model"));
        Assert.NotNull(jobs.Retain(new() { Success = true, ModelBim = new byte[5] }));
    }
    private sealed class TestClock : TimeProvider
    {
        public DateTimeOffset UtcNow { get; set; } = DateTimeOffset.UtcNow;
        public override DateTimeOffset GetUtcNow() => UtcNow;
    }
}
