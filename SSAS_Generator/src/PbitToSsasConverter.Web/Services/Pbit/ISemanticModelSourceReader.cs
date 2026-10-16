using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Intermediate;
using PbitToSsasConverter.Web.Models.Pbit;

namespace PbitToSsasConverter.Web.Services.Pbit;

public interface ISemanticModelSourceReader
{
    bool CanRead(ModelSource source);
    Task<NormalizedPowerBiModel> ReadAsync(ModelSource source, Guid jobId, string directory, IProgress<ConversionProgress>? progress, CancellationToken ct);
}
public sealed class PbitSourceReader(IPbitPackageReader packageReader, IPbitModelExtractor extractor) : ISemanticModelSourceReader
{
    public bool CanRead(ModelSource source) => Path.GetExtension(source.FileName).Equals(".pbit", StringComparison.OrdinalIgnoreCase);
    public async Task<NormalizedPowerBiModel> ReadAsync(ModelSource source, Guid jobId, string directory, IProgress<ConversionProgress>? progress, CancellationToken ct)
    {
        var package = await packageReader.ReadAsync(jobId, Path.Combine(directory, "source.pbit"), directory, ct);
        progress?.Report(new(20, "semantic", "Extracting semantic model"));
        return await extractor.ExtractAsync(package, progress, ct);
    }
}
