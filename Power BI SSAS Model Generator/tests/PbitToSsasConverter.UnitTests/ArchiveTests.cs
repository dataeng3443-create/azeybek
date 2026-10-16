using System.IO.Compression;
using System.Text;
using Microsoft.Extensions.Options;
using PbitToSsasConverter.Tests;
using PbitToSsasConverter.Web.Infrastructure;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Services.Pbit;

namespace PbitToSsasConverter.UnitTests;

public sealed class ArchiveTests : IDisposable
{
    private readonly string root = Path.Combine(Path.GetTempPath(), "pbit-tests-" + Guid.NewGuid().ToString("N"));
    public ArchiveTests() => Directory.CreateDirectory(root);
    [Theory]
    [InlineData("../escaped.txt")][InlineData("../../outside")][InlineData("..\\escape.txt")][InlineData("/etc/file")][InlineData("C:/Windows/file")]
    public async Task RejectsZipSlip(string name)
    {
        var path = Zip((name, "data"));
        var ex = await Assert.ThrowsAsync<ConversionException>(() => new SecureArchiveExtractor(ModelFixture.Limits(root)).ExtractAsync(path, Path.Combine(root, "out"), default));
        Assert.Equal("UNSAFE_ARCHIVE", ex.Code);
    }
    [Fact]
    public async Task RejectsCaseInsensitiveDuplicatePaths()
    {
        var path = Zip(("Metadata", "a"), ("metadata", "b"));
        var ex = await Assert.ThrowsAsync<ConversionException>(() => new SecureArchiveExtractor(ModelFixture.Limits(root)).ExtractAsync(path, Path.Combine(root, "out"), default));
        Assert.Equal("UNSAFE_ARCHIVE", ex.Code);
    }
    [Fact]
    public async Task RejectsInvalidArchive()
    {
        var path = Path.Combine(root, "source.pbit"); await File.WriteAllTextAsync(path, "not a ZIP");
        var reader = new PbitPackageReader(new(ModelFixture.Limits(root)), new());
        Assert.Equal("UNSUPPORTED_PACKAGE", (await Assert.ThrowsAsync<ConversionException>(() => reader.ReadAsync(Guid.NewGuid(), path, root, default))).Code);
    }
    [Fact]
    public async Task RejectsTruncatedZip()
    {
        var path = Path.Combine(root, "source.pbit"); await File.WriteAllBytesAsync(path, [0x50, 0x4b, 3, 4, 1, 2]);
        var reader = new PbitPackageReader(new(ModelFixture.Limits(root)), new());
        Assert.Equal("ARCHIVE_INVALID", (await Assert.ThrowsAsync<ConversionException>(() => reader.ReadAsync(Guid.NewGuid(), path, root, default))).Code);
    }
    [Fact]
    public async Task EnforcesExtractedSizeAndFileCountLimits()
    {
        var path = Zip(("a", "some metadata"), ("b", "more metadata"));
        var limits = Options.Create(new ConversionLimits { MaxEntries = 1 });
        Assert.Equal("ARCHIVE_LIMIT", (await Assert.ThrowsAsync<ConversionException>(() => new SecureArchiveExtractor(limits).ExtractAsync(path, Path.Combine(root, "count"), default))).Code);
        limits.Value.MaxEntries = 10; limits.Value.MaxExtractedBytes = 2;
        Assert.Equal("ARCHIVE_LIMIT", (await Assert.ThrowsAsync<ConversionException>(() => new SecureArchiveExtractor(limits).ExtractAsync(path, Path.Combine(root, "size"), default))).Code);
    }
    [Fact]
    public async Task RejectsZipBombCompressionRatio()
    {
        var path = Zip(("a", new string('a', 100_000)));
        var limits = Options.Create(new ConversionLimits { MaxCompressionRatio = 10 });
        Assert.Equal("ARCHIVE_RATIO", (await Assert.ThrowsAsync<ConversionException>(() => new SecureArchiveExtractor(limits).ExtractAsync(path, Path.Combine(root, "out"), default))).Code);
    }
    [Fact]
    public async Task RejectsSymbolicLinks()
    {
        var path = Path.Combine(root, "link.pbit");
        using (var archive = ZipFile.Open(path, ZipArchiveMode.Create))
        {
            var entry = archive.CreateEntry("link"); entry.ExternalAttributes = unchecked((int)0xA1FF0000);
            using var writer = new StreamWriter(entry.Open()); writer.Write("/etc/passwd");
        }
        Assert.Equal("UNSAFE_ARCHIVE", (await Assert.ThrowsAsync<ConversionException>(() => new SecureArchiveExtractor(ModelFixture.Limits(root)).ExtractAsync(path, Path.Combine(root, "out"), default))).Code);
    }
    [Theory]
    [InlineData("utf-8")][InlineData("utf-16")][InlineData("utf-16BE")][InlineData("utf-32")]
    public async Task IdentifiesJsonByContentAndEncoding(string encoding)
    {
        var text = "{\"model\":{\"tables\":[]}}";
        var path = Path.Combine(root, "random-name"); await File.WriteAllTextAsync(path, text, Encoding.GetEncoding(encoding));
        var artifact = await new PbitPackageInspector().InspectAsync("random-name", path, new FileInfo(path).Length, default);
        Assert.Equal("json", artifact.Kind);
    }
    [Fact]
    public async Task HonorsCancellation()
    {
        var path = Zip(("a", "data"));
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new SecureArchiveExtractor(ModelFixture.Limits(root)).ExtractAsync(path, Path.Combine(root, "out"), cancellation.Token));
    }
    private string Zip(params (string Name, string Text)[] entries)
    {
        var path = Path.Combine(root, Guid.NewGuid() + ".pbit");
        using var zip = ZipFile.Open(path, ZipArchiveMode.Create);
        foreach (var entry in entries) { using var writer = new StreamWriter(zip.CreateEntry(entry.Name, CompressionLevel.Optimal).Open()); writer.Write(entry.Text); }
        return path;
    }
    public void Dispose() => Directory.Delete(root, true);
}
