# Validation record

Validated on macOS ARM64 with .NET SDK 8.0.425 and Microsoft.AnalysisServices 19.114.12.

- Release build: successful, zero compiler warnings/errors.
- Unit tests: 56 passed.
- ASP.NET Core integration tests: 8 passed.
- Total: 64 passed, zero failed, zero skipped.
- Release publish: successful.
- Complete synthetic ZIP package conversion and TOM round-trip: passed at 1500, 1600 and 1700.
- Browser file chooser upload → conversion → summary → expanded warnings → Model.bim download: passed against the published Release application.
- Browser corrupt-PBIT flow: safe error, report available, BIM download disabled; Convert Another File resets the form.
- Responsive layout: checked at 390 px; document width equals viewport width with no horizontal overflow.
- Supported calculations, calculation groups, provider/structured data sources, query/DirectQuery partitions, RLS/OLS, sort/hierarchy references, annotation preservation and credential redaction: covered by tests.
- Zip Slip, symlink, duplicate path, size/count/ratio limits, invalid ZIP, Unicode detection, malformed artifact recovery, total metadata budget and expired download cleanup: covered by tests.

All model fixtures are synthetic. A customer Power BI Desktop PBIT export, Visual Studio SSDT and an SSAS server were not available, so real-template acceptance, SSDT opening, DAX/M execution, deployment and processing are not claimed as verified. Docker configuration is included but was not run in this environment.
