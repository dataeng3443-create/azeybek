using System.Text;
using PbitToSsasConverter.Web.Models.Pbit;

namespace PbitToSsasConverter.Web.Services.Pbit;

public sealed class PbitPackageInspector
{
    public async Task<PbitArtifact> InspectAsync(string name, string path, long length, CancellationToken ct)
    {
        await using var stream = File.OpenRead(path);
        var sample = new byte[(int)Math.Min(length, 4096)];
        await stream.ReadExactlyAsync(sample, ct);
        var encoding = DetectEncoding(sample);
        // A fixed-size inspection sample can end inside a Unicode code point.
        var sampleEncoding = Encoding.GetEncoding(encoding.CodePage, EncoderFallback.ReplacementFallback, DecoderFallback.ReplacementFallback);
        var text = sampleEncoding.GetString(sample).TrimStart('\uFEFF', ' ', '\r', '\n', '\t');
        var kind = text.StartsWith('{') || text.StartsWith('[') ? "json" :
            text.StartsWith("section ", StringComparison.Ordinal) ? "m-section" :
            sample.Length > 3 && sample[0] == 0x50 && sample[1] == 0x4b ? "zip" : "binary-or-text";
        return new(name, path, length, kind, encoding.WebName);
    }
    public static Encoding DetectEncoding(ReadOnlySpan<byte> bytes)
    {
        if (bytes.Length >= 4 && bytes[0] == 0 && bytes[1] == 0 && bytes[2] == 0xfe && bytes[3] == 0xff) return new UTF32Encoding(true, true, true);
        if (bytes.Length >= 4 && bytes[0] == 0xff && bytes[1] == 0xfe && bytes[2] == 0 && bytes[3] == 0) return new UTF32Encoding(false, true, true);
        if (bytes.Length >= 2 && bytes[0] == 0xff && bytes[1] == 0xfe) return new UnicodeEncoding(false, true, true);
        if (bytes.Length >= 2 && bytes[0] == 0xfe && bytes[1] == 0xff) return new UnicodeEncoding(true, true, true);
        if (bytes.Length >= 4 && bytes[1] == 0 && bytes[3] == 0) return new UnicodeEncoding(false, false, true);
        if (bytes.Length >= 4 && bytes[0] == 0 && bytes[2] == 0) return new UnicodeEncoding(true, false, true);
        return new UTF8Encoding(false, true);
    }
}
