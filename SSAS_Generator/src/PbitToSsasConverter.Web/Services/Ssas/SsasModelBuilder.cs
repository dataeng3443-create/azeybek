using Microsoft.AnalysisServices;
using Microsoft.AnalysisServices.Tabular;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Intermediate;
using PbitToSsasConverter.Web.Services.Pbit;
using Database = Microsoft.AnalysisServices.Tabular.Database;

namespace PbitToSsasConverter.Web.Services.Ssas;

public interface ISsasModelBuilder { Database Build(NormalizedPowerBiModel source, ConversionOptions options, CancellationToken ct); }
public sealed class SsasModelBuilder(TomMetadataMapper mapper, TomTableBuilder tables, TomRelationshipBuilder relationships, TomDataSourceBuilder dataSources, TomSecurityBuilder security) : ISsasModelBuilder
{
    public Database Build(NormalizedPowerBiModel source, ConversionOptions options, CancellationToken ct)
    {
        TomValidator.ValidateNormalized(source, options);
        var db = new Database { Name = source.Name, ID = source.Name, CompatibilityLevel = options.CompatibilityLevel, Model = new Model { Culture = source.Culture }, StorageEngineUsed = StorageEngineUsed.TabularMetadata };
        try
        {
            mapper.Apply(db.Model, source.Properties, "Model", options.CompatibilityLevel, options, source.Warnings);
            foreach (var ds in source.DataSources)
            {
                ct.ThrowIfCancellationRequested();
                var target = dataSources.Build(ds, options, source.Warnings);
                if (target is not null) db.Model.DataSources.Add(target);
            }
            foreach (var expression in source.Expressions)
            {
                if (options.CompatibilityLevel < 1400) { TomMetadataMapper.Warn(source.Warnings, "COMPATIBILITY", expression.Name, "Named M expressions require compatibility level 1400 or higher."); continue; }
                var target = new NamedExpression { Name = expression.Name, Expression = expression.Expression };
                mapper.Apply(target, expression.Properties, expression.Name, options.CompatibilityLevel, options, source.Warnings);
                db.Model.Expressions.Add(target);
                if (expression.Expression is not null) TomPartitionBuilder.InspectExpression(expression.Expression, expression.Name, source.Warnings);
            }
            foreach (var table in source.Tables)
            {
                ct.ThrowIfCancellationRequested();
                tables.Build(table, db, options, source.Warnings);
            }
            foreach (var table in source.Tables) tables.Resolve(table, db.Model.Tables[table.Name], options, source.Warnings);
            foreach (var relationship in source.Relationships) { ct.ThrowIfCancellationRequested(); relationships.Build(relationship, db.Model, options, source.Warnings); }
            foreach (var role in source.Roles) security.BuildRole(role, db.Model, options, source.Warnings);
            foreach (var perspective in source.Perspectives) security.BuildPerspective(perspective, db.Model, options, source.Warnings);
            if (!options.PreserveHiddenObjects) TomMetadataMapper.Warn(source.Warnings, "HIDDEN_OBJECTS_RETAINED", "Model", "Hidden objects were retained because removing them could invalidate DAX, RLS and relationship dependencies.");
            return db;
        }
        catch { db.Dispose(); throw; }
    }
}
