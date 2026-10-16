using Microsoft.Extensions.Options;
using PbitToSsasConverter.Web.Components;
using PbitToSsasConverter.Web.Infrastructure;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Services.Conversion;
using PbitToSsasConverter.Web.Services.Pbit;
using PbitToSsasConverter.Web.Services.Pbit.Strategies;
using PbitToSsasConverter.Web.Services.Ssas;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddRazorComponents().AddInteractiveServerComponents(options => options.DetailedErrors = false);
builder.Services.AddOptions<ConversionLimits>().BindConfiguration("Conversion")
    .Validate(x => x.MaxUploadBytes > 0 && x.MaxExtractedBytes > 0 && x.MaxArtifactBytes > 0 && x.MaxArtifactBytes <= int.MaxValue && x.MaxTotalMetadataBytes > 0 && x.MaxEntries > 0 && x.MaxCompressionRatio > 0 && x.ProcessingTimeoutSeconds > 0 && x.DownloadRetentionMinutes > 0 && x.MaxConcurrentConversions > 0 && x.MaxRetainedOutputBytes > 0, "Conversion limits must be positive and artifact parsing must fit in memory.").ValidateOnStart();
builder.Services.AddSingleton<ConversionJobManager>();
builder.Services.AddSingleton<TempFileManager>();
builder.Services.AddHostedService<CleanupWorker>();
builder.Services.AddTransient<SecureArchiveExtractor>();
builder.Services.AddTransient<PbitPackageInspector>();
builder.Services.AddTransient<IPbitPackageReader, PbitPackageReader>();
builder.Services.AddTransient<IPbitModelExtractionStrategy, JsonModelSchemaExtractionStrategy>();
builder.Services.AddTransient<IPbitModelExtractionStrategy, MashupExtractionStrategy>();
builder.Services.AddTransient<CredentialSanitizer>();
builder.Services.AddTransient<MetadataNormalizer>();
builder.Services.AddTransient<IPbitModelExtractor, PbitModelExtractor>();
builder.Services.AddTransient<ISemanticModelSourceReader, PbitSourceReader>();
builder.Services.AddTransient<TomMetadataMapper>();
builder.Services.AddTransient<TomPartitionBuilder>();
builder.Services.AddTransient<TomTableBuilder>();
builder.Services.AddTransient<TomDataSourceBuilder>();
builder.Services.AddTransient<TomRelationshipBuilder>();
builder.Services.AddTransient<TomSecurityBuilder>();
builder.Services.AddTransient<TomValidator>();
builder.Services.AddTransient<ModelBimSerializer>();
builder.Services.AddTransient<ISsasModelBuilder, SsasModelBuilder>();
builder.Services.AddTransient<IModelConversionService, ModelConversionService>();
builder.WebHost.ConfigureKestrel(o => o.Limits.MaxRequestBodySize = builder.Configuration.GetValue<long?>("Conversion:MaxUploadBytes") ?? 524288000);
var app = builder.Build();
if (!app.Environment.IsDevelopment()) app.UseExceptionHandler("/error");
app.Use(async (context, next) =>
{
    context.Response.Headers["X-Content-Type-Options"] = "nosniff";
    context.Response.Headers["Referrer-Policy"] = "no-referrer";
    context.Response.Headers["X-Frame-Options"] = "DENY";
    await next();
});
app.UseStaticFiles();
app.UseAntiforgery();
app.MapGet("/downloads/{token}/{kind}", (string token, string kind, ConversionJobManager jobs, HttpContext context) =>
{
    context.Response.Headers.CacheControl = "no-store";
    var artifact = jobs.Get(token, kind);
    return artifact is null ? Results.NotFound("This download has expired or is unavailable. Convert the PBIT again.") : Results.File(artifact.Bytes, "application/json; charset=utf-8", artifact.Name);
});
app.MapGet("/health", () => Results.Ok(new { status = "healthy" }));
app.MapRazorComponents<App>().AddInteractiveServerRenderMode();
app.Run();
public partial class Program;
