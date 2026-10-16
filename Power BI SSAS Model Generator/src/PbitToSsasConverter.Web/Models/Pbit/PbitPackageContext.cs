using System.Text.Json.Nodes;

namespace PbitToSsasConverter.Web.Models.Pbit;

public sealed record PbitArtifact(string EntryName, string Path, long Length, string Kind, string? EncodingName);
public sealed record PbitPackageContext(Guid JobId, string Directory, IReadOnlyList<PbitArtifact> Artifacts);
public sealed record ExtractedModel(JsonObject Schema, string Artifact, int Priority);
public sealed record ModelSource(string FileName, Stream Content);
