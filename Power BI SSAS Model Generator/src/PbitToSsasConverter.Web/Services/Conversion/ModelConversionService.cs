using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Options;
using PbitToSsasConverter.Web.Infrastructure;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Intermediate;
using PbitToSsasConverter.Web.Models.Pbit;
using PbitToSsasConverter.Web.Services.Pbit;
using PbitToSsasConverter.Web.Services.Ssas;

namespace PbitToSsasConverter.Web.Services.Conversion;

public interface IModelConversionService
{
    Task<ConversionResult> ConvertAsync(Stream pbitStream, string originalFileName, ConversionOptions options, IProgress<ConversionProgress>? progress, CancellationToken cancellationToken);
}
public sealed class ModelConversionService(IEnumerable<ISemanticModelSourceReader> readers, TempFileManager temp, ISsasModelBuilder builder,
    ModelBimSerializer serializer, ConversionJobManager jobs, IOptions<ConversionLimits> settings, ILogger<ModelConversionService> logger) : IModelConversionService
{
    public async Task<ConversionResult> ConvertAsync(Stream pbitStream, string originalFileName, ConversionOptions options, IProgress<ConversionProgress>? progress, CancellationToken cancellationToken)
    {
        var id = Guid.NewGuid();
        var stage = "upload";
        string? directory = null;
        NormalizedPowerBiModel? model = null;
        var statistics = new ConversionStatistics(0, 0, 0, 0, 0, 0);
        var limits = settings.Value;
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(limits.ProcessingTimeoutSeconds));
        var ct = timeout.Token;
        var acquired = false;
        var sourceName = Path.GetFileName(originalFileName.Replace('\\', '/'));
        try
        {
            ValidateFile(sourceName);
            TomValidator.ValidateOptions(options);
            acquired = await jobs.TryEnterAsync(ct);
            if (!acquired) throw new ConversionException("SERVER_BUSY", "The converter is processing its maximum number of jobs. Please try again shortly.");
            directory = temp.Create(id);
            var source = new ModelSource(sourceName, pbitStream);
            var reader = readers.FirstOrDefault(r => r.CanRead(source)) ?? throw new ConversionException("FILE_TYPE", "Only .pbit files are supported.");
            logger.LogInformation("PBIT_UPLOAD_STARTED {JobId}", id);
            progress?.Report(new(0, "upload", "Uploading Power BI Template..."));
            await CopyUploadAsync(pbitStream, Path.Combine(directory, "source.pbit"), limits.MaxUploadBytes, ct);
            logger.LogInformation("PBIT_UPLOAD_COMPLETED {JobId}", id);
            stage = "extraction";
            progress?.Report(new(10, "package", "Reading Power BI package"));
            logger.LogInformation("PBIT_EXTRACTION_STARTED {JobId}", id);
            model = await reader.ReadAsync(source, id, directory, progress, ct);
            logger.LogInformation("PBIT_EXTRACTION_COMPLETED {JobId} {Tables} {Measures} {Relationships}", id, model.Tables.Count, model.Tables.Sum(t => t.Measures.Count), model.Relationships.Count);
            progress?.Report(new(60, "normalize", "Converting Power BI metadata"));
            ct.ThrowIfCancellationRequested();
            stage = "tom";
            progress?.Report(new(70, "build", "Building SSAS Tabular Model"));
            logger.LogInformation("TOM_BUILD_STARTED {JobId}", id);
            using var database = await Task.Run(() => builder.Build(model, options, ct), ct);
            logger.LogInformation("TOM_BUILD_COMPLETED {JobId}", id);
            statistics = new(database.Model.Tables.Count, database.Model.Tables.Sum(t => t.Columns.Count), database.Model.Tables.Sum(t => t.Measures.Count), database.Model.Relationships.Count, database.Model.Tables.Sum(t => t.Partitions.Count), database.Model.DataSources.Count);
            stage = "validation";
            progress?.Report(new(85, "validate", "Validating Model.bim and TOM round-trip"));
            logger.LogInformation("MODEL_VALIDATION_STARTED {JobId}", id);
            ct.ThrowIfCancellationRequested();
            var bytes = await Task.Run(() => serializer.SerializeAndValidate(database), ct);
            ct.ThrowIfCancellationRequested();
            logger.LogInformation("MODEL_VALIDATION_COMPLETED {JobId}", id);
            progress?.Report(new(95, "output", "Generating output"));
            var result = Result(true, bytes, [], model.Warnings, sourceName, options, statistics);
            logger.LogInformation("MODEL_BIM_CREATED {JobId} {ByteCount}", id, bytes.Length);
            progress?.Report(new(100, "completed", "SSAS Model Successfully Generated"));
            return result;
        }
        catch (Exception ex) when (ex is not OutOfMemoryException)
        {
            // Exception messages from third-party parsers may contain source expressions or credentials.
            // Log type and stack for diagnostics, never the raw exception/message or source metadata.
            logger.LogError("CONVERSION_FAILED {JobId} {Stage} {ExceptionType} {StackTrace}", id, stage, ex.GetType().FullName, ex.StackTrace);
            var error = ex switch
            {
                ConversionException e => new ConversionError(e.Code, CredentialSanitizer.Redact(e.Message)),
                OperationCanceledException => new ConversionError(cancellationToken.IsCancellationRequested ? "CANCELLED" : "TIMEOUT", cancellationToken.IsCancellationRequested ? "Conversion cancelled." : "Conversion exceeded the configured time limit."),
                InvalidDataException => new ConversionError("ARCHIVE_INVALID", "The uploaded Power BI template could not be read."),
                IOException => new ConversionError("IO_ERROR", "The file could not be read or written. Please retry or contact the administrator."),
                _ => new ConversionError(stage == "validation" ? "MODEL_VALIDATION" : stage == "tom" ? "TOM_CONVERSION" : "METADATA_PARSE", "The semantic model could not be converted safely. Review the conversion report and try a new PBIT export.")
            };
            return Result(false, null, [error], model?.Warnings ?? [], sourceName, options, statistics);
        }
        finally
        {
            if (directory is not null) temp.Delete(directory);
            if (acquired) jobs.Exit();
        }
    }
    public static void ValidateFile(string name)
    {
        if (string.IsNullOrWhiteSpace(name) || !Path.GetExtension(name).Equals(".pbit", StringComparison.OrdinalIgnoreCase))
            throw new ConversionException("FILE_TYPE", "Only Power BI Template (.pbit) files are accepted.");
    }
    private static async Task CopyUploadAsync(Stream source, string path, long limit, CancellationToken ct)
    {
        await using var output = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None, 81920, true);
        var buffer = new byte[81920];
        long total = 0;
        int read;
        while ((read = await source.ReadAsync(buffer, ct)) > 0)
        {
            total += read;
            if (total > limit) throw new ConversionException("FILE_SIZE", "The uploaded file exceeds the configured size limit.");
            await output.WriteAsync(buffer.AsMemory(0, read), ct);
        }
        if (total == 0) throw new ConversionException("EMPTY_FILE", "The uploaded file is empty.");
    }
    private static ConversionResult Result(bool success, byte[]? bim, IReadOnlyList<ConversionError> errors, List<ConversionWarning> warnings, string file, ConversionOptions options, ConversionStatistics statistics)
    {
        var distinct = warnings.Distinct().ToArray();
        var report = new { sourceFile = file, targetCompatibilityLevel = options.CompatibilityLevel, success, statistics, warnings = distinct, errors,
            unsupportedFeatures = distinct.Where(w => w.Code is "POWER_BI_FEATURE" or "COMPATIBILITY" or "UNSUPPORTED_METADATA" or "DIRECT_LAKE" or "UNSUPPORTED_EXTRACTION_PATH").ToArray(),
            validation = new { tomRoundTrip = success, serverDeploymentTested = false, daxAndMExecutionTested = false } };
        return new() { Success = success, ModelBim = bim, Statistics = statistics, Warnings = distinct, Errors = errors,
            ConversionReport = options.GenerateConversionReport ? JsonSerializer.SerializeToUtf8Bytes(report, new JsonSerializerOptions(JsonSerializerDefaults.Web) { WriteIndented = true, Converters = { new JsonStringEnumConverter() } }) : null };
    }
}
