# Power BI PBIT → SSAS Model.bim Converter

A .NET 8 / ASP.NET Core Blazor Server application that reads Power BI template packages, extracts available semantic JSON metadata, creates a real Microsoft Tabular Object Model (TOM) database, and returns a validated `Model.bim` plus `conversion-report.json`. No model objects, queries, connections or expressions are invented when extraction fails.

## Build and run

Prerequisites: .NET 8 SDK (8.0.400 or newer 8.0 feature band) and NuGet access on first restore. SQL Server, Power BI Desktop and Visual Studio are **not required to run the converter**. Windows plus the Analysis Services Projects extension for Visual Studio are needed for the intended SSDT deployment workflow.

From the solution directory:

```sh
dotnet restore
dotnet build
dotnet test
dotnet run --project src/PbitToSsasConverter.Web
```

Open http://localhost:5200. Alternatively, `cd src/PbitToSsasConverter.Web` and run `dotnet run`.

1. Select or drag one `.pbit` file into the upload area.
2. Choose a target SSAS version (default SQL Server 2019 / 1500). Use **Custom compatibility level** for 1400, 1600 (SQL Server 2022) or 1700 (SQL Server 2025).
3. Generate the model; stages reflect real work rather than a timer.
4. Inspect warnings and download `Model.bim` and the conversion report.
5. In a matching Analysis Services Tabular Project, replace `Model.bim` and use F7 / View Code. Configure target credentials and test processing on SSAS.

`samples/SyntheticDemo.pbit` is a deliberately synthetic ZIP/schema fixture for trying the interface. It is not an export from Power BI Desktop and contains no customer data. Its external source paths are examples, not working connections.

## Architecture

```text
Blazor InputFile → IModelConversionService → isolated temporary package
  → ISemanticModelSourceReader / PbitSourceReader
  → IPbitPackageReader / SecureArchiveExtractor / PbitPackageInspector
  → IPbitModelExtractionStrategy pipeline
  → MetadataNormalizer → NormalizedPowerBiModel
  → ISsasModelBuilder → TOM Database / Model
  → tables, columns, measures, partitions, hierarchies, relationships, roles, perspectives
  → TomValidator → TOM serialization → TOM deserialization → validation
  → short-lived download storage + conversion report
```

The intermediate model is independent of TOM and archive APIs. `ISemanticModelSourceReader` is the extension point for PBIX, PBIP, TMDL or existing BIM readers. Only PBIT is enabled in this release. Full `.smproj` generation is not included; `Model.bim` is the required deliverable.

## PBIT extraction

The reader verifies a ZIP header and enumerates every archive entry. It does not require one internal filename. Content inspection detects JSON, UTF-8, UTF-16 LE/BE (including BOM-less UTF-16), UTF-32 and recognizable mashup sections. The JSON strategy searches recognized schema wrappers and semantic table structure in all JSON artifacts, including unexpectedly named entries.

Schema candidates are ranked by semantic structure. Named objects from complementary artifacts are merged; conflicting versions retain the primary definition and produce a warning. Expressions represented as line arrays are joined with newline separators. DAX, SQL and M are never reparsed or rewritten, except recognizable credential values are redacted and reported.

The mashup strategy explicitly reports standalone/binary mashup content as an unsupported extraction path. It does **not** execute M, deserialize arbitrary binary objects, decode an undocumented binary model by guessing, or fabricate table/query associations. When readable semantic JSON contains M partitions and shared expressions, those are converted even if an additional binary DataMashup entry exists.

## TOM output and compatibility

The project references the current multi-runtime `Microsoft.AnalysisServices` package, version 19.114.12, and uses `Microsoft.AnalysisServices.Tabular`. It does not use the obsolete Framework-only `Microsoft.AnalysisServices.Tabular` NuGet package.

Database, Model, Table, DataColumn, CalculatedColumn, CalculatedTableColumn, Measure, Partition, SingleColumnRelationship, DataSource, Hierarchy, Level, CalculationGroup, ModelRole and Perspective are created as TOM objects. Scalar supported metadata is applied through a guarded TOM property mapper. Structured connection details use TOM's `ConnectionDetails`. Unknown metadata is reported instead of being blindly copied into the BIM schema.

`JsonSerializer.SerializeDatabase` produces the database definition. System.Text.Json only provides neutral metadata parsing, report generation and final pretty formatting. Before download, the generated UTF-8 JSON is deserialized using TOM with `CompatibilityMode.AnalysisServices` and validated again. Outputs are database definitions, not `createOrReplace` commands.

| Target | Compatibility |
| --- | --- |
| SQL Server 2016 SSAS | 1200 |
| SQL Server 2019 SSAS (default) | 1500 |
| Custom, supported on-premises levels | 1200, 1400, 1500, 1600, 1700 |

Custom does not mean arbitrary integers or Power BI-only intermediate compatibility levels. M/structured sources and OLS require at least 1400; calculation groups and many-to-many relationships require at least 1500. Lineage tags and dynamic formats are guarded on down-conversion. Newer features that TOM cannot represent fail validation or produce explicit warnings. A target downgrade can leave no usable partition; in that case download is blocked rather than generating an empty fake source.

## Supported metadata

- Tables, descriptions, hidden flags, source columns, keys, data categories, formatting, annotations and supported scalar properties.
- Data columns, DAX calculated columns, calculated table columns and calculated partitions.
- Measures, original DAX, format strings, dynamic measure formats, display folders and hidden state.
- M, SQL query, calculated and calculation-group partition sources; Import and DirectQuery modes.
- Named M expressions and source expressions containing SQL, Excel, CSV, Folder, Web, OData or other connectors, without executing them.
- Provider data sources and structured connection details; credentials must be configured on the server.
- Active/inactive one-to-many, many-to-one, one-to-one and many-to-many single-column relationships; filtering, security filtering and referential-integrity flags.
- SortByColumn references, hierarchy level order, perspectives and calculation group items/precedence/format expressions.
- RLS table expressions and supported object-level table/column permissions. Role membership is reported for target-specific reconfiguration.

## Partial support and explicit exclusions

- Binary-only DataModel/DataMashup, encrypted packages and undocumented legacy encodings cannot be recovered without a readable semantic JSON schema. Re-exporting a current PBIT may expose a supported path.
- Power BI Service / Fabric bindings, Direct Lake, remote semantic models, composite behavior, visual calculations, report objects, refresh policies, query groups and unsupported metadata are reported. No artificial SSAS equivalent is created.
- Automatic date/time tables are retained with warnings. Field parameter annotations/extended metadata and Power BI annotations cannot recreate Power BI UI behavior in SSAS.
- Connector execution, gateway settings, authentication, network access, source files, native providers and SQL server availability are not verified. External file paths need access from the SSAS service account.
- Unknown complex metadata, translations/cultures, KPI/detail-row definitions, aggregations, refresh-policy generated partitions and advanced selection expressions are reported when they cannot be mapped. Conflicting definitions from different artifacts are not reconciled by guessing.
- Missing optional relationship/hierarchy/perspective references are omitted with warnings; broken partition structure or security restrictions block BIM download. Hidden objects are retained even if an API caller requests their removal, with a warning, because removal can break DAX and RLS dependencies.
- Local TOM round-trip is schema/reference validation, **not** proof that SSDT opens every real model, DAX compiles, M executes, or SSAS deploys/processes it. Those checks require actual customer templates and a target Windows/SSAS environment. Reports state these checks were not performed.

## Safety, retention and configuration

`src/PbitToSsasConverter.Web/appsettings.json` controls limits. Defaults: 500 MiB upload, 2 GiB extracted data, 128 MiB per metadata artifact, 256 MiB total parsed metadata, 10,000 entries, compression ratio 1000, 10-minute processing limit, two concurrent conversions, 512 MiB retained downloads and 30-minute download lifetime.

- Archive paths are checked before any extraction, including traversal, absolute paths, Windows drive syntax, case-insensitive duplicates and symbolic links. Both declared and actual decompressed byte counts are limited.
- Uploaded packages are never executed. Files are extracted only into a per-job GUID directory with user-only Unix directory permissions, then removed in `finally` on success, failure or cancellation.
- Old crash leftovers are cleaned at startup; outputs live only in bounded process memory and are purged every 30 seconds. Restarting the app invalidates all downloads.
- Downloads use cryptographically random 256-bit capability tokens and `Cache-Control: no-store`. Treat a download link as access to that model; keep it private. Tokens do not replace organization authentication.
- Credential objects and recognizable password/token/key assignments are removed. Arbitrary secrets disguised in DAX, SQL, annotations or custom encodings cannot be reliably classified. Review metadata before sharing or deploying it. Redaction warnings identify affected metadata paths without echoing secrets.
- Logs use structured event names, job IDs, object counts, exception types and stack locations. Raw third-party exception messages and source expressions are deliberately excluded because they can contain secrets.
- Cancellation is cooperative. ZIP and upload I/O observe cancellation directly; synchronous TOM work is checked before/after the SDK calls and cannot be forcibly interrupted inside a vendor method. For hostile multi-tenant use, add a separately supervised worker process/container with hard memory/CPU/time limits.
- The default development listener is loopback. Before hosting for multiple users, configure HTTPS and organization authentication at the reverse proxy, appropriate `AllowedHosts`, connection/rate limits and per-user quotas. Blazor Server requires WebSocket support and session affinity; the current download store is single-process.

Environment overrides follow .NET configuration conventions, for example `Conversion__MaxUploadBytes`, `Conversion__TempRoot` and `AllowedHosts`.

## Tests and release build

```sh
dotnet test PbitToSsasConverter.sln
dotnet publish src/PbitToSsasConverter.Web -c Release -o publish
dotnet publish src/PbitToSsasConverter.Web -c Release -r win-x64 --self-contained false -o publish/windows
```

Unit tests cover archive defenses, file validation, type mappings, DAX/M preservation, relationships, calculated objects, calculation groups, data sources, security, hierarchies, perspectives, compatibility warnings and TOM round-trip. Integration tests exercise the complete ZIP→TOM pipeline, safe error reports, real HTTP download routes, missing tokens, retention capacity and the rendered home page. Fixtures are synthetic and explicitly labeled; no real PBIT or SSAS server was provided with the project brief.

The included Dockerfile publishes to a non-root .NET 8 runtime image. Example: `docker build -t pbit-to-ssas .` and `docker run --rm -p 127.0.0.1:5200:8080 pbit-to-ssas`. Container execution is an alternative; Docker is not required for local .NET development.

## References

- [Microsoft Analysis Services client libraries](https://learn.microsoft.com/en-us/analysis-services/client-libraries)
- [Microsoft.AnalysisServices NuGet package](https://www.nuget.org/packages/Microsoft.AnalysisServices/19.114.12)
- [Analysis Services compatibility levels](https://learn.microsoft.com/en-us/analysis-services/tabular-models/compatibility-level-for-tabular-models-in-analysis-services)
- [TOM database JSON deserialization](https://learn.microsoft.com/en-us/dotnet/api/microsoft.analysisservices.tabular.jsonserializer.deserializedatabase)

Bootstrap 5.3.8 is vendored locally under `wwwroot/lib/bootstrap`; its MIT license notice is preserved in the distribution file. The application makes no runtime request to a CSS CDN.
