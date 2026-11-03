using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;

namespace Chao2Harvester;

public class NotifyModel : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;
    protected void Change([CallerMemberName] string? name = null) => PropertyChanged?.Invoke(this,new(name));
}
public class OptionRow : NotifyModel
{
    public string Id { get; }
    public string Label { get; }
    private bool enabled;
    private double limit;
    public bool Enabled { get => enabled; set { enabled=value;Change(); } }
    public double Limit { get => limit; set { limit=value;Change(); } }
    public bool Counts { get; }
    public Visibility CountVisibility => Counts ? Visibility.Visible : Visibility.Collapsed;
    public ObservableCollection<OptionRow> Parent { get; }
    public OptionRow(JsonNode spec, JsonNode value, bool counts, ObservableCollection<OptionRow> parent)
    {
        Id=spec["id"]!.GetValue<string>();Label=spec["label"]!.GetValue<string>();
        Enabled=value["enabled"]!.GetValue<bool>();Limit=value["limit"]?.GetValue<int>() ?? 0;
        Counts=counts;Parent=parent;
    }
    public JsonObject ToJson()
    {
        if (double.IsNaN(Limit) || Limit<0 || Limit>100 || Limit%1!=0) throw new InvalidOperationException("次数必须为0至100的整数");
        var row=new JsonObject { ["id"]=Id,["label"]=Label,["enabled"]=Enabled };
        if(Counts)row["limit"]=(int)Limit;
        return row;
    }
}
public class TaskOption : NotifyModel
{
    public string Key { get; }
    public string Label { get; }
    public string Type { get; }
    public double Min { get; }
    public double Max { get; }
    public bool Counts { get; }
    public string Description { get; }
    public string Notice { get; }
    public Visibility NoticeVisibility=>string.IsNullOrEmpty(Notice)?Visibility.Collapsed:Visibility.Visible;
    public string? EnabledWhen { get; }
    public string? EnabledValue { get; }
    private TaskOption? dependency;
    public bool IsAvailable => dependency is null || ((EnabledValue is null ? dependency.Checked : dependency.ChoiceId==EnabledValue) && dependency.IsAvailable);
    public double Indent { get; }
    public string Group { get; }
    public bool Compact { get; }
    public Thickness OptionMargin => new(Compact?Math.Min(Indent,18):Indent,0,0,Compact?2:8);
    public string AddLabel { get; }
    private bool checkValue;
    public bool Checked { get=>checkValue; set { if(checkValue==value)return;checkValue=value;Change(); } }
    private double number;
    private string choiceId="";
    public double Number { get=>number; set { if(number.Equals(value))return;number=value;Change(); } }
    public string ChoiceId { get=>choiceId; set { if(choiceId==value)return;choiceId=value;Change(); } }
    public List<OptionChoice> Choices { get; }=[];
    public ObservableCollection<OptionRow> Rows { get; }=[];
    public ObservableCollection<TeamRow> Teams { get; }=[];
    public ObservableCollection<StageRow> Stages { get; }=[];
    public List<StageChoice> StageChoices { get; }=[];
    public bool CanAddStage => Stages.Count < StageChoices.Count;
    public Visibility EmptyStagesVisibility => Stages.Count==0 ? Visibility.Visible : Visibility.Collapsed;
    public bool CanAddTeam => Teams.Count < Max;
    public Visibility EmptyTeamsVisibility => Teams.Count==0 ? Visibility.Visible : Visibility.Collapsed;
    public Visibility BoolVisibility => Type=="bool" ? Visibility.Visible : Visibility.Collapsed;
    public Visibility NumberVisibility => Type=="number" ? Visibility.Visible : Visibility.Collapsed;
    public Visibility ChoiceVisibility => Type=="choice" ? Visibility.Visible : Visibility.Collapsed;
    public Visibility OrderVisibility => Type=="order" ? Visibility.Visible : Visibility.Collapsed;
    public Visibility TeamsVisibility => Type=="teams" ? Visibility.Visible : Visibility.Collapsed;
    public Visibility StagesVisibility => Type=="stages" ? Visibility.Visible : Visibility.Collapsed;
    public Visibility CountHintVisibility => Counts ? Visibility.Visible : Visibility.Collapsed;
    public TaskOption(JsonNode spec, JsonNode? saved, bool legacyDefaults=false)
    {
        Key=spec["key"]!.GetValue<string>();Label=spec["label"]!.GetValue<string>();Type=spec["type"]!.GetValue<string>();
        Min=spec["min"]?.GetValue<double>() ?? 0;Max=spec["max"]?.GetValue<double>() ?? 100;
        Counts=spec["counts"]?.GetValue<bool>() ?? false;
        Description=spec["description"]?.GetValue<string>() ?? "";
        Notice=spec["notice"]?.GetValue<string>() ?? "";
        EnabledWhen=spec["enabled_when"]?.GetValue<string>();
        EnabledValue=spec["enabled_value"]?.GetValue<string>();
        Indent=spec["indent"]?.GetValue<double>() ?? (EnabledWhen=="refresh_tasks" ? 18 : 0);
        Group=spec["group"]?.GetValue<string>() ?? Key;
        Compact=spec["compact"]?.GetValue<bool>() ?? false;
        AddLabel=spec["add_label"]?.GetValue<string>() ?? "添加项目";
        var value=saved ?? spec["default"]!;
        if(Type=="bool")Checked=value.GetValue<bool>();
        else if(Type=="number")Number=value.Deserialize<double>();
        else if(Type=="choice")
        {
            foreach(var choice in spec["choices"]!.AsArray())
                Choices.Add(new(choice!["id"]!.GetValue<string>(),choice["label"]!.GetValue<string>()));
            ChoiceId=value.GetValue<string>();
        }
        else if(Type=="teams")
        {
            foreach(var row in value.AsArray())
            {
                // Version 2 had five checkbox slots; keep only enabled entries.
                if(row is JsonObject legacy)
                {
                    if(legacy["enabled"]!.GetValue<bool>())Teams.Add(new(int.Parse(legacy["id"]!.ToString()),this));
                }
                else Teams.Add(new(row!.GetValue<int>(),this));
            }
            Teams.CollectionChanged+=(_,_)=>TeamsChanged();
        }
        else if(Type=="order")
        {
            var defaults=spec["default"]!.AsArray();
            foreach(var row in value.AsArray())
            {
                var canonical=defaults.FirstOrDefault(x=>x!["id"]!.ToString()==row!["id"]!.ToString());
                if(canonical is not null)Rows.Add(new(canonical,row!,Counts,Rows));
            }
            foreach(var row in defaults)
                if(!Rows.Any(x=>x.Id==row!["id"]!.ToString()))Rows.Add(new(row!,row!,Counts,Rows));
        }
        else if(Type=="stages")
        {
            foreach(var choice in spec["choices"]!.AsArray())
                StageChoices.Add(new(choice!["id"]!.GetValue<string>(),choice["label"]!.GetValue<string>(),choice["limit"]?.GetValue<int>() ?? 0,
                    choice["reward"]?.GetValue<string>() ?? "",choice["reward_icon"]?.GetValue<string>()));
            foreach(var row in value.AsArray())
            {
                var choice=StageChoices.FirstOrDefault(c=>c.Id==row!["id"]!.GetValue<string>());
                if(choice is null || row!["enabled"]?.GetValue<bool>()==false)continue;
                int limit=row!["limit"]?.GetValue<int>() ?? choice.DefaultLimit;
                if(legacyDefaults && limit==0 && choice.Id.StartsWith("lower_"))limit=choice.DefaultLimit;
                Stages.Add(new(choice.Id,limit,this));
            }
            Stages.CollectionChanged+=(_,_)=>StagesChanged();
        }
    }
    public void BindDependency(IEnumerable<TaskOption> options)
    {
        if(EnabledWhen is null)return;
        dependency=options.First(o=>o.Key==EnabledWhen);
        dependency.PropertyChanged+=(_,e)=> { if(e.PropertyName is nameof(Checked) or nameof(ChoiceId) or nameof(IsAvailable))Change(nameof(IsAvailable)); };
        Change(nameof(IsAvailable));
    }
    public void AddTeam()
    {
        if(!CanAddTeam)return;
        int next=Enumerable.Range((int)Min,(int)(Max-Min+1)).First(n=>Teams.All(t=>t.TeamId!=n));
        Teams.Add(new(next,this));
    }
    public void RemoveTeam(TeamRow row)=>Teams.Remove(row);
    public void TeamsChanged()
    {
        Change(nameof(CanAddTeam));Change(nameof(EmptyTeamsVisibility));
        foreach(var row in Teams)row.RefreshChoices();
    }
    public void AddStage()
    {
        if(!CanAddStage)return;
        var next=StageChoices.First(c=>Stages.All(r=>r.Id!=c.Id));
        Stages.Add(new(next.Id,next.DefaultLimit,this));
    }
    public void RemoveStage(StageRow row)=>Stages.Remove(row);
    public void StagesChanged()
    {
        Change(nameof(CanAddStage));Change(nameof(EmptyStagesVisibility));
        foreach(var row in Stages)row.RefreshChoices();
    }
    public JsonNode ToJson()
    {
        if(Type=="bool")return JsonValue.Create(Checked)!;
        if(Type=="choice")
        {
            if(Choices.All(c=>c.Id!=ChoiceId))throw new InvalidOperationException(Label+"：请选择有效项目");
            return JsonValue.Create(ChoiceId)!;
        }
        if(Type=="order")return new JsonArray(Rows.Select(x=>(JsonNode)x.ToJson()).ToArray());
        if(Type=="stages")
        {
            if(Stages.Select(r=>r.Id).Distinct().Count()!=Stages.Count || Stages.Any(r=>StageChoices.All(c=>c.Id!=r.Id)))
                throw new InvalidOperationException("副本不能重复或使用未知项目");
            return new JsonArray(Stages.Select(r=>(JsonNode)r.ToJson()).ToArray());
        }
        if(Type=="teams")
        {
            var ids=Teams.Select(t=>t.TeamId).ToArray();
            if(ids.Length>Max||ids.Distinct().Count()!=ids.Length||ids.Any(i=>i<Min||i>Max))throw new InvalidOperationException("队伍序号必须为1至5且不能重复");
            return new JsonArray(ids.Select(i=>(JsonNode?)JsonValue.Create(i)).ToArray());
        }
        if(double.IsNaN(Number)||Number<Min||Number>Max||Number%1!=0)throw new InvalidOperationException(Label+"：请输入范围内整数");
        return JsonValue.Create((int)Number)!;
    }
}

public sealed class TaskOptionSection(IEnumerable<TaskOption> options)
{
    private readonly TaskOption[] options=options.ToArray();
    public TaskOption Toggle=>options[0];
    public IEnumerable<TaskOption> Details=>options.Skip(1);
    public Visibility DetailsVisibility=>options.Length>1?Visibility.Visible:Visibility.Collapsed;
    public Visibility SingleVisibility=>options.Length==1?Visibility.Visible:Visibility.Collapsed;
}

public record OptionChoice(string Id,string Label);
public record StageChoice(string Id,string Label,int DefaultLimit,string Reward="",string? IconFile=null)
{
    public string? RewardIcon=>IconFile is null ? null : "pack://application:,,,/rewards/"+IconFile;
    public Visibility IconVisibility=>IconFile is null ? Visibility.Collapsed : Visibility.Visible;
}
public class StageRow(string id,double limit,TaskOption owner) : NotifyModel
{
    private string id=id;
    private double limit=limit;
    public TaskOption Owner { get; }=owner;
    public string Id
    {
        get=>id;
        set
        {
            if(string.IsNullOrEmpty(value)||value==id||Owner.Stages.Any(r=>r!=this&&r.Id==value))return;
            var choice=Owner.StageChoices.FirstOrDefault(c=>c.Id==value);
            if(choice is null)return;
            id=value;Limit=choice.DefaultLimit;Change();Change(nameof(Label));Owner.StagesChanged();
        }
    }
    public string Label=>Owner.StageChoices.First(c=>c.Id==Id).Label;
    public double Limit { get=>limit; set { limit=value;Change(); } }
    public Visibility CountVisibility=>Owner.Counts?Visibility.Visible:Visibility.Collapsed;
    public IEnumerable<StageChoice> Choices=>Owner.StageChoices.Where(c=>c.Id==Id||Owner.Stages.All(r=>r.Id!=c.Id));
    public void RefreshChoices()=>Change(nameof(Choices));
    public JsonObject ToJson()
    {
        if(Owner.Counts&&(double.IsNaN(Limit)||Limit<0||Limit>100||Limit%1!=0))throw new InvalidOperationException("副本次数必须为0至100的整数");
        var value=new JsonObject { ["id"]=Id,["label"]=Label,["enabled"]=true };
        if(Owner.Counts)value["limit"]=(int)Limit;
        return value;
    }
}

public record TeamChoice(int Id,string Label);
public class TeamRow(int teamId,TaskOption owner) : NotifyModel
{
    private int teamId=teamId;
    public TaskOption Owner { get; }=owner;
    public int TeamId
    {
        get=>teamId;
        set { if(value<Owner.Min||value>Owner.Max||value==teamId)return;teamId=value;Change();Owner.TeamsChanged(); }
    }
    public IEnumerable<TeamChoice> Choices=>Enumerable.Range((int)Owner.Min,(int)(Owner.Max-Owner.Min+1))
        .Where(n=>n==TeamId||Owner.Teams.All(t=>t.TeamId!=n)).Select(n=>new TeamChoice(n,"队伍 "+n));
    public void RefreshChoices()=>Change(nameof(Choices));
}
