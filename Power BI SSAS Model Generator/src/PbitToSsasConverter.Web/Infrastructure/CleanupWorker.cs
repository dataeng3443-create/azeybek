using Microsoft.Extensions.Options;
using PbitToSsasConverter.Web.Models.Conversion;

namespace PbitToSsasConverter.Web.Infrastructure;

public sealed class CleanupWorker(ConversionJobManager jobs, TempFileManager temp, IOptions<ConversionLimits> settings, ILogger<CleanupWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        // Process-specific temp subdirectories are removed in finally. Retry crash leftovers at startup.
        if (Directory.Exists(settings.Value.TempRoot))
            foreach (var path in Directory.EnumerateDirectories(settings.Value.TempRoot))
                if (Guid.TryParseExact(Path.GetFileName(path), "N", out _) && Directory.GetLastWriteTimeUtc(path) < DateTime.UtcNow.AddHours(-24)) temp.Delete(path);
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(30));
        try { while (await timer.WaitForNextTickAsync(stoppingToken)) jobs.Cleanup(); }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { logger.LogInformation("CLEANUP_WORKER_STOPPED"); }
    }
}
