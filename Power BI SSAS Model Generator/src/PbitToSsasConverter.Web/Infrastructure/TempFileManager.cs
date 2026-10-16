using Microsoft.Extensions.Options;
using PbitToSsasConverter.Web.Models.Conversion;

namespace PbitToSsasConverter.Web.Infrastructure;

public sealed class TempFileManager(IOptions<ConversionLimits> settings, ILogger<TempFileManager> logger)
{
    public string Create(Guid jobId)
    {
        var path = Path.Combine(settings.Value.TempRoot, jobId.ToString("N"));
        Directory.CreateDirectory(path);
        if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        return path;
    }
    public void Delete(string path)
    {
        try { if (Directory.Exists(path)) Directory.Delete(path, true); }
        catch (IOException) { logger.LogWarning("TEMP_CLEANUP_FAILED; stale directory will be retried"); }
        catch (UnauthorizedAccessException) { logger.LogWarning("TEMP_CLEANUP_FAILED; access denied"); }
    }
}
