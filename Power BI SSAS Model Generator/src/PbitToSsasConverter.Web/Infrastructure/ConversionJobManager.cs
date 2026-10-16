using System.Security.Cryptography;
using Microsoft.Extensions.Options;
using PbitToSsasConverter.Web.Models.Conversion;

namespace PbitToSsasConverter.Web.Infrastructure;

public sealed record DownloadArtifact(byte[] Bytes, string Name);
public sealed class ConversionJobManager(IOptions<ConversionLimits> settings, TimeProvider? clock = null) : IDisposable
{
    private readonly TimeProvider time = clock ?? TimeProvider.System;
    private sealed record Output(ConversionResult Result, DateTimeOffset Expires, long Size);
    private readonly SemaphoreSlim gate = new(settings.Value.MaxConcurrentConversions);
    private readonly Dictionary<string, Output> outputs = [];
    private readonly object sync = new();
    private long stored;
    public Task<bool> TryEnterAsync(CancellationToken ct) => gate.WaitAsync(0, ct);
    public void Exit() => gate.Release();
    public string Retain(ConversionResult result)
    {
        var size = (result.ModelBim?.LongLength ?? 0) + (result.ConversionReport?.LongLength ?? 0);
        lock (sync)
        {
            CleanupCore();
            if (size > settings.Value.MaxRetainedOutputBytes - stored) throw new ConversionException("OUTPUT_CAPACITY", "Download storage is full. Retry after existing downloads expire.");
            var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
            outputs[token] = new(result, time.GetUtcNow().AddMinutes(settings.Value.DownloadRetentionMinutes), size);
            stored += size;
            return token;
        }
    }
    public DownloadArtifact? Get(string token, string kind)
    {
        lock (sync)
        {
            CleanupCore();
            if (!outputs.TryGetValue(token, out var output)) return null;
            return kind switch
            {
                "model" when output.Result.Success && output.Result.ModelBim is not null => new(output.Result.ModelBim, "Model.bim"),
                "report" when output.Result.ConversionReport is not null => new(output.Result.ConversionReport, "conversion-report.json"), _ => null
            };
        }
    }
    public void Remove(string? token) { if (token is null) return; lock (sync) if (outputs.Remove(token, out var output)) stored -= output.Size; }
    public void Cleanup() { lock (sync) CleanupCore(); }
    private void CleanupCore()
    {
        foreach (var key in outputs.Where(x => x.Value.Expires <= time.GetUtcNow()).Select(x => x.Key).ToArray())
        { stored -= outputs[key].Size; outputs.Remove(key); }
    }
    public void Dispose() => gate.Dispose();
}
