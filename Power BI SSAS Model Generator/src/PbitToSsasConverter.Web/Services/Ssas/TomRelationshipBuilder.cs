using Microsoft.AnalysisServices.Tabular;
using PbitToSsasConverter.Web.Models.Conversion;
using PbitToSsasConverter.Web.Models.Intermediate;
using PbitToSsasConverter.Web.Services.Pbit;

namespace PbitToSsasConverter.Web.Services.Ssas;

public sealed class TomRelationshipBuilder(TomMetadataMapper mapper)
{
    public void Build(NormalizedRelationship source, Model model, ConversionOptions options, List<ConversionWarning> warnings)
    {
        var from = model.Tables.Find(source.FromTable)?.Columns.Find(source.FromColumn);
        var to = model.Tables.Find(source.ToTable)?.Columns.Find(source.ToColumn);
        if (from is null || to is null)
        {
            TomMetadataMapper.Warn(warnings, "RELATIONSHIP_REFERENCE", source.Name,
                $"Relationship {source.FromTable}[{source.FromColumn}] → {source.ToTable}[{source.ToColumn}] could not be generated because a referenced table or column was not found.");
            return;
        }
        if (MetadataNormalizer.Text(source.Properties, "type") is string type && !type.Equals("singleColumn", StringComparison.OrdinalIgnoreCase))
        { TomMetadataMapper.Warn(warnings, "RELATIONSHIP_TYPE", source.Name, "Only single-column relationships are supported."); return; }
        var target = new SingleColumnRelationship { Name = source.Name, FromColumn = from, ToColumn = to };
        mapper.Apply(target, MetadataNormalizer.CopyExcept(source.Properties, "type", "cardinality"), source.Name, options.CompatibilityLevel, options, warnings);
        if (MetadataNormalizer.Text(source.Properties, "cardinality") is string cardinality)
        {
            switch (cardinality.ToLowerInvariant())
            {
                case "onetomany": target.FromCardinality = RelationshipEndCardinality.One; target.ToCardinality = RelationshipEndCardinality.Many; break;
                case "manytoone": target.FromCardinality = RelationshipEndCardinality.Many; target.ToCardinality = RelationshipEndCardinality.One; break;
                case "onetoone": target.FromCardinality = target.ToCardinality = RelationshipEndCardinality.One; break;
                case "manytomany": target.FromCardinality = target.ToCardinality = RelationshipEndCardinality.Many; break;
                default: TomMetadataMapper.Warn(warnings, "RELATIONSHIP_CARDINALITY", source.Name, "Unknown cardinality; relationship omitted."); return;
            }
        }
        if (target.FromCardinality == RelationshipEndCardinality.Many && target.ToCardinality == RelationshipEndCardinality.Many && options.CompatibilityLevel < 1500)
        { TomMetadataMapper.Warn(warnings, "COMPATIBILITY", source.Name, "Many-to-many relationships require compatibility level 1500 or higher."); return; }
        model.Relationships.Add(target);
    }
}
