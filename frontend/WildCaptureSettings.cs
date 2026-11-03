using System.IO;
using System.Text;
using System.Text.Json.Nodes;
using System.Windows.Media;

namespace Chao2Harvester;

public class WildGrade : NotifyModel
{
    public string Id { get; }
    public string Label { get; }
    public Brush Foreground { get; }
    private bool enabled;
    public bool Enabled { get=>enabled; set { if(enabled==value)return;enabled=value;Change(); } }
    private double probability;
    public double Probability { get=>probability; set { if(probability.Equals(value))return;probability=value;Change(); } }
    public int DefaultProbability { get; }
    public int MinimumProbability { get; }
    public WildGrade(JsonNode spec,JsonNode? saved)
    {
        Id=spec["id"]!.GetValue<string>();Label=spec["label"]!.GetValue<string>();
        Foreground=(Brush)new BrushConverter().ConvertFromString(spec["color"]!.GetValue<string>())!;
        Enabled=saved?["enabled"]?.GetValue<bool>() ?? false;
        DefaultProbability=spec["probability"]!.GetValue<int>();
        MinimumProbability=spec["minimum_probability"]?.GetValue<int>() ?? 5;
        Probability=Math.Max(MinimumProbability,saved?["probability"]?.GetValue<int>() ?? DefaultProbability);
    }
    public JsonObject ToJson()
    {
        if(!double.IsFinite(Probability)||Probability<MinimumProbability||Probability>100||Probability%5!=0)
            throw new InvalidOperationException($"{Label}捕捉成功率必须为{MinimumProbability}%至100%，每5%一档");
        return new() { ["enabled"]=Enabled,["probability"]=(int)Probability };
    }
    public static string BrushKey(string? id)=>id switch {
        "young"=>"WildYoungBrush", "phantom"=>"WildPhantomBrush", "ultimate"=>"WildUltimateBrush",
        "immortal"=>"WildImmortalBrush", "awakened"=>"WildAwakenedBrush", _=>"WarningLogBrush" };
}

public static class WildSettingsPersistence
{
    // Change only this tool's keys; other pages may contain unfinished edits.
    public static void Save(string path,bool enabled,JsonObject rarities)
    {
        var saved=JsonNode.Parse(File.ReadAllText(path))!.AsObject();
        saved["wild_capture_enabled"]=enabled;
        saved["wild_capture"]=rarities.DeepClone();
        var pending=path+".wild.tmp";
        File.WriteAllText(pending,saved.ToJsonString(new() { WriteIndented=true }),new UTF8Encoding(false));
        File.Move(pending,path,true);
    }
}
