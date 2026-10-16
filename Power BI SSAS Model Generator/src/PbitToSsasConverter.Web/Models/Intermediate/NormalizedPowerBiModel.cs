using System.Text.Json.Nodes;
using PbitToSsasConverter.Web.Models.Conversion;

namespace PbitToSsasConverter.Web.Models.Intermediate;

// Neutral metadata only: this layer has no dependency on TOM or ZIP packages.
public abstract class NormalizedObject
{
    public string Name { get; set; } = "";
    public JsonObject Properties { get; set; } = new();
}
public sealed class NormalizedPowerBiModel : NormalizedObject
{
    public string Culture { get; set; } = "en-US";
    public List<NormalizedTable> Tables { get; } = [];
    public List<NormalizedDataSource> DataSources { get; } = [];
    public List<NormalizedRelationship> Relationships { get; } = [];
    public List<NormalizedRole> Roles { get; } = [];
    public List<NormalizedPerspective> Perspectives { get; } = [];
    public List<NormalizedExpression> Expressions { get; } = [];
    public List<ConversionWarning> Warnings { get; } = [];
}
public sealed class NormalizedTable : NormalizedObject
{
    public List<NormalizedColumn> Columns { get; } = [];
    public List<NormalizedMeasure> Measures { get; } = [];
    public List<NormalizedPartition> Partitions { get; } = [];
    public List<NormalizedHierarchy> Hierarchies { get; } = [];
    public JsonObject? CalculationGroup { get; set; }
}
public sealed class NormalizedColumn : NormalizedObject
{
    public string Kind { get; set; } = "data";
    public string? Expression { get; set; }
    public string? SortByColumn { get; set; }
}
public sealed class NormalizedMeasure : NormalizedObject { public string? Expression { get; set; } }
public sealed class NormalizedPartition : NormalizedObject
{
    public string Kind { get; set; } = "";
    public string Mode { get; set; } = "import";
    public string? Expression { get; set; }
    public string? DataSource { get; set; }
    public JsonObject SourceProperties { get; set; } = new();
}
public sealed class NormalizedHierarchy : NormalizedObject { public List<NormalizedLevel> Levels { get; } = []; }
public sealed class NormalizedLevel : NormalizedObject { public string Column { get; set; } = ""; public int Ordinal { get; set; } }
public sealed class NormalizedRelationship : NormalizedObject
{
    public string FromTable { get; set; } = "";
    public string FromColumn { get; set; } = "";
    public string ToTable { get; set; } = "";
    public string ToColumn { get; set; } = "";
}
public sealed class NormalizedDataSource : NormalizedObject { public string Kind { get; set; } = "provider"; }
public sealed class NormalizedRole : NormalizedObject { public JsonArray TablePermissions { get; set; } = []; }
public sealed class NormalizedPerspective : NormalizedObject { public JsonArray Tables { get; set; } = []; }
public sealed class NormalizedExpression : NormalizedObject { public string? Expression { get; set; } }
