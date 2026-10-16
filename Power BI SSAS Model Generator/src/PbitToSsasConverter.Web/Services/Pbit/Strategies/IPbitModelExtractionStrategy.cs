using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Pbit;

namespace PbitToSsasConverter.Web.Services.Pbit.Strategies;

public sealed record ExtractionResult(IReadOnlyList<ExtractedModel> Models, IReadOnlyList<ConversionWarning> Warnings);
public interface IPbitModelExtractionStrategy
{
    bool CanHandle(PbitPackageContext context);
    Task<ExtractionResult> ExtractAsync(PbitPackageContext context, CancellationToken cancellationToken);
}
