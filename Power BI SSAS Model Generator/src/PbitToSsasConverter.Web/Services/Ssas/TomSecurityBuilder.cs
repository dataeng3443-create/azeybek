using System.Text.Json.Nodes;
using Microsoft.AnalysisServices.Tabular;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Intermediate;
using PbitToSsasConverter.Web.Services.Pbit;

namespace PbitToSsasConverter.Web.Services.Ssas;

public sealed class TomSecurityBuilder(TomMetadataMapper mapper)
{
    public void BuildRole(NormalizedRole source, Model model, ConversionOptions options, List<ConversionWarning> warnings)
    {
        var role = new ModelRole { Name = source.Name };
        mapper.Apply(role, MetadataNormalizer.CopyExcept(source.Properties, "members"), source.Name, options.CompatibilityLevel, options, warnings);
        if (source.Properties["members"] is JsonArray { Count: > 0 })
            TomMetadataMapper.Warn(warnings, "ROLE_MEMBERS", source.Name, "Role membership must be configured for the target SSAS environment. RLS and supported OLS rules are preserved.");
        foreach (var p in source.TablePermissions.OfType<JsonObject>())
        {
            var table = model.Tables.Find(MetadataNormalizer.Name(p));
            if (table is null) throw new ConversionException("SECURITY_REFERENCE", "A role references an unavailable table. Download is blocked to avoid losing security restrictions.");
            if (options.CompatibilityLevel < 1400 && (p["metadataPermission"] is not null || p["columnPermissions"] is JsonArray { Count: > 0 }))
                throw new ConversionException("SECURITY_COMPATIBILITY", "Object-level security requires compatibility level 1400 or higher.");
            var permission = new TablePermission { Table = table, FilterExpression = MetadataNormalizer.Expression(p["filterExpression"]) };
            mapper.Apply(permission, MetadataNormalizer.CopyExcept(p, "name", "filterExpression", "columnPermissions"), source.Name, options.CompatibilityLevel, options, warnings);
            foreach (var c in MetadataNormalizer.Objects(p, "columnPermissions"))
            {
                var column = table.Columns.Find(MetadataNormalizer.Name(c));
                if (column is null) throw new ConversionException("SECURITY_REFERENCE", "A column permission references an unavailable column. Download is blocked.");
                var cp = new ColumnPermission { Column = column };
                mapper.Apply(cp, MetadataNormalizer.CopyExcept(c, "name"), source.Name, options.CompatibilityLevel, options, warnings);
                permission.ColumnPermissions.Add(cp);
            }
            role.TablePermissions.Add(permission);
        }
        model.Roles.Add(role);
    }
    public void BuildPerspective(NormalizedPerspective source, Model model, ConversionOptions options, List<ConversionWarning> warnings)
    {
        var perspective = new Perspective { Name = source.Name };
        mapper.Apply(perspective, source.Properties, source.Name, options.CompatibilityLevel, options, warnings);
        foreach (var t in source.Tables.OfType<JsonObject>())
        {
            var table = model.Tables.Find(MetadataNormalizer.Name(t));
            if (table is null) { TomMetadataMapper.Warn(warnings, "PERSPECTIVE_REFERENCE", source.Name, "An unavailable perspective table was omitted."); continue; }
            var pt = new PerspectiveTable { Table = table };
            mapper.Apply(pt, MetadataNormalizer.CopyExcept(t, "name", "columns", "measures", "hierarchies"), source.Name, options.CompatibilityLevel, options, warnings);
            foreach (var c in MetadataNormalizer.Objects(t, "columns"))
            {
                var column = table.Columns.Find(MetadataNormalizer.Name(c));
                if (column is null) TomMetadataMapper.Warn(warnings, "PERSPECTIVE_REFERENCE", source.Name, "An unavailable perspective column was omitted.");
                else pt.PerspectiveColumns.Add(new PerspectiveColumn { Column = column });
            }
            foreach (var m in MetadataNormalizer.Objects(t, "measures"))
            {
                var measure = table.Measures.Find(MetadataNormalizer.Name(m));
                if (measure is null) TomMetadataMapper.Warn(warnings, "PERSPECTIVE_REFERENCE", source.Name, "An unavailable perspective measure was omitted.");
                else pt.PerspectiveMeasures.Add(new PerspectiveMeasure { Measure = measure });
            }
            foreach (var h in MetadataNormalizer.Objects(t, "hierarchies"))
            {
                var hierarchy = table.Hierarchies.Find(MetadataNormalizer.Name(h));
                if (hierarchy is null) TomMetadataMapper.Warn(warnings, "PERSPECTIVE_REFERENCE", source.Name, "An unavailable perspective hierarchy was omitted.");
                else pt.PerspectiveHierarchies.Add(new PerspectiveHierarchy { Hierarchy = hierarchy });
            }
            perspective.PerspectiveTables.Add(pt);
        }
        model.Perspectives.Add(perspective);
    }
}
