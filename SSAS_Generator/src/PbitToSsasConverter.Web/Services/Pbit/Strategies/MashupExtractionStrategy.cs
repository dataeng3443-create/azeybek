using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Pbit;

namespace PbitToSsasConverter.Web.Services.Pbit.Strategies;

// Binary mashup contents are intentionally not treated as a documented or executable format.
// M partitions and named expressions in JSON are handled by the schema strategy.
public sealed class MashupExtractionStrategy : IPbitModelExtractionStrategy
{
    public bool CanHandle(PbitPackageContext context) => context.Artifacts.Any(IsMashup);
    public Task<ExtractionResult> ExtractAsync(PbitPackageContext context, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var warnings = context.Artifacts.Where(IsMashup).Select(a => new ConversionWarning("UNSUPPORTED_EXTRACTION_PATH", a.EntryName,
            "Standalone/binary Power Query mashup extraction is unsupported. M expressions present in semantic JSON are preserved; additional mashup-only queries cannot be recovered.")).ToList();
        return Task.FromResult(new ExtractionResult([], warnings));
    }
    private static bool IsMashup(PbitArtifact a) => a.Kind == "m-section" || a.EntryName.Contains("mashup", StringComparison.OrdinalIgnoreCase);
}
