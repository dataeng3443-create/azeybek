namespace PbitToSsasConverter.Web.Models.Conversion;

public enum IssueSeverity { Info, Warning, Error }
public sealed record ConversionWarning(string Code, string Object, string Message, IssueSeverity Severity = IssueSeverity.Warning);
public sealed record ConversionError(string Code, string Message);
public sealed record ConversionProgress(int Percentage, string Stage, string Message);
public sealed class ConversionOptions
{
    public int CompatibilityLevel { get; set; } = 1600;
    public bool PreserveAnnotations { get; set; } = true;
    public bool PreserveHiddenObjects { get; set; } = true;
    public bool PreservePowerQueryExpressions { get; set; } = true;
    public bool GenerateConversionReport { get; set; } = true;
}
public sealed record ConversionStatistics(int Tables, int Columns, int Measures, int Relationships, int Partitions, int DataSources);
public sealed class ConversionResult
{
    public bool Success { get; init; }
    public byte[]? ModelBim { get; init; }
    public string FileName { get; init; } = "Model.bim";
    public ConversionStatistics Statistics { get; init; } = new(0, 0, 0, 0, 0, 0);
    public IReadOnlyList<ConversionWarning> Warnings { get; init; } = [];
    public IReadOnlyList<ConversionError> Errors { get; init; } = [];
    public byte[]? ConversionReport { get; init; }
}
public sealed class ConversionLimits
{
    public long MaxUploadBytes { get; set; } = 500L * 1024 * 1024;
    public long MaxExtractedBytes { get; set; } = 2L * 1024 * 1024 * 1024;
    public long MaxArtifactBytes { get; set; } = 128L * 1024 * 1024;
    public long MaxTotalMetadataBytes { get; set; } = 256L * 1024 * 1024;
    public int MaxEntries { get; set; } = 10_000;
    public int MaxCompressionRatio { get; set; } = 1000;
    public int ProcessingTimeoutSeconds { get; set; } = 600;
    public int DownloadRetentionMinutes { get; set; } = 30;
    public int MaxConcurrentConversions { get; set; } = 2;
    public long MaxRetainedOutputBytes { get; set; } = 512L * 1024 * 1024;
    public string TempRoot { get; set; } = Path.Combine(Path.GetTempPath(), "PbitToSsasConverter");
}
public sealed class ConversionException(string code, string message, Exception? inner = null) : Exception(message, inner)
{
    public string Code { get; } = code;
}
