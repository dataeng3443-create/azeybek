using System.IO.Compression;
using Microsoft.Extensions.Options;
using PbitToSsasConverter.Web.Models.Conversion;

namespace PbitToSsasConverter.Web.Infrastructure;

public sealed class SecureArchiveExtractor(IOptions<ConversionLimits> settings)
{
    public async Task<IReadOnlyList<(string Name, string Path, long Length)>> ExtractAsync(string archive, string destination, CancellationToken ct)
    {
        var limits = settings.Value;
        Directory.CreateDirectory(destination);
        var root = Path.GetFullPath(destination) + Path.DirectorySeparatorChar;
        using var zip = ZipFile.OpenRead(archive);
        if (zip.Entries.Count > limits.MaxEntries) throw new ConversionException("ARCHIVE_LIMIT", "The package contains too many entries.");
        long declared = 0;
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        // Validate the entire central directory before writing any entry.
        foreach (var entry in zip.Entries)
        {
            ct.ThrowIfCancellationRequested();
            var name = entry.FullName.Replace('\\', '/');
            var path = Path.GetFullPath(Path.Combine(destination, name));
            if (!path.StartsWith(root, StringComparison.Ordinal) || name.Contains(':') || name.Split('/').Contains("..") ||
                ((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000 || !names.Add(path))
                throw new ConversionException("UNSAFE_ARCHIVE", "The package contains an unsafe or duplicate entry path.");
            if (entry.Length > limits.MaxExtractedBytes - declared)
                throw new ConversionException("ARCHIVE_LIMIT", "The extracted package exceeds the configured size limit.");
            declared += entry.Length;
            if (entry.Length > 0 && (entry.CompressedLength == 0 || (double)entry.Length / entry.CompressedLength > limits.MaxCompressionRatio))
                throw new ConversionException("ARCHIVE_RATIO", "The package exceeds the permitted compression ratio.");
        }
        var files = new List<(string, string, long)>();
        long actualTotal = 0;
        var buffer = new byte[81920];
        foreach (var entry in zip.Entries)
        {
            ct.ThrowIfCancellationRequested();
            var path = Path.GetFullPath(Path.Combine(destination, entry.FullName.Replace('\\', '/')));
            if (entry.FullName.EndsWith('/') || entry.FullName.EndsWith('\\')) { Directory.CreateDirectory(path); continue; }
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            await using var input = entry.Open();
            await using var output = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None, 81920, true);
            long actual = 0;
            int read;
            while ((read = await input.ReadAsync(buffer, ct)) > 0)
            {
                actual += read;
                actualTotal += read;
                if (actual > entry.Length || actualTotal > limits.MaxExtractedBytes)
                    throw new ConversionException("ARCHIVE_LIMIT", "The extracted package exceeds the configured size limit.");
                await output.WriteAsync(buffer.AsMemory(0, read), ct);
            }
            if (actual != entry.Length) throw new ConversionException("ARCHIVE_INVALID", "An archive entry is truncated.");
            files.Add((entry.FullName, path, actual));
        }
        return files;
    }
}
