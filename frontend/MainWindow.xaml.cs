using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace Chao2Harvester;

public class TaskItem(string key, string name, string description, bool enabled) : INotifyPropertyChanged
{
    public string Key { get; } = key;
    public string InstanceId { get; init; } = key;
    private string name = name;
    public string Name { get=>name; set { if(name==value)return;name=value;Changed(); } }
    public string Description { get; } = description;
    public string Hint { get; set; } = "";
    public ObservableCollection<TaskOption> Options { get; }=[];
    public Visibility ForestVisibility => Key=="forest"?Visibility.Visible:Visibility.Collapsed;
    public Visibility NonForestVisibility => Key=="forest"?Visibility.Collapsed:Visibility.Visible;
    public Visibility RegularOptionsVisibility => Key is "forest" or "other"?Visibility.Collapsed:Visibility.Visible;
    public Visibility OtherVisibility => Key=="other"?Visibility.Visible:Visibility.Collapsed;
    public IEnumerable<TaskOptionSection> OtherSections => Options.Where(o=>o.Key!="challenge_abyss")
        .GroupBy(o=>o.Group).Select(g=>new TaskOptionSection(g));
    public TaskOption? AbyssOption=>Options.FirstOrDefault(o=>o.Key=="challenge_abyss");
    public IEnumerable<TaskOption> ForestBasicOptions => Options.Where(o=>o.Key is "teams" or "wall_mode" or "reserve_points" or "max_explorations" or "collect_resources");
    public IEnumerable<TaskOption> ForestAdvancedOptions => Options.Where(o=>o.Key!="mode");
    public int ForestModeIndex
    {
        get=>Options.FirstOrDefault(o=>o.Key=="mode")?.ChoiceId=="advanced"?1:0;
        set
        {
            var mode=Options.FirstOrDefault(o=>o.Key=="mode");
            if(mode is null)return;
            mode.ChoiceId=value==1?"advanced":"simple";
            Changed();
        }
    }
    public JsonObject SaveOptions()=>new(Options.Select(o=>new KeyValuePair<string,JsonNode?>(o.Key,o.ToJson())));
    private bool enabled = enabled;
    private bool enableSetting;
    private string state = "待执行";
    public bool Enabled { get => enabled; set { enabled = value; Changed(); } }
    public bool EnableSetting { get => enableSetting; set { if(enableSetting==value)return;enableSetting=value;Changed(); } }
    public Visibility EmptyOptionsVisibility => Options.Count==0?Visibility.Visible:Visibility.Collapsed;
    public string State { get => state; set { state = value; Changed(); } }
    public event PropertyChangedEventHandler? PropertyChanged;
    private void Changed([CallerMemberName] string? name = null) => PropertyChanged?.Invoke(this, new(name));
}
public partial class MainWindow : HandyControl.Controls.Window, INotifyPropertyChanged
{
    private T OtherToolPart<T>(string name) where T:FrameworkElement=>VisualDescendants((FrameworkElement)TaskOptions.OtherContent!)
        .OfType<T>().Single(e=>e.Name==name);
    private System.Windows.Controls.Expander WildExpander=>OtherToolPart<System.Windows.Controls.Expander>("WildExpander");
    private System.Windows.Controls.Expander AbyssExpander=>OtherToolPart<System.Windows.Controls.Expander>("AbyssExpander");
    private System.Windows.Controls.CheckBox WildCaptureSwitch=>OtherToolPart<System.Windows.Controls.CheckBox>("WildCaptureSwitch");
    private System.Windows.Controls.CheckBox AbyssSwitch=>OtherToolPart<System.Windows.Controls.CheckBox>("AbyssSwitch");
    private System.Windows.Controls.ItemsControl WildGradesList=>OtherToolPart<System.Windows.Controls.ItemsControl>("WildGradesList");
    private TaskOptionsView AbyssOptionsView=>OtherToolPart<TaskOptionsView>("AbyssOptionsView");
    private readonly JsonObject settings;
    private Process? worker;
    private bool receivedResult;
    private bool closeAfterResult;
    private long lastFeedback;
    private long? stopRequested;
    private string currentPhase="";
    private string? abortReason;
    private string? lastWorkerError;
    private bool idle = true;
    private bool canStop;
    private string status = "就绪";
    private string resources = "";
    private RunHistory? activeRun;
    public ObservableCollection<TaskItem> Tasks { get; } = [];
    public ObservableCollection<LogLine> ToolLogs { get; } = [];
    public ObservableCollection<string> PuzzleCells { get; } = new(Enumerable.Repeat("",9));
    public TaskItem PuzzleTool { get; }=new("puzzle","拼二大作战","",true);
    public TaskItem TourTool { get; }=new("tour","幻境巡游","",true);
    public TaskItem AbyssTool { get; }=new("abyss","深渊先遣","",true);
    public TaskItem MerchantTool { get; }=new("merchant","神秘商人","",true);
    private bool freeSummonEnabled;
    private bool freeSummonSettingsReady;
    private string? freeSummonSmokePath;
    public bool FreeSummonEnabled
    {
        get=>freeSummonEnabled;
        set { if(freeSummonEnabled==value)return;freeSummonEnabled=value;Changed();AutoSaveFreeSummon(); }
    }
    private string freeSummonSaveError="";
    public string FreeSummonSaveError { get=>freeSummonSaveError; private set { freeSummonSaveError=value;Changed(); } }
    private bool merchantSettingsReady;
    private string? merchantSmokePath;
    private string merchantSaveError="";
    public string MerchantSaveError { get=>merchantSaveError; private set { merchantSaveError=value;Changed(); } }
    public ObservableCollection<WildGrade> WildGrades { get; }=[];
    private bool wildCaptureEnabled;
    private bool wildSettingsReady;
    private string? wildSmokePath;
    private string wildSaveError="";
    public bool WildCaptureEnabled
    {
        get=>wildCaptureEnabled;
        set { if(wildCaptureEnabled==value)return;wildCaptureEnabled=value;Changed();AutoSaveWild(); }
    }
    public string WildSaveError { get=>wildSaveError; private set { wildSaveError=value;Changed();Changed(nameof(WildSaveErrorVisibility)); } }
    public Visibility WildSaveErrorVisibility=>string.IsNullOrEmpty(WildSaveError)?Visibility.Collapsed:Visibility.Visible;
    private string puzzleSummary="等待读取棋盘";
    public string PuzzleSummary { get=>puzzleSummary; private set { puzzleSummary=value;Changed(); } }
    private string currentMode="run";
    private readonly RunLogs runLogs = new();
    public ObservableCollection<LogGroup> LogGroups => runLogs.Groups;
    public IEnumerable<LogLine> Logs => runLogs.Lines;
    public ObservableCollection<TaskItem> StaminaPriority { get; }=[];
    private TaskItem? selectedTask;
    public TaskItem? SelectedTask
    {
        get=>selectedTask;
        set
        {
            if(ReferenceEquals(selectedTask,value))return;
            selectedTask=value;
            foreach(var task in Tasks)task.EnableSetting=ReferenceEquals(task,value);
            Changed();Changed(nameof(TaskSettingsVisibility));
        }
    }
    public Visibility TaskSettingsVisibility=>SelectedTask is null?Visibility.Collapsed:Visibility.Visible;
    public string Adb { get; set; }
    public string Address { get; set; }
    public IReadOnlyList<string> GameVersions { get; } = ["1.86", "1.88"];
    private string gameVersion = "1.86";
    public string GameVersion
    {
        get => gameVersion;
        set
        {
            if (gameVersion == value || !GameVersions.Contains(value)) return;
            gameVersion = value;
            Changed();
        }
    }
    public bool AutoThreeShots { get; set; }
    public bool FollowRunningTask { get; set; }
    public bool UnorderedTasks { get; set; }
    public bool Idle { get => idle; private set { idle = value; Changed(); Changed(nameof(StartVisibility)); Changed(nameof(StopVisibility));Changed(nameof(CanDeleteTemplate));Changed(nameof(CanAddTask)); } }
    public bool CanStop { get => canStop; private set { canStop = value; Changed(); } }
    public Visibility StartVisibility => Idle ? Visibility.Visible : Visibility.Collapsed;
    public Visibility StopVisibility => Idle ? Visibility.Collapsed : Visibility.Visible;
    public string Status { get => status; private set { status = value; Changed(); } }
    public string ResourceSummary { get => resources; private set { resources = value; Changed(); } }
    public event PropertyChangedEventHandler? PropertyChanged;
    private void Changed([CallerMemberName] string? name = null) => PropertyChanged?.Invoke(this, new(name));

    public MainWindow()
    {
        var manifest = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "tasks.json")))!.AsArray();
        taskManifest=manifest;
        // Offline checks exercise defaults independently of the user's saved choices.
        settings = App.Smoke
            ? new JsonObject {
                ["schema_version"] = 5,
                ["tasks"] = new JsonArray(manifest.Select(t => (JsonNode?)JsonValue.Create(t!["key"]!.GetValue<string>())).ToArray())
            }
            : JsonNode.Parse(File.ReadAllText(Path.Combine(App.Root, "config.json")))!.AsObject();
        MigrateHuntSettings(settings);
        MigrateCelebrationTasks(settings);
        MigrateResourceLimits(settings);
        if((settings["schema_version"]?.GetValue<int>() ?? 0)<5 && settings["task_options"]?["cocoon"] is JsonObject cocoon && cocoon["targets"] is JsonArray oldTargets)
            cocoon["daily_tasks"] ??= JsonValue.Create(oldTargets.Any(r=>r?["id"]?.ToString().StartsWith("lower_")==true && r["enabled"]?.GetValue<bool>()!=false));
        Adb = settings["adb"]?.GetValue<string>() ?? "";
        Address = settings["address"]?.GetValue<string>() ?? "127.0.0.1:16384";
        if (settings["game_version"] is JsonValue savedVersion && savedVersion.TryGetValue<string>(out var version) && version is not null)
            GameVersion = version;
        var toolSpecs=JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"tools.json")))!.AsArray();
        InitializeTriggerEvents(toolSpecs);
        var wildSpec=toolSpecs.First(t=>t!["key"]!.GetValue<string>()=="wild_capture")!;
        foreach(var grade in wildSpec["rarities"]!.AsArray())
        {
            var row=new WildGrade(grade!,settings["wild_capture"]?[grade!["id"]!.GetValue<string>()]);
            row.PropertyChanged+=(_,_)=>AutoSaveWild();WildGrades.Add(row);
        }
        wildCaptureEnabled=settings["wild_capture_enabled"]?.GetValue<bool>() ?? WildGrades.Any(r=>r.Enabled);
        freeSummonEnabled=settings["free_summon_enabled"]?.GetValue<bool>() ?? false;
        var puzzleSpec=toolSpecs.First(t=>t!["key"]!.GetValue<string>()=="puzzle")!;
        MigratePuzzleSettings(settings,puzzleSpec);
        foreach(var field in puzzleSpec["fields"]!.AsArray())
            PuzzleTool.Options.Add(new(field!,settings[field!["key"]!.GetValue<string>()]));
        var toolSpec=toolSpecs.First(t=>t!["key"]!.GetValue<string>()=="tour")!;
        foreach(var field in toolSpec["fields"]!.AsArray())
            TourTool.Options.Add(new(field!,settings["tour_options"]?[field!["key"]!.GetValue<string>()]));
        var abyssSpec=toolSpecs.First(t=>t!["key"]!.GetValue<string>()=="abyss")!;
        foreach(var field in abyssSpec["fields"]!.AsArray())
            AbyssTool.Options.Add(new(field!,settings["abyss_options"]?[field!["key"]!.GetValue<string>()]));
        foreach(var option in AbyssTool.Options)WatchOption(option);
        var merchantSpec=toolSpecs.First(t=>t!["key"]!.GetValue<string>()=="merchant")!;
        foreach(var field in merchantSpec["fields"]!.AsArray())
            MerchantTool.Options.Add(new(field!,settings["merchant_options"]?[field!["key"]!.GetValue<string>()]));
        foreach(var option in MerchantTool.Options)
        {
            option.BindDependency(MerchantTool.Options);
            option.PropertyChanged+=(_,e)=>{if(e.PropertyName is nameof(TaskOption.ChoiceId) or nameof(TaskOption.Number))AutoSaveMerchant();};
            foreach(var row in option.Rows)row.PropertyChanged+=(_,_)=>AutoSaveMerchant();
            option.Rows.CollectionChanged+=(_,_)=>AutoSaveMerchant();
        }
        AutoThreeShots=settings["stamina_settings"]?["auto_three_shots"]?.GetValue<bool>() ?? true;
        FollowRunningTask=settings["follow_running_task"]?.GetValue<bool>() ?? true;
        UnorderedTasks=settings["unordered_tasks"]?.GetValue<bool>() ?? false;
        var chosen = settings["tasks"]!.AsArray().Select(x => x!.GetValue<string>()).ToHashSet();
        if(chosen.Contains("idle")||chosen.Contains("daily_rewards"))chosen.Add("rewards");
        foreach (var task in manifest)
        {
            var key = task!["key"]!.GetValue<string>();
            bool defaultEnabled=task["settings"]?["default_enabled"]?.GetValue<bool>()==true && settings["task_options"]?[key] is null;
            var item=new TaskItem(key, task["name"]!.GetValue<string>(), task["description"]!.GetValue<string>(), chosen.Contains(key)||defaultEnabled);
            item.Hint=task["settings"]?["hint"]?.GetValue<string>() ?? "";
            foreach(var field in task["settings"]!["fields"]!.AsArray())
            {
                var fieldKey=field!["key"]!.GetValue<string>();
                var value=settings["task_options"]?[key]?[fieldKey];
                if(value is null && fieldKey=="auto_three_shots")value=JsonValue.Create(AutoThreeShots);
                item.Options.Add(new(field!,value,(settings["schema_version"]?.GetValue<int>() ?? 0)<4));
            }
            foreach(var option in item.Options)option.BindDependency(item.Options);
            Tasks.Add(item);
            taskCatalog.Add(key,item);
        }
        var priority=settings["stamina_order"]?.AsArray().Select(x=>x!.GetValue<string>()).ToArray() ?? ["copies","hunt","main"];
        foreach(var key in priority)StaminaPriority.Add(Tasks.First(x=>x.Key==key));
        InitializeTaskQueue();
        InitializeComponent();
        DataContext = this;
        var selection=settings["task_settings_selection"]?.GetValue<string>();
        SelectedTask=Tasks.FirstOrDefault(t=>t.InstanceId==selection) ?? Tasks.FirstOrDefault();
        Append("勾选任务后点击开始。");
        wildSettingsReady=true;
        merchantSettingsReady=true;
        freeSummonSettingsReady=true;
        triggerSettingsReady=true;
        if (App.Smoke) Loaded += async (_, _) => await RunSmoke();
        else if(App.RunRequested)Loaded+=async (_,_)=>await Begin("run");
    }

    private void Append(string message,string color="MessageLogBrush")
    {
        bool follow=LogScroll.ScrollableHeight-LogScroll.VerticalOffset<24;
        var line=new LogLine(DateTime.Now.ToString("HH:mm:ss"), message,color);
        runLogs.Append(line);activeRun?.Log(line.Time,message,color);
        if(currentMode!="run")
        {
            LogLine.AppendTo(ToolLogs,new(line.Time,message,color));
            while(ToolLogs.Count>300)ToolLogs.RemoveAt(0);
            Dispatcher.InvokeAsync(()=>ToolLogScroll.ScrollToEnd(),DispatcherPriority.Background);
        }
        // Reading an earlier expanded task must not be interrupted by new lines.
        if(follow && runLogs.Current!.IsExpanded)
            Dispatcher.InvokeAsync(()=>
            {
                var group=VisualDescendants(LogList).OfType<System.Windows.Controls.Expander>()
                    .FirstOrDefault(e=>ReferenceEquals(e.DataContext,runLogs.Current));
                if(group is null)LogScroll.ScrollToEnd();
                else group.BringIntoView(new Rect(0,Math.Max(0,group.ActualHeight-1),1,1));
            },DispatcherPriority.Background);
    }
    private void SelectAll(object sender, RoutedEventArgs e) { foreach (var task in Tasks) task.Enabled = true; }
    private void ClearSelection(object sender, RoutedEventArgs e) { foreach (var task in Tasks) task.Enabled = false; }
    private void ConfigureTask(object sender,RoutedEventArgs e)
    {
        var item=(TaskItem)((FrameworkElement)sender).DataContext;
        SelectedTask=item;
    }
    private static void MigrateHuntSettings(JsonObject saved)
    {
        if(saved["task_options"]?["hunt"] is not JsonObject hunt)return;
        if(hunt["team"] is null)
        {
            var first=(hunt["teams"] as JsonArray)?.FirstOrDefault(row=>row is not JsonObject || row["enabled"]?.GetValue<bool>()==true);
            hunt["team"]=(first is JsonObject ? first["id"] : first)?.ToString() ?? "2";
        }
        hunt.Remove("teams");hunt.Remove("max_runs");
    }
    private static void MigrateCelebrationTasks(JsonObject saved)
    {
        // Preserve each template's ordinary tasks and put seasonal activities
        // in one slot. User requested only 三阵入局 enabled on this migration.
        if(saved["task_options"] is not JsonObject)saved["task_options"]=new JsonObject();
        var options=saved["task_options"]!.AsObject();
        bool fresh=options["celebration"] is not JsonObject;
        if(fresh)
        {
            options["celebration"]=new JsonObject {
                ["triad"]=true,["giant"]=false,["daily_puzzle"]=false,
                ["triad_auto_settle"]=options["triad"]?["auto_settle"]?.DeepClone() ?? JsonValue.Create(true),
                ["giant_auto_settle"]=options["giant"]?["auto_settle"]?.DeepClone() ?? JsonValue.Create(true),
                ["giant_skip_completed"]=options["giant"]?["skip_completed"]?.DeepClone() ?? JsonValue.Create(true),
                ["giant_teams"]=options["giant"]?["teams"]?.DeepClone() ?? new JsonArray(1),
                ["giant_max_runs"]=options["giant"]?["max_runs"]?.DeepClone() ?? JsonValue.Create(0)
            };
        }
        if(options["other"] is JsonObject other)other.Remove("daily_puzzle");
        foreach(var name in new[] { "tasks", "task_order" })
        {
            if(saved[name] is not JsonArray list)continue;
            var result=new List<string>();
            bool hasLegacy=list.Any(node=>node?.ToString() is "giant" or "triad");
            foreach(var node in list)
            {
                string key=node!.ToString();
                if(key is "giant" or "triad")key="celebration";
                if(key=="celebration" && hasLegacy && result.Contains(key))continue;
                result.Add(key);
            }
            if(fresh && !result.Contains("celebration"))
            {
                int at=result.FindIndex(k=>k is "rewards" or "other" or "finish");
                result.Insert(at<0?result.Count:at,"celebration");
            }
            saved[name]=Keys(result);
        }
        if(saved["task_queue"] is JsonArray queue)
        {
            var result=new JsonArray();
            bool inserted=queue.OfType<JsonObject>().Any(row=>row["key"]?.ToString()=="celebration");
            foreach(var raw in queue.OfType<JsonObject>())
            {
                if(raw["key"]?.ToString() is not ("giant" or "triad")) { result.Add(raw.DeepClone());continue; }
                if(inserted)continue;
                result.Add(new JsonObject { ["id"]=raw["id"]!.DeepClone(),["key"]="celebration",["name"]="庆典活动",
                    ["enabled"]=true,["options"]=options["celebration"]!.DeepClone() });
                inserted=true;
            }
            if(fresh && !inserted)
            {
                int at=result.ToList().FindIndex(k=>k?["key"]?.ToString() is "rewards" or "other" or "finish");
                result.Insert(at<0?result.Count:at,new JsonObject { ["id"]="celebration_"+Guid.NewGuid().ToString("N"),
                    ["key"]="celebration",["name"]="庆典活动",["enabled"]=true,["options"]=options["celebration"]!.DeepClone() });
            }
            saved["task_queue"]=result;
        }
        if(saved["task_templates"] is JsonArray templates)
            foreach(var template in templates.OfType<JsonObject>())
                if(template["settings"] is JsonObject snapshot)MigrateCelebrationTasks(snapshot);
    }
    private static void MigratePuzzleSettings(JsonObject saved,JsonNode spec)
    {
        if(!saved.ContainsKey("puzzle_target_score") && (saved.ContainsKey("puzzle_goal")||saved.ContainsKey("puzzle_max_moves")))
        {
            var legacy=saved["puzzle_goal"]?.GetValue<string>() ?? "first";
            var target=spec["legacy_goals"]?[legacy] ?? throw new InvalidOperationException("旧版拼二目标无效");
            saved["puzzle_target_score"]=target.DeepClone();
            saved["puzzle_max_games"]=0;
        }
        saved.Remove("puzzle_goal");saved.Remove("puzzle_max_moves");
    }
    private void AutoSaveWild()
    {
        if(!wildSettingsReady)return;
        try
        {
            var snapshot=(settings["wild_capture"] as JsonObject)?.DeepClone().AsObject() ?? new JsonObject();
            string validation="";
            foreach(var grade in WildGrades)
            {
                try { snapshot[grade.Id]=grade.ToJson(); }
                catch(InvalidOperationException e)
                {
                    validation=e.Message;
                    // Typing an unfinished number must not prevent turning the tool off.
                    var previous=snapshot[grade.Id] as JsonObject;
                    if(previous is null)snapshot[grade.Id]=previous=new() { ["probability"]=grade.DefaultProbability };
                    previous["enabled"]=grade.Enabled;
                }
            }
            if(!App.Smoke || wildSmokePath is not null)
                WildSettingsPersistence.Save(wildSmokePath ?? Path.Combine(App.Root,"config.json"),WildCaptureEnabled,snapshot);
            settings["wild_capture"]=snapshot;
            settings["wild_capture_enabled"]=WildCaptureEnabled;
            WildSaveError=validation;
        }
        catch(Exception e) { WildSaveError="自动保存失败："+e.Message; }
    }
    private void AutoSaveFreeSummon()
    {
        if(!freeSummonSettingsReady)return;
        try
        {
            if(!App.Smoke || freeSummonSmokePath is not null)
            {
                string path=freeSummonSmokePath ?? Path.Combine(App.Root,"config.json");
                var saved=JsonNode.Parse(File.ReadAllText(path))!.AsObject();
                saved["free_summon_enabled"]=FreeSummonEnabled;
                File.WriteAllText(path+".summon.tmp",saved.ToJsonString(new() { WriteIndented=true }),new UTF8Encoding(false));
                File.Move(path+".summon.tmp",path,true);
            }
            settings["free_summon_enabled"]=FreeSummonEnabled;
            FreeSummonSaveError="";
        }
        catch(Exception e) { FreeSummonSaveError="自动保存失败："+e.Message; }
    }
    private void AutoSaveMerchant()
    {
        if(!merchantSettingsReady)return;
        try
        {
            var snapshot=(settings["merchant_options"] as JsonObject)?.DeepClone().AsObject() ?? new JsonObject();
            string validation="";
            foreach(var option in MerchantTool.Options)
            {
                try { snapshot[option.Key]=option.ToJson(); }
                catch(InvalidOperationException e)
                {
                    validation=e.Message;
                    snapshot[option.Key] ??= JsonValue.Create(240);
                }
            }
            if(!App.Smoke || merchantSmokePath is not null)
            {
                string path=merchantSmokePath ?? Path.Combine(App.Root,"config.json");
                var saved=JsonNode.Parse(File.ReadAllText(path))!.AsObject();
                saved["merchant_options"]=snapshot.DeepClone();
                File.WriteAllText(path+".merchant.tmp",saved.ToJsonString(new() { WriteIndented=true }),new UTF8Encoding(false));
                File.Move(path+".merchant.tmp",path,true);
            }
            settings["merchant_options"]=snapshot;
            MerchantSaveError=validation;
        }
        catch(Exception e) { MerchantSaveError="自动保存失败："+e.Message; }
    }
    private void Save()
    {
        foreach(var option in PuzzleTool.Options)settings[option.Key]=option.ToJson();
        settings.Remove("puzzle_goal");settings.Remove("puzzle_max_moves");
        settings["tour_options"]=TourTool.SaveOptions();
        settings["abyss_options"]=AbyssTool.SaveOptions();
        settings["merchant_options"]=MerchantTool.SaveOptions();
        settings["trigger_events"]=TriggerEventsTool.SaveOptions();
        settings["free_summon_enabled"]=FreeSummonEnabled;
        settings["wild_capture"]=new JsonObject(WildGrades.Select(r=>new KeyValuePair<string,JsonNode?>(r.Id,r.ToJson())));
        settings["wild_capture_enabled"]=WildCaptureEnabled;
        settings["adb"] = Adb.Trim();
        settings["address"] = Address.Trim();
        settings["game_version"] = GameVersion;
        settings.Remove("max_battles");
        settings["close_mumu"] = false; // Closing is configured only through the visible finish task.
        settings["tasks"] = Keys(Tasks.Where(t=>t.Enabled).Select(t=>t.Key).Distinct());
        settings["task_options"]=CatalogOptions();
        settings["task_order"]=Keys(Tasks.Select(t=>t.Key).Distinct());
        settings["task_queue"]=InstanceQueue();
        settings["allow_repeat_tasks"]=AllowRepeatTasks;
        settings["stamina_order"]=new JsonArray(StaminaPriority.Select(t=>(JsonNode?)JsonValue.Create(t.Key)).ToArray());
        settings["stamina_settings"]=new JsonObject { ["auto_three_shots"]=AutoThreeShots };
        settings["follow_running_task"]=FollowRunningTask;
        settings["unordered_tasks"]=UnorderedTasks;
        settings["schema_version"]=8;
        settings["task_settings_selection"]=SelectedTask?.InstanceId ?? "";
        SaveTaskTemplates();
        // A failed UI test must never modify the user's configuration.
        if (!App.Smoke)
        {
            string path = Path.Combine(App.Root, "config.json");
            File.WriteAllText(path + ".tmp", settings.ToJsonString(new() { WriteIndented = true }), new UTF8Encoding(false));
            File.Move(path + ".tmp", path, true);
        }
    }
    private void SaveClick(object sender, RoutedEventArgs e)
    {
        try { Save(); Append("设置已保存。"); }
        catch (Exception exc) { MessageBox.Show(this, exc.Message, "设置未保存"); }
    }
    private void StartRun(object sender, RoutedEventArgs e) => _ = Begin("run");
    private void StartFromTaskClick(object sender, RoutedEventArgs e)
    {
        if(!Idle || sender is not FrameworkElement { DataContext:TaskItem item } || !item.Enabled || !Tasks.Contains(item))return;
        SelectedTask=item;
        _ = Begin("run", fake:App.Smoke, startFrom:item.InstanceId);
    }
    private void RunOnlyTaskClick(object sender,RoutedEventArgs e)
    {
        if(!Idle || sender is not FrameworkElement {DataContext:TaskItem item} || !Tasks.Contains(item))return;
        SelectedTask=item;
        _ = Begin("run",fake:App.Smoke,onlyTask:item.InstanceId);
    }
    private void Diagnose(object sender, RoutedEventArgs e) => _ = Begin("diagnostic");
    private void LaunchGame(object sender, RoutedEventArgs e) => _ = Begin("launch");
    private void StartPuzzle(object sender, RoutedEventArgs e) => _ = Begin("puzzle");
    private void StartTour(object sender, RoutedEventArgs e) => _ = Begin("tour");
    private void StartAbyss(object sender, RoutedEventArgs e) => _ = Begin("abyss");
    private void StopRun(object sender, RoutedEventArgs e) => RequestStop();
    private void RequestStop()
    {
        if (worker is null || worker.HasExited || !CanStop) return;
        CanStop = false; Status = "正在停止";stopRequested=Stopwatch.GetTimestamp();
        try { worker.StandardInput.WriteLine("{\"command\":\"stop\"}"); worker.StandardInput.Flush(); Append("已请求停止。"); }
        catch (IOException exc) { Append("停止通道已关闭：" + exc.Message); }
    }

    private async Task Begin(string mode, bool fake = false, string? startFrom = null,string? onlyTask = null)
    {
        if (!Idle) return;
        if (fake && !App.Smoke) throw new InvalidOperationException("测试通道只能用于离线检查");
        currentMode=mode;
        receivedResult=false;closeAfterResult=false;abortReason=null;lastWorkerError=null;stopRequested=null;
        activeRun=null;App.ActiveRunFolder=null;
        runLogs.Begin(mode switch { "puzzle"=>"拼二大作战", "tour"=>"幻境巡游", "abyss"=>"深渊先遣", "diagnostic"=>"只读检测", "launch"=>"打开游戏", _=>"连接与准备" });
        ToolLogs.Clear();ResourceSummary="";Preview.Source=null;LogScroll.ScrollToTop();
        if(mode=="run")Pages.SelectedIndex=0;
        else
        {
            Pages.SelectedItem=ToolsTab;
            ToolsPages.SelectedIndex=mode=="puzzle"?0:mode=="tour"?1:mode=="diagnostic"?2:3;
            ToolLogs.Clear();
        }
        using var monitorStop=new CancellationTokenSource();
        Task? monitor=null;
        try
        {
            string historyRoot=App.Smoke?Path.Combine(App.DiagnosticsRoot,"runs"):Path.Combine(App.Root,"reports");
            activeRun=RunHistory.Start(historyRoot,mode);App.ActiveRunFolder=activeRun.Folder;
            foreach(var error in activeRun.CleanupErrors)Append("旧记录暂时无法清理："+error,"WarningLogBrush");
            Save();
            if (!fake && !File.Exists(Adb.Trim())) throw new InvalidOperationException("请在设置中填写 MuMu adb.exe 路径。");
            var selected = Tasks.Where(t => t.Enabled).Select(t => t.Key).Distinct().ToArray();
            var targetId=onlyTask??startFrom;
            var firstTask=targetId is null?null:Tasks.FirstOrDefault(t=>t.InstanceId==targetId);
            if(onlyTask is not null)
            {
                if(mode!="run" || startFrom is not null || firstTask is null)throw new InvalidOperationException("请选择一条有效任务运行。");
                selected=[firstTask.Key];
            }
            if (mode == "run" && selected.Length == 0) throw new InvalidOperationException("请至少勾选一项任务。");
            if(startFrom is not null && (mode!="run" || firstTask is null || !firstTask.Enabled))
                throw new InvalidOperationException("请从列表中已勾选的任务开始。");
            string python = Path.Combine(App.Root, "runtime", "python", "python.exe");
            if (!File.Exists(python)) python = Path.Combine(App.Root, ".venv", "Scripts", "python.exe");
            if (!File.Exists(python)) throw new InvalidOperationException("缺少 Python 运行环境，请下载完整发布包，或按 README 配置源码运行环境。");
            var start = new ProcessStartInfo(python)
            {
                WorkingDirectory = App.Root, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };
            start.ArgumentList.Add("-u");
            if (fake) start.ArgumentList.Add(Path.Combine(App.Root, "tests", "fixtures", "gui-worker.py"));
            else { start.ArgumentList.Add("-m"); start.ArgumentList.Add("chao2.gui_worker"); }
            start.Environment["PYTHONUTF8"] = "1";
            start.Environment["CHAO2_REPORT_ROOT"]=historyRoot;
            start.Environment["CHAO2_REPORT_FOLDER"]=activeRun.Folder;
            start.Environment["CHAO2_RUN_TOKEN"]=activeRun.Token;
            worker = new Process { StartInfo = start };
            receivedResult = false;closeAfterResult=false;Idle = false;CanStop = true;
            abortReason=null;lastWorkerError=null;stopRequested=null;lastFeedback=Stopwatch.GetTimestamp();
            currentPhase="正在启动后台";Status=currentPhase;
            Append(mode switch { "puzzle"=>"正在连接并读取已打开的拼二棋盘…", "tour"=>"正在连接并开始幻境巡游…", "abyss"=>"正在连接并检查深渊先遣…", "diagnostic"=>"开始只读检测，正在连接模拟器…", "launch"=>"正在打开 MuMu 和超二…", _=>"开始执行，正在连接模拟器…" },"InfoLogBrush");
            if(firstTask is not null)Append(onlyTask is not null?$"仅运行「{firstTask.Name}」，完成后结束本轮。":$"从「{firstTask.Name}」开始，按列表顺序执行后续已勾选任务。","InfoLogBrush");
            int firstIndex=firstTask is null?0:Tasks.IndexOf(firstTask);
            for(int i=0;i<Tasks.Count;i++)Tasks[i].State=onlyTask is not null
                ?Tasks[i].InstanceId==onlyTask?"待执行":Tasks[i].Enabled?"本轮跳过":"未启用"
                :i<firstIndex?"本轮跳过":Tasks[i].Enabled?"待执行":"未启用";
            worker.Start();
            Task output = ReadEvents(worker.StandardOutput);
            Task errors = ReadErrors(worker.StandardError,activeRun.Folder);
            await worker.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new { mode, settings, selected, start_from=startFrom,only_task=onlyTask }));
            await worker.StandardInput.FlushAsync();
            monitor=MonitorWorker(worker,monitorStop.Token);
            await worker.WaitForExitAsync();
            await Task.WhenAll(output, errors);
            if(abortReason is not null) { Status="已停止";Append(abortReason,"ErrorLogBrush"); }
            else if (!receivedResult)
            {
                Status = "异常结束";Append($"后台退出，未收到结果（退出码 {worker.ExitCode}）。","ErrorLogBrush");
                if(lastWorkerError is not null)Append(lastWorkerError,"ErrorLogBrush");
            }
        }
        catch (Exception exc)
        {
            lastWorkerError=exc.Message;
            Status = "无法启动"; Append(exc.Message,"ErrorLogBrush");
            // Closing stdin cancels an already launched backend before it can outlive the UI.
            if (worker is { HasExited: false }) worker.StandardInput.Close();
        }
        finally
        {
            monitorStop.Cancel();
            if(monitor is not null)try { await monitor; } catch(OperationCanceledException) { }
            runLogs.Finish(Status);
            activeRun?.Finish(stopRequested is null?"blocked":"stopped",abortReason??lastWorkerError??Status);
            activeRun=null;App.ActiveRunFolder=null;
            worker?.Dispose();worker=null;CanStop=false;Idle=true;
            if(closeAfterResult && receivedResult && abortReason is null && stopRequested is null && !App.Smoke)Close();
        }
    }
    private async Task MonitorWorker(Process process,CancellationToken cancel)
    {
        int lastNotice=0;
        double quietLimit=App.Smoke?2:60;
        double stopLimit=App.Smoke?1:8;
        while(!process.HasExited)
        {
            await Task.Delay(App.Smoke?100:1000,cancel);
            if(process.HasExited)return;
            double quiet=Stopwatch.GetElapsedTime(lastFeedback).TotalSeconds;
            if(stopRequested is null && quiet>=quietLimit)
            {
                abortReason=$"后台连续{quietLimit:0}秒没有反馈，已中止。本次停在：{currentPhase}。";
                Append("等待后台超时，正在停止…","ErrorLogBrush");RequestStop();
            }
            else if(stopRequested is null && quiet>=15 && (int)quiet/15>lastNotice)
            {
                lastNotice=(int)quiet/15;
                Append($"仍在等待：{currentPhase}（{(int)quiet}秒未收到新反馈）。","WarningLogBrush");
            }
            if(quiet<15)lastNotice=0;
            if(stopRequested is long requested && Stopwatch.GetElapsedTime(requested).TotalSeconds>=stopLimit)
            {
                abortReason??="后台未响应停止，已终止本次后台进程，保留游戏现场。";
                // Only the worker owned by this run is terminated, never MuMu or other apps.
                if(!process.HasExited)process.Kill(entireProcessTree:true);
                return;
            }
        }
    }
    private async Task ReadEvents(StreamReader reader)
    {
        while (await reader.ReadLineAsync() is { } line)
        {
            if (!line.StartsWith("@chao2@")) continue;
            try
            {
                using var document = JsonDocument.Parse(line[7..]);
                var root = document.RootElement;
                lastFeedback=Stopwatch.GetTimestamp();
                HandleEvent(root.GetProperty("kind").GetString()!, root.GetProperty("data"));
            }
            catch (Exception exc) when(exc is JsonException or KeyNotFoundException or InvalidOperationException)
            { Append("收到无法解析的后台反馈："+exc.Message,"WarningLogBrush"); }
        }
    }
    private async Task ReadErrors(StreamReader reader,string folder)
    {
        // Write errors immediately; a stuck worker must not hide diagnostics until exit.
        await using var file=new StreamWriter(Path.Combine(folder,"frontend-worker.log"),false,new UTF8Encoding(false)) { AutoFlush=true };
        while(await reader.ReadLineAsync() is { } line)
        {
            await file.WriteLineAsync(line);
            if(!string.IsNullOrWhiteSpace(line))lastWorkerError=line.Length>500?line[..500]:line;
        }
    }
    private void HandleEvent(string kind, JsonElement data)
    {
        if (kind == "log")
        {
            string message=data.GetString() ?? "";
            string color=message.StartsWith("已安全停止")?"ErrorLogBrush":message.StartsWith("连接成功")?"SuccessLogBrush":message.StartsWith("正在")?"InfoLogBrush":"MessageLogBrush";
            Append(message,color);
        }
        else if(kind=="wild_notice")
            Append(data.GetProperty("message").GetString()!,WildGrade.BrushKey(data.GetProperty("rarity").GetString()));
        else if(kind=="phase") { currentPhase=data.GetString() ?? "执行中";if(stopRequested is null)Status=currentPhase; }
        else if (kind == "task")
        {
            var item = Tasks.FirstOrDefault(t => t.InstanceId == data[0].GetString());
            if (item is not null)
            {
                item.State = data[1].GetString() ?? "";
                var group=runLogs.Task(item.InstanceId,item.Name,item.State);
                if(item.State=="跳过" && group.Lines.Count==0 && Logs.LastOrDefault() is { } last && last.Text.Contains(item.Name))
                    group.Lines.Add(last);
                if(FollowRunningTask && item.State=="运行中")SelectedTask=item;
            }
        }
        else if (kind == "preview" && File.Exists(data.GetString()))
        {
            // Load to memory: the worker overwrites latest.png on the next observation.
            using var file = File.OpenRead(data.GetString()!);
            var image = new BitmapImage(); image.BeginInit(); image.CacheOption = BitmapCacheOption.OnLoad;
            image.StreamSource = file; image.EndInit(); image.Freeze(); Preview.Source = image;
        }
        else if(kind=="puzzle")
        {
            var board=data.GetProperty("board");
            if(board.GetArrayLength()!=9)throw new InvalidOperationException("棋盘尺寸不是3×3");
            for(int i=0;i<9;i++)PuzzleCells[i]=board[i].GetInt32()==0?"":board[i].ToString();
            string score=data.GetProperty("score").ValueKind==JsonValueKind.Null?"未读清":data.GetProperty("score").ToString();
            string game=data.TryGetProperty("game",out var gameNode)?$"第 {gameNode} 局    ":"";
            PuzzleSummary=$"{game}第 {data.GetProperty("moves")} 步    得分 {score}    最大数字 {data.GetProperty("max_tile")}";
        }
        else if (kind == "resources") UpdateResources(data, "最近观察");
        else if (kind == "result")
        {
            activeRun?.SaveResult(data);
            receivedResult = true;
            string code = data.GetProperty("status").GetString() ?? "";
            closeAfterResult=currentMode=="run" && (code is "completed" or "partial") &&
                data.TryGetProperty("close_app_requested",out var close) && close.ValueKind==JsonValueKind.True;
            Status = code switch { "completed" => "本轮完成", "partial" => "部分完成", "blocked" when currentPhase.StartsWith("正在连接 MuMu") => "连接失败", "blocked" => "已安全停止", "stopped" => "已停止", "diagnostic" => "检测完成", "launched" => "游戏已启动", _ => "已结束" };
            runLogs.Finish(Status);
            if (data.TryGetProperty("reason", out var reason) && reason.ValueKind == JsonValueKind.String && Logs.LastOrDefault()?.Text.EndsWith(reason.GetString()!,StringComparison.Ordinal)!=true)
                Append(reason.GetString()!,code=="blocked"?"ErrorLogBrush":"WarningLogBrush");
            if (data.TryGetProperty("resources_end", out var r) && r.ValueKind == JsonValueKind.Object) UpdateResources(r, "结束时");
            else if (data.TryGetProperty("resources_last_observed", out r) && r.ValueKind == JsonValueKind.Object) UpdateResources(r, "最近观察");
            else if (data.TryGetProperty("resources_start", out r) && r.ValueKind == JsonValueKind.Object) UpdateResources(r, "开始时");
            Append(Status + (data.TryGetProperty("folder", out _) ? "，记录已保存。" : "。"),code=="blocked"?"ErrorLogBrush":code is "partial" or "stopped"?"WarningLogBrush":"SuccessLogBrush");
            if(data.TryGetProperty("free_summons",out var summons) && summons.ValueKind==JsonValueKind.Array && summons.GetArrayLength()>0)
            {
                runLogs.Summary("免费造唤 · 结束记录");
                foreach(var summon in summons.EnumerateArray())
                    if(summon.TryGetProperty("message",out var summonMessage))
                        Append(summonMessage.GetString()!,summon.GetProperty("status").GetString()=="done"?"SuccessLogBrush":"MessageLogBrush");
            }
            if(data.TryGetProperty("wild_captures",out var captures) && captures.ValueKind==JsonValueKind.Array && captures.GetArrayLength()>0)
            {
                runLogs.Summary("野生怪兽 · 结束提醒");
                foreach(var capture in captures.EnumerateArray())
                    Append(capture.GetProperty("message").GetString()!,WildGrade.BrushKey(capture.GetProperty("rarity").GetString()));
            }
            if(data.TryGetProperty("wild_checks",out var wildChecks) && wildChecks.ValueKind==JsonValueKind.Array && wildChecks.GetArrayLength()>0)
            {
                var last=wildChecks[wildChecks.GetArrayLength()-1];
                var checkStatus=last.GetProperty("status").GetString();
                if(checkStatus is "absent" or "navigation_failed")
                {
                    runLogs.Summary("野生怪兽 · 检查结果");
                    Append(last.GetProperty("message").GetString()!,checkStatus=="navigation_failed"?"WarningLogBrush":"MessageLogBrush");
                }
            }
        }
    }
    private void UpdateResources(JsonElement r, string when)
    {
        string V(string name) => r.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null ? value.ToString() : "?";
        ResourceSummary = $"{when}：体力 {V("stamina")}/{V("stamina_cap")}    钻石 {V("diamonds")}    金币 {V("gold_text")}";
    }
    private static void OpenPath(string path) => Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
    private void OpenReports(object sender, RoutedEventArgs e)
    { string folder=Path.Combine(App.Root,"reports");Directory.CreateDirectory(folder);OpenPath(folder); }
    private void OpenReadme(object sender, RoutedEventArgs e) => OpenPath(Path.Combine(App.Root, "README.md"));
    private void OpenLicense(object sender, RoutedEventArgs e) => OpenPath(Path.Combine(App.Root, "THIRD_PARTY_NOTICES.md"));
    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (!Idle) { RequestStop(); e.Cancel = true; return; }
        Save();
    }

    private async Task RunSmoke()
    {
        // No ADB or game operations. Render the actual WPF views and exercise stdio/stop.
        Directory.CreateDirectory(App.DiagnosticsRoot);
        try
        {
            if (Tasks.Count != 17 || Tasks[0].Key!="startup" || new[]{"forest","rift","tribe","exploration","origin","arena","nest","celebration","other"}.Any(k=>!Tasks.Any(t=>t.Key==k)) || Tasks.Any(t=>t.Key is "idle" or "overview" or "daily_rewards" or "three_shots" or "giant" or "triad") || !Idle || StartButton.Visibility != Visibility.Visible || StopButton.Visibility != Visibility.Collapsed)
                throw new Exception("初始界面状态错误");
            if (!GameVersionPicker.IsVisible || (string?)GameVersionPicker.SelectedItem != "1.86" || GameVersionPicker.Items.Count != 2)
                throw new Exception("游戏版本选择初始状态错误");
            GameVersionPicker.SelectedItem = "1.88";
            Save();
            if (GameVersion != "1.88" || settings["game_version"]?.GetValue<string>() != "1.88")
                throw new Exception("所选游戏版本未保存");
            GameVersionPicker.SelectedItem = "1.86";
            await SmokeTaskTemplates();
            await SmokeContinueFromTask();
            await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            await Task.Delay(250);
            Capture("wpf-main.png");
            double logLeft=LogPanel.TranslatePoint(new Point(),this).X;
            SelectedTask=Tasks.First(t=>t.Key=="copies");
            var copySwitch=SelectedTask.Options.First(o=>o.Key=="challenge_copies");
            var sageSwitch=SelectedTask.Options.First(o=>o.Key=="wandering_sage");
            var sageUntilEnd=SelectedTask.Options.First(o=>o.Key=="sage_until_end");
            if(!sageUntilEnd.Checked || !sageUntilEnd.IsAvailable)throw new Exception("智者持续处理默认未开启");
            sageSwitch.Checked=false;
            if(sageUntilEnd.IsAvailable)throw new Exception("智者关闭后持续处理选项未禁用");
            sageSwitch.Checked=true;sageUntilEnd.Checked=false;Save();
            if(settings["task_options"]!["copies"]!["sage_until_end"]!.GetValue<bool>())
                throw new Exception("智者持续处理关闭未保存");
            sageUntilEnd.Checked=true;Save();
            if(!settings["task_options"]!["copies"]!["sage_until_end"]!.GetValue<bool>())
                throw new Exception("智者持续处理开启未保存");
            if(SelectedTask.Name!="异象" || !new TaskOption(manifestFor("copies","challenge_copies"),null).Checked ||
                !new TaskOption(manifestFor("copies","wandering_sage"),null).Checked)
                throw new Exception("异象名称或子任务默认开关错误");
            copySwitch.Checked=false;sageSwitch.Checked=true;
            if(SelectedTask.Options.Where(o=>o.Key is "teams" or "max_runs" or "include_friends").Any(o=>o.IsAvailable) || !sageSwitch.IsAvailable)
                throw new Exception("复制体关闭后依赖控件或独立智者开关错误");
            Save();
            if(settings["task_options"]!["copies"]!["challenge_copies"]!.GetValue<bool>() ||
                !settings["task_options"]!["copies"]!["wandering_sage"]!.GetValue<bool>())
                throw new Exception("异象子任务开关未分别保存");
            copySwitch.Checked=true;Save();
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            CheckInlineOptions();Capture("wpf-anomaly-settings.png");
            foreach(var (legacy,expected) in new[]{
                ("{\"teams\":[3,2],\"max_runs\":1}","3"),
                ("{\"teams\":[{\"id\":\"1\",\"enabled\":false},{\"id\":\"4\",\"enabled\":true}]}","4"),
                ("{\"teams\":[]}","2"),
                ("{\"team\":\"5\",\"teams\":[2],\"max_runs\":1}","5")})
            {
                var old=new JsonObject { ["task_options"]=new JsonObject { ["hunt"]=JsonNode.Parse(legacy) } };
                MigrateHuntSettings(old);
                var migrated=old["task_options"]!["hunt"]!.AsObject();
                if(migrated["team"]?.GetValue<string>()!=expected || migrated.ContainsKey("teams") || migrated.ContainsKey("max_runs"))
                    throw new Exception("狩猎单队迁移错误");
            }
            SelectedTask=Tasks.First(t=>t.Key=="hunt");
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var huntTeam=SelectedTask.Options.Single(o=>o.Key=="team");
            var huntTeamBox=VisualDescendants(TaskOptions).OfType<System.Windows.Controls.ComboBox>().Single(b=>b.IsVisible && ReferenceEquals(b.DataContext,huntTeam));
            if(huntTeam.ChoiceId!="2" || huntTeam.Choices.Count!=5 ||
                SelectedTask.Options.Any(o=>o.Key is "teams" or "max_runs") ||
                VisualDescendants(TaskOptions).OfType<System.Windows.Controls.Button>().Any(b=>b.IsVisible && b.Content?.ToString()=="添加队伍"))
                throw new Exception("狩猎未简化为单个队伍选择");
            huntTeamBox.SelectedValue="3";Save();
            if(new TaskOption(manifestFor("hunt","team"),settings["task_options"]!["hunt"]!["team"]).ChoiceId!="3")
                throw new Exception("狩猎单队选择未保存");
            huntTeamBox.SelectedValue="2";Save();
            if(Tasks.Where(t=>t.Key is "copies" or "hunt" or "main").Any(t=>t.Options.Single(o=>o.Key=="auto_three_shots").Label!="体力不足时自动领取每日三发"))
                throw new Exception("三发条件文案不一致");
            CheckInlineOptions();Capture("wpf-hunt-settings.png");
            SelectedTask=Tasks.First(t=>t.Key=="cocoon");
            var legacyLimits=JsonNode.Parse("""
                {"max_battles":50,"tour_options":{"max_battles":25},"task_options":{"cocoon":{"max_runs":3,"reserve_spikes":0,"targets":[{"id":"gold","limit":5}]}},"task_queue":[{"key":"cocoon","options":{"max_runs":4,"reserve_spikes":3}}],"task_templates":[{"settings":{"max_battles":50,"task_options":{"cocoon":{"reserve_spikes":4}}}}]}
                """)!.AsObject();
            MigrateResourceLimits(legacyLimits);
            string once=legacyLimits.ToJsonString();MigrateResourceLimits(legacyLimits);
            if(legacyLimits.ContainsKey("max_battles")||legacyLimits["task_options"]!["cocoon"]!.AsObject().ContainsKey("max_runs")||
                legacyLimits["task_options"]!["cocoon"]!["reserve_spikes_enabled"]!.GetValue<bool>()||
                !legacyLimits["task_queue"]![0]!["options"]!["reserve_spikes_enabled"]!.GetValue<bool>()||
                legacyLimits["task_templates"]![0]!["settings"]!.AsObject().ContainsKey("max_battles")||
                !legacyLimits["task_templates"]![0]!["settings"]!["task_options"]!["cocoon"]!["reserve_spikes_enabled"]!.GetValue<bool>()||
                legacyLimits["tour_options"]!["max_battles"]!.GetValue<int>()!=25||once!=legacyLimits.ToJsonString())
                throw new Exception("旧设置、队列或模板上限迁移失败");
            UpdateLayout();
            if(Tasks.Count(t=>t.EnableSetting)!=1||!SelectedTask.EnableSetting||Math.Abs(LogPanel.TranslatePoint(new Point(),this).X-logLeft)>.1)
                throw new Exception("切换任务设置后选中状态或日志位置错误");
            if(FindName("SettingsMode") is not null)throw new Exception("设置分类标签仍然存在");
            var dailyOption=SelectedTask.Options.First(o=>o.Key=="daily_tasks");
            var refreshOption=SelectedTask.Options.First(o=>o.Key=="refresh_tasks");
            var spikeCondition=SelectedTask.Options.First(o=>o.Key=="refresh_require_three_spikes");
            dailyOption.Checked=true;refreshOption.Checked=false;spikeCondition.Checked=true;
            if(spikeCondition.IsAvailable)throw new Exception("未开魔典时尖刺条件未禁用");
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var refreshControl=VisualDescendants(TaskOptions).OfType<System.Windows.Controls.CheckBox>().Single(c=>ReferenceEquals(c.DataContext,refreshOption));
            var spikeControl=VisualDescendants(TaskOptions).OfType<System.Windows.Controls.CheckBox>().Single(c=>ReferenceEquals(c.DataContext,spikeCondition));
            if(!refreshControl.IsEnabled||refreshControl.IsChecked!=false||spikeControl.IsEnabled)throw new Exception("依赖开关的实际控件状态错误");
            Capture("wpf-refresh-disabled.png");
            refreshOption.Checked=true;
            if(!spikeCondition.IsAvailable||!spikeCondition.Checked)throw new Exception("魔典依赖选项未恢复");
            dailyOption.Checked=false;
            if(refreshOption.IsAvailable||spikeCondition.IsAvailable)throw new Exception("每日任务依赖链未生效");
            dailyOption.Checked=true;Save();
            if(!settings["task_options"]!["cocoon"]!["daily_tasks"]!.GetValue<bool>()||!settings["task_options"]!["cocoon"]!["refresh_require_three_spikes"]!.GetValue<bool>())throw new Exception("每日及尖刺条件未保存");
            var teams=SelectedTask.Options.First(o=>o.Key=="teams");
            teams.Teams.Clear();teams.AddTeam();teams.Teams[0].TeamId=2;teams.AddTeam();teams.Teams[1].TeamId=3;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            CheckInlineOptions();
            var addTeam=VisualDescendants(TaskOptions).OfType<System.Windows.Controls.Button>().Single(b=>b.IsVisible && b.Content?.ToString()=="添加队伍");
            var teamBoxes=VisualDescendants(TaskOptions).OfType<System.Windows.Controls.ComboBox>().Where(b=>b.IsVisible && b.DataContext is TeamRow).ToArray();
            var addPoint=addTeam.TranslatePoint(new Point(),TaskOptions);
            if(teamBoxes.Length!=2 || teamBoxes.Any(b=>b.TranslatePoint(new Point(),TaskOptions).X<addPoint.X+addTeam.ActualWidth) ||
                Math.Abs(teamBoxes[0].TranslatePoint(new Point(),TaskOptions).Y-addPoint.Y)>2)
                throw new Exception("添加队伍按钮未在列表左上方");
            Capture("wpf-task-settings.png");
            // Configuration must survive a save/load roundtrip, including row order/counts.
            var target=SelectedTask.Options.First(o=>o.Key=="targets");
            if(target.StageChoices.Any(c=>string.IsNullOrWhiteSpace(c.Reward)) || target.StageChoices.Single(c=>c.Id=="spore").Reward!="强化孢子")
                throw new Exception("副本奖励名称未加载");
            // Use a deterministic in-memory fixture. A user's deleted/replaced
            // dungeon rows must not make the offline smoke test fail.
            target.Stages.Clear();for(int i=0;i<4;i++)target.AddStage();
            if(target.StageChoices.Any(c=>c.Id.StartsWith("lower_"))||target.StageChoices.Any(c=>c.DefaultLimit!=0)||target.Counts)throw new Exception("每日仍在副本列表或次数上限未删除");
            if(SelectedTask.Options.Any(o=>o.Key=="max_runs")||settings.ContainsKey("max_battles"))throw new Exception("挑战上限未删除");
            target.Stages.Move(0,3);
            var spikes=SelectedTask.Options.First(o=>o.Key=="reserve_spikes");
            var keepSpikes=SelectedTask.Options.First(o=>o.Key=="reserve_spikes_enabled");
            if(keepSpikes.Checked||spikes.IsAvailable)throw new Exception("未勾选保留尖刺时数量仍启用");
            keepSpikes.Checked=true;
            spikes.Number=3;
            if(!spikes.IsAvailable)throw new Exception("勾选保留尖刺后数量未启用");
            Save();
            var restored=new TaskOption(manifestFor("cocoon","targets"),settings["task_options"]!["cocoon"]!["targets"]);
            if(restored.Stages[3].Id!="gold"||restored.ToJson().AsArray().Any(r=>r!.AsObject().ContainsKey("limit"))||settings["task_options"]!["cocoon"]!["reserve_spikes"]!.GetValue<int>()!=3||!settings["task_options"]!["cocoon"]!["reserve_spikes_enabled"]!.GetValue<bool>())throw new Exception("副本顺序或资源保留未保存，或仍保存次数上限");
            target.Stages.Move(3,0);keepSpikes.Checked=false;Save();
            if(spikes.IsAvailable||settings["task_options"]!["cocoon"]!["reserve_spikes_enabled"]!.GetValue<bool>())throw new Exception("取消保留尖刺未保存");
            restored.Stages.Clear();
            if(new TaskOption(manifestFor("cocoon","targets"),restored.ToJson()).Stages.Count!=0)throw new Exception("删除的副本自动补回");
            restored.AddStage();
            restored.Stages[0].Id="spore";
            if(restored.Stages[0].Limit!=0)throw new Exception("非每日副本仍有默认次数上限");
            restored.AddStage();restored.Stages.Move(1,0);
            while(restored.CanAddStage)restored.AddStage();
            restored.AddStage();
            if(restored.Stages.Count!=restored.StageChoices.Count||restored.Stages.Any(r=>r.Choices.Any(c=>c.Id!=r.Id&&restored.Stages.Any(other=>other.Id==c.Id))))throw new Exception("副本选项出现重复");
            restored.RemoveStage(restored.Stages[0]);
            if(!restored.CanAddStage||new TaskOption(manifestFor("cocoon","targets"),restored.ToJson()).Stages.Count!=restored.Stages.Count)throw new Exception("副本删除未保留");
            while(teams.CanAddTeam)teams.AddTeam();
            teams.AddTeam();
            if(teams.Teams.Count!=5)throw new Exception("队伍扩展上限错误");
            teams.Teams.Move(4,0);teams.RemoveTeam(teams.Teams[1]);Save();
            var savedTeams=new TaskOption(manifestFor("cocoon","teams"),settings["task_options"]!["cocoon"]!["teams"]);
            if(!savedTeams.Teams.Select(t=>t.TeamId).SequenceEqual(teams.Teams.Select(t=>t.TeamId)))throw new Exception("队伍序号/顺序未保存");
            teams.Teams.Clear();Save();
            if(settings["task_options"]!["cocoon"]!["teams"]!.AsArray().Count!=0)throw new Exception("删除所有队伍未保存");
            teams.AddTeam();teams.Teams[0].TeamId=2;teams.AddTeam();teams.Teams[1].TeamId=3;
            TaskOptions.OptionsScroll.ScrollToBottom();
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            Capture("wpf-task-settings-bottom.png");
            SelectedTask=Tasks.First(t=>t.Key=="tribe");
            var tribeOrders=SelectedTask.Options.First(o=>o.Key=="reserve_orders");
            var tribeDefaultTeams=new TaskOption(manifestFor("tribe","teams"),null);
            var tribeDefaultOrders=new TaskOption(manifestFor("tribe","reserve_orders"),null);
            var tribeTotem=SelectedTask.Options.First(o=>o.Key=="random_totem");
            if(!new TaskOption(manifestFor("tribe","random_totem"),null).Checked)
                throw new Exception("部落图腾兜底默认开关错误");
            tribeTotem.Checked=false;Save();
            if(settings["task_options"]!["tribe"]!["random_totem"]!.GetValue<bool>())
                throw new Exception("部落图腾兜底开关未保存");
            tribeTotem.Checked=true;Save();
            if(!tribeDefaultTeams.Teams.Select(t=>t.TeamId).SequenceEqual(new[]{2}) || tribeDefaultOrders.Number!=0)
                throw new Exception("部落冒险默认队伍或保留战令错误");
            tribeOrders.Number=5;Save();
            if(settings["task_options"]!["tribe"]!["reserve_orders"]!.GetValue<int>()!=5)throw new Exception("保留战令未保存");
            tribeOrders.Number=0;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            CheckInlineOptions();Capture("wpf-tribe-settings.png");
            SelectedTask=Tasks.First(t=>t.Key=="rift");
            var riftDefaultTeams=new TaskOption(manifestFor("rift","teams"),null);
            var riftDefaultKeys=new TaskOption(manifestFor("rift","reserve_keys"),null);
            if(!riftDefaultTeams.Teams.Select(t=>t.TeamId).SequenceEqual(new[]{2,1}) || riftDefaultKeys.Number!=0)
                throw new Exception("裂痕默认队伍顺序或钥匙保留数不正确");
            var riftKeys=SelectedTask.Options.First(o=>o.Key=="reserve_keys");
            riftKeys.Number=3;Save();
            if(settings["task_options"]!["rift"]!["reserve_keys"]!.GetValue<int>()!=3)throw new Exception("裂痕保留钥匙未保存");
            riftKeys.Number=0;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            CheckInlineOptions();Capture("wpf-rift-settings.png");
            SelectedTask=Tasks.First(t=>t.Key=="forest");
            var forestMode=SelectedTask.Options.First(o=>o.Key=="mode");
            var forestStrategy=SelectedTask.Options.First(o=>o.Key=="strategy");
            var forestReserve=SelectedTask.Options.First(o=>o.Key=="reserve_points");
            var forestPriority=SelectedTask.Options.First(o=>o.Key=="node_priority");
            if(SelectedTask.ForestModeIndex!=0 || SelectedTask.ForestBasicOptions.Count()!=5 ||
                !SelectedTask.ForestAdvancedOptions.Contains(forestPriority) ||
                new TaskOption(manifestFor("forest","strategy"),null).ChoiceId!="overflow" ||
                new TaskOption(manifestFor("forest","reserve_points"),null).Number!=0 || forestPriority.Rows.Count!=7)
                throw new Exception("森林普通/高级页或默认设置错误");
            forestStrategy.ChoiceId="node";forestReserve.Number=5;
            forestPriority.Rows.Move(1,0);forestPriority.Rows.Last().Enabled=false;Save();
            if(settings["task_options"]!["forest"]!["strategy"]!.GetValue<string>()!="node" ||
                settings["task_options"]!["forest"]!["reserve_points"]!.GetValue<int>()!=5 ||
                settings["task_options"]!["forest"]!["node_priority"]![0]!["id"]!.GetValue<string>()!="beast" ||
                settings["task_options"]!["forest"]!["node_priority"]!.AsArray().Last()!["enabled"]!.GetValue<bool>())
                throw new Exception("森林探索策略或优先级顺序未保存");
            forestStrategy.ChoiceId="overflow";
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var forestTabs=VisualDescendants(TaskOptions).OfType<System.Windows.Controls.TabControl>().Single(t=>t.IsVisible);
            if(forestTabs.Items.Count!=2 || forestTabs.SelectedIndex!=0)
                throw new Exception("森林普通页未显示");
            CheckInlineOptions();Capture("wpf-forest-settings.png");
            forestTabs.SelectedIndex=1;Save();
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);UpdateLayout();
            if(forestMode.ChoiceId!="advanced" ||
                !VisualDescendants(TaskOptions).OfType<System.Windows.Controls.TextBlock>().Any(t=>t.IsVisible && t.Text?.Contains("高级功能不稳定")==true))
                throw new Exception("森林高级页提示或模式保存失败");
            Capture("wpf-forest-advanced-settings.png");
            forestTabs.SelectedIndex=0;Save();
            if(settings["task_options"]!["forest"]!["mode"]!.GetValue<string>()!="simple")
                throw new Exception("森林普通模式未恢复");
            SelectedTask=Tasks.First(t=>t.Key=="arena");
            var opponent=SelectedTask.Options.First(o=>o.Key=="opponent");
            if(opponent.Choices.Count!=4||new TaskOption(manifestFor("arena","opponent"),null).ChoiceId!="power_gap")throw new Exception("斗技场选项默认值错误");
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var opponentBox=VisualDescendants(TaskOptions).OfType<System.Windows.Controls.ComboBox>().Single(b=>b.IsVisible&&ReferenceEquals(b.DataContext,opponent));
            opponentBox.SelectedValue="random";Save();
            if(new TaskOption(manifestFor("arena","opponent"),settings["task_options"]!["arena"]!["opponent"]).ChoiceId!="random")throw new Exception("斗技场对手选择未保存");
            var gapMin=SelectedTask.Options.First(o=>o.Key=="power_gap_min");
            var gapMax=SelectedTask.Options.First(o=>o.Key=="power_gap_max");
            opponentBox.SelectedValue="power_gap";Save();
            if(gapMin.Number!=10000||gapMax.Number!=20000||!gapMin.IsAvailable||!gapMax.IsAvailable)throw new Exception("斗技场战力差默认值错误");
            gapMin.Number=12000;gapMax.Number=25000;Save();
            if(settings["task_options"]!["arena"]!["power_gap_min"]!.GetValue<int>()!=12000||settings["task_options"]!["arena"]!["power_gap_max"]!.GetValue<int>()!=25000)throw new Exception("斗技场战力差未保存");
            opponentBox.SelectedValue="strongest_below";Save();
            if(gapMin.IsAvailable||gapMax.IsAvailable)throw new Exception("斗技场最高战力模式不应启用区间");
            gapMin.Number=10000;gapMax.Number=20000;opponentBox.SelectedValue="power_gap";Save();
            CheckInlineOptions();Capture("wpf-arena-settings.png");
            foreach(var key in new[]{"origin","arena"})
                if(!new TaskOption(manifestFor(key,"teams"),null).Teams.Select(t=>t.TeamId).SequenceEqual(new[]{2}))throw new Exception("PvP默认队伍错误");
            if(new TaskOption(manifestFor("nest","repeat_challenge"),null).Checked)throw new Exception("暴走旷野默认不重复挑战");
            SelectedTask=Tasks.First(t=>t.Key=="tower");
            var towers=SelectedTask.Options.First(o=>o.Key=="towers");
            var feathers=SelectedTask.Options.First(o=>o.Key=="reserve_feathers");feathers.Number=5;Save();
            if(settings["task_options"]!["tower"]!["reserve_feathers"]!.GetValue<int>()!=5)throw new Exception("保留羽毛未保存");
            var emptyTowers=new TaskOption(manifestFor("tower","towers"),new JsonArray());
            emptyTowers.AddStage();emptyTowers.Stages[0].Id="dragon";emptyTowers.AddStage();emptyTowers.Stages.Move(1,0);
            var towerRoundtrip=new TaskOption(manifestFor("tower","towers"),emptyTowers.ToJson());
            if(!towerRoundtrip.Stages.Select(r=>r.Id).SequenceEqual(new[]{"normal","dragon"}))throw new Exception("添加塔与排序未保存");
            emptyTowers.RemoveStage(emptyTowers.Stages[0]);emptyTowers.RemoveStage(emptyTowers.Stages[0]);
            if(new TaskOption(manifestFor("tower","towers"),emptyTowers.ToJson()).Stages.Count!=0)throw new Exception("删除的塔自动补回");
            feathers.Number=0;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            Capture("wpf-tower-settings.png");
            SelectedTask=Tasks.First(t=>t.Key=="rewards");
            if(!SelectedTask.Options.First(o=>o.Key=="collect_idle").Checked)throw new Exception("星律默认未开启");
            var echoRewards=SelectedTask.Options.First(o=>o.Key=="world_echoes");
            if(!echoRewards.Rows.Select(r=>r.Id).SequenceEqual(new[]{"monument","lost","torrent","notes"}) || echoRewards.Rows.Any(r=>!r.Enabled))throw new Exception("世界回响四项默认值错误");
            echoRewards.Rows[1].Enabled=false;Save();
            if(new TaskOption(manifestFor("rewards","world_echoes"),settings["task_options"]!["rewards"]!["world_echoes"]).Rows[1].Enabled)throw new Exception("回响独立开关未保存");
            echoRewards.Rows[1].Enabled=true;Save();
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            Capture("wpf-rewards.png");
            SelectedTask=Tasks.First(t=>t.Key=="other");
            var friendMaster=SelectedTask.Options.First(o=>o.Key=="friend_management");
            var friendPrune=SelectedTask.Options.First(o=>o.Key=="remove_inactive_friends");
            var friendDays=SelectedTask.Options.First(o=>o.Key=="inactive_days");
            var friendAdd=SelectedTask.Options.First(o=>o.Key=="auto_add_friends");
            var bagClear=SelectedTask.Options.First(o=>o.Key=="clear_bag_notifications");
            var contractRewards=SelectedTask.Options.First(o=>o.Key=="collect_contract");
            var starSpores=SelectedTask.Options.First(o=>o.Key=="buy_star_spores");
            var starConversion=SelectedTask.Options.First(o=>o.Key=="convert_star_souls");
            var blueEvolve=SelectedTask.Options.First(o=>o.Key=="evolve_blue_for_star_souls");
            var blueEggs=SelectedTask.Options.First(o=>o.Key=="buy_blue_eggs_for_star_souls");
            var blueEggsAll=SelectedTask.Options.First(o=>o.Key=="buy_all_blue_eggs");
            var starEggTarget=SelectedTask.Options.First(o=>o.Key=="star_egg_target");
            var goldDonation=SelectedTask.Options.First(o=>o.Key=="tribe_gold_donation");
            if(!starSpores.Checked || starConversion.Checked || blueEvolve.Checked || blueEggs.Checked || blueEggsAll.Checked || goldDonation.Checked)
                throw new Exception("饲星商店与金币捐献默认值错误");
            if(blueEvolve.IsAvailable || blueEggs.IsAvailable || blueEggsAll.IsAvailable)
                throw new Exception("饲星蓝怪补料前置条件默认未禁用");
            starConversion.Checked=true;goldDonation.Checked=true;Save();
            if(!settings["task_options"]!["other"]!["convert_star_souls"]!.GetValue<bool>() ||
               !settings["task_options"]!["other"]!["tribe_gold_donation"]!.GetValue<bool>())
                throw new Exception("饲星转化与金币捐献开关未保存");
            if(!blueEvolve.IsAvailable || blueEggs.IsAvailable)
                throw new Exception("究极转化开关的蓝怪依赖错误");
            blueEvolve.Checked=true;
            if(!blueEggs.IsAvailable || blueEggsAll.IsAvailable)
                throw new Exception("蓝怪进化与怪兽茧兑换依赖错误");
            blueEggs.Checked=true;
            if(!blueEggsAll.IsAvailable || !starEggTarget.IsAvailable || starEggTarget.ChoiceId!="停顿")
                throw new Exception("怪兽茧兑换设置未启用或默认目标错误");
            blueEggsAll.Checked=true;Save();
            if(!settings["task_options"]!["other"]!["evolve_blue_for_star_souls"]!.GetValue<bool>() ||
               !settings["task_options"]!["other"]!["buy_blue_eggs_for_star_souls"]!.GetValue<bool>() ||
               !settings["task_options"]!["other"]!["buy_all_blue_eggs"]!.GetValue<bool>())
                throw new Exception("蓝怪补料设置未实时保存");
            blueEggsAll.Checked=false;blueEggs.Checked=false;blueEvolve.Checked=false;Save();
            starSpores.Checked=false;
            if(starConversion.IsAvailable || blueEvolve.IsAvailable || blueEggs.IsAvailable || blueEggsAll.IsAvailable || !goldDonation.IsAvailable)
                throw new Exception("饲星转化前置条件或捐献独立开关错误");
            starSpores.Checked=true;starConversion.Checked=false;goldDonation.Checked=false;Save();
            foreach(var key in new[]{"collect_daily_single","collect_plane_lord"})
            {
                var freeReward=SelectedTask.Options.First(o=>o.Key==key);
                if(!freeReward.Checked)throw new Exception("新增免费领奖默认未开启");
                freeReward.Checked=false;Save();
                if(settings["task_options"]!["other"]![key]!.GetValue<bool>())throw new Exception("免费领奖开关未保存");
                freeReward.Checked=true;
            }
            var boxes=SelectedTask.Options.First(o=>o.Key=="open_monster_boxes");
            var boxMode=SelectedTask.Options.First(o=>o.Key=="monster_box_mode");
            var boxTarget=SelectedTask.Options.First(o=>o.Key=="monster_box_target");
            var boxLimit=SelectedTask.Options.First(o=>o.Key=="monster_box_limit");
            if(boxes.Checked||boxMode.IsAvailable||boxTarget.IsAvailable||boxLimit.IsAvailable||boxTarget.Choices.Count!=8)
                throw new Exception("幻化怪兽茧默认关闭或依赖设置不正确");
            boxes.Checked=true;boxMode.ChoiceId="specified";boxTarget.ChoiceId="停顿";boxLimit.Number=2;Save();
            if(!boxTarget.IsAvailable||!boxLimit.IsAvailable||settings["task_options"]!["other"]!["monster_box_target"]!.GetValue<string>()!="停顿"||
               settings["task_options"]!["other"]!["monster_box_limit"]!.GetValue<int>()!=2)throw new Exception("幻化怪兽茧指定和数量未保存");
            boxMode.ChoiceId="random";
            if(boxTarget.IsAvailable)throw new Exception("随机开茧不应启用指定怪兽");
            boxMode.ChoiceId="balanced";boxes.Checked=false;boxLimit.Number=0;boxTarget.ChoiceId="暴龙";Save();
            if(boxMode.IsAvailable||boxTarget.IsAvailable||boxLimit.IsAvailable)throw new Exception("关闭开茧后的前置条件未禁用");
            var purpleEvolution=SelectedTask.Options.First(o=>o.Key=="evolve_blue_monsters");
            var purpleMode=SelectedTask.Options.First(o=>o.Key=="blue_evolution_mode");
            var purpleCount=SelectedTask.Options.First(o=>o.Key=="blue_evolution_count");
            if(purpleEvolution.Checked||purpleMode.IsAvailable||purpleCount.IsAvailable||purpleMode.ChoiceId!="count"||purpleCount.Number!=1)
                throw new Exception("蓝怪进化紫怪默认开关或依赖错误");
            purpleEvolution.Checked=true;purpleCount.Number=3;Save();
            if(!purpleMode.IsAvailable||!purpleCount.IsAvailable||settings["task_options"]!["other"]!["blue_evolution_count"]!.GetValue<int>()!=3)
                throw new Exception("指定进化只数未启用或保存");
            purpleMode.ChoiceId="until_empty";Save();
            if(purpleCount.IsAvailable||settings["task_options"]!["other"]!["blue_evolution_mode"]!.GetValue<string>()!="until_empty")
                throw new Exception("材料耗尽模式仍允许设置只数或未保存");
            purpleMode.ChoiceId="count";purpleEvolution.Checked=false;purpleCount.Number=1;Save();
            if(purpleMode.IsAvailable||purpleCount.IsAvailable)throw new Exception("关闭进化后依赖未禁用");
            if(!contractRewards.Checked || SelectedTask.Options.IndexOf(contractRewards)>=SelectedTask.Options.IndexOf(bagClear))throw new Exception("契约任务默认值或顺序错误");
            if(friendDays.Number!=5 || friendPrune.Checked || !bagClear.Checked)throw new Exception("其他任务默认值错误");
            friendMaster.Checked=true;friendPrune.Checked=false;
            if(friendDays.IsAvailable || !friendAdd.IsAvailable)throw new Exception("好友清理天数依赖未生效");
            friendPrune.Checked=true;friendDays.Number=14;
            if(!friendDays.IsAvailable)throw new Exception("开启清理后天数仍禁用");
            friendMaster.Checked=false;
            if(friendDays.IsAvailable || friendAdd.IsAvailable || !bagClear.IsAvailable || !contractRewards.IsAvailable)throw new Exception("好友、契约和背包子任务没有独立控制");
            contractRewards.Checked=false;Save();
            if(settings["task_options"]!["other"]!["collect_contract"]!.GetValue<bool>())throw new Exception("契约关闭未保存");
            contractRewards.Checked=true;
            friendMaster.Checked=true;friendDays.Number=5;friendPrune.Checked=false;Save();
            if(settings["task_options"]!["other"]!["inactive_days"]!.GetValue<int>()!=5)throw new Exception("好友未登录天数未保存");
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);UpdateLayout();
            var daysControl=VisualDescendants(TaskOptions).OfType<HandyControl.Controls.NumericUpDown>().Single(c=>ReferenceEquals(c.DataContext,friendDays));
            if(daysControl.IsEnabled)throw new Exception("未开启好友清理时天数控件没有变灰");
            TaskList.ScrollIntoView(SelectedTask);UpdateLayout();
            await Task.Delay(300); // Let the checkbox glyph animations finish before capture.
            Capture("wpf-other-settings.png");
            if(VisualDescendants(TaskControlPanel).OfType<System.Windows.Controls.TextBlock>().Any(t=>t.Text=="完成后"))throw new Exception("旧完成后区域未移除");
            SelectedTask=Tasks.First(t=>t.Key=="copies");Save();
            if(settings["task_settings_selection"]!.GetValue<string>()!="copies")throw new Exception("齿轮选择未保存");
            Pages.SelectedItem = SettingsTab;
            await Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
            Capture("wpf-settings.png");
            OverviewOrderBox.IsChecked=true;Save();
            if(!UnorderedTasks || !settings["unordered_tasks"]!.GetValue<bool>())throw new Exception("概览顺序开关未保存");
            OverviewOrderBox.IsChecked=false;Save();
            if(UnorderedTasks || settings["unordered_tasks"]!.GetValue<bool>())throw new Exception("任务顺序未恢复");
            AutoThreeShots=false;Save();
            if(settings["stamina_settings"]!["auto_three_shots"]!.GetValue<bool>())throw new Exception("关闭三发未保存");
            AutoThreeShots=true;Save();
            foreach(var key in new[]{"copies","hunt","main"})
            {
                SelectedTask=Tasks.First(t=>t.Key==key);
                var refill=SelectedTask.Options.First(o=>o.Key=="auto_three_shots");
                var potion=SelectedTask.Options.First(o=>o.Key=="auto_potions");
                if(!refill.Checked||potion.Checked)throw new Exception("体力补充默认值错误");
                refill.Checked=false;potion.Checked=true;Save();
                if(settings["task_options"]![key]!["auto_three_shots"]!.GetValue<bool>() || !settings["task_options"]![key]!["auto_potions"]!.GetValue<bool>())throw new Exception("独立体力设置未保存");
                refill.Checked=true;potion.Checked=false;
            }
            foreach(var key in new[]{"origin","arena"})
                if(!Tasks.First(t=>t.Key==key).Options.First(o=>o.Key=="auto_settle").Checked)throw new Exception("PVP自动结算默认值错误");
            Pages.SelectedIndex=0;
            SelectedTask=Tasks.First(t=>t.Key=="nest");
            var buffs=SelectedTask.Options.First(o=>o.Key=="buff_priority");
            var wall=SelectedTask.Options.Single(o=>o.Key=="wall_mode");
            if(wall.ChoiceId!="attack" || wall.Choices.Count!=3)throw new Exception("暴走战墙默认值或选项错误");
            wall.ChoiceId="defense";Save();
            if(settings["task_options"]!["nest"]!["wall_mode"]!.ToString()!="defense" ||
                settings["task_queue"]!.AsArray().First(t=>t!["key"]!.ToString()=="nest")!["options"]!["wall_mode"]!.ToString()!="defense")
                throw new Exception("战墙设置未随任务实例保存");
            wall.ChoiceId="attack";Save();
            if(buffs.Rows.Count!=12)throw new Exception("旷野增益选项缺失");
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);Capture("wpf-rampage-priority.png");
            SelectedTask=Tasks.First(t=>t.Key=="finish");
            if(Tasks.Last().Key!="finish" || SelectedTask.Options.Where(o=>o.Key!="close_on_partial").Any(o=>!o.Checked) ||
                SelectedTask.Options.Single(o=>o.Key=="close_on_partial").Checked)throw new Exception("结束关闭设置错误");
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);Capture("wpf-finish.png");
            var celebrations=Tasks.First(t=>t.Key=="celebration");
            if(!celebrations.Options.First(o=>o.Key=="triad").Checked ||
                celebrations.Options.Where(o=>o.Key is "giant" or "daily_puzzle").Any(o=>o.Checked) ||
                Tasks.First(t=>t.Key=="other").Options.Any(o=>o.Key=="daily_puzzle"))
                throw new Exception("庆典活动未默认只开启三阵");
            var giantOption=celebrations.Options.First(o=>o.Key=="giant");
            if(celebrations.Options.First(o=>o.Key=="giant_teams").IsAvailable)throw new Exception("巨物未开启时阵容未禁用");
            giantOption.Checked=true;
            if(!celebrations.Options.First(o=>o.Key=="giant_teams").IsAvailable)throw new Exception("巨物阵容未随开关启用");
            giantOption.Checked=false;
            SelectedTask=celebrations;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);Capture("wpf-celebration.png");
            var older=new JsonObject {
                ["tasks"]=new JsonArray("giant","other"),
                ["task_order"]=new JsonArray("giant","rewards","other"),
                ["task_queue"]=new JsonArray(new JsonObject { ["id"]="giant",["key"]="giant",["name"]="进击巨物",["enabled"]=true,["options"]=new JsonObject() }),
                ["task_options"]=new JsonObject { ["giant"]=new JsonObject { ["auto_settle"]=false },
                                                  ["other"]=new JsonObject { ["daily_puzzle"]=true } }
            };
            MigrateCelebrationTasks(older);
            if(older["task_order"]!.AsArray().Select(k=>k!.ToString()).ToArray() is not ["celebration","rewards","other"] ||
                !older["task_queue"]!.AsArray().Any(k=>k?["key"]?.ToString()=="celebration") ||
                older["task_options"]?["celebration"]?["giant_auto_settle"]?.GetValue<bool>()!=false ||
                older["task_options"]?["celebration"]?["giant"]?.GetValue<bool>()!=false ||
                older["task_options"]?["celebration"]?["triad"]?.GetValue<bool>()!=true ||
                older["task_options"]?["other"]?["daily_puzzle"] is not null)
                throw new Exception("庆典活动迁移错误");
            older["task_options"]!["celebration"]!["triad"]=false;
            MigrateCelebrationTasks(older);
            if(older["task_options"]!["celebration"]!["triad"]!.GetValue<bool>())throw new Exception("重复迁移覆盖了庆典开关");
            SelectedTask=Tasks.First(t=>t.Key=="copies");Save();
            FollowRunningTask=false;Save();
            if(settings["follow_running_task"]!.GetValue<bool>())throw new Exception("任务跟随开关未保存");
            using(var current=JsonDocument.Parse("[\"hunt\",\"运行中\"]"))
            {
                HandleEvent("task",current.RootElement);
                if(SelectedTask?.Key!="copies")throw new Exception("关闭跟随仍然切换设置");
                FollowRunningTask=true;HandleEvent("task",current.RootElement);
                if(SelectedTask?.Key!="hunt")throw new Exception("运行任务设置未跟随");
            }
            SelectedTask=Tasks.First(t=>t.Key=="cocoon");
            await Begin("diagnostic", fake: true);
            if (Pages.SelectedItem!=ToolsTab || ToolsPages.SelectedIndex!=2 || Status != "检测完成" || !ResourceSummary.Contains("7/161") || !Logs.Any(l=>l.Text=="正在连接 MuMu…")) throw new Exception("诊断过程或结果未正确显示");
            var triadSettle=Tasks.First(t=>t.Key=="celebration").Options.First(o=>o.Key=="triad_auto_settle");
            triadSettle.Checked=false;Save();
            if(settings["task_options"]!["celebration"]!["triad_auto_settle"]!.GetValue<bool>())throw new Exception("三阵入局自动结算关闭未保存");
            triadSettle.Checked=true;
            await Begin("puzzle",fake:true);
            if(Pages.SelectedItem!=ToolsTab || ToolsPages.SelectedIndex!=0 || !Idle || PuzzleCells[0]!="8" || !PuzzleSummary.Contains("24"))throw new Exception("拼二工具反馈或独立页面异常");
            var puzzleTarget=PuzzleTool.Options.First(o=>o.Key=="puzzle_target_score");
            var puzzleGames=PuzzleTool.Options.First(o=>o.Key=="puzzle_max_games");
            if(PuzzleTool.Options.Count!=2||puzzleTarget.Number!=7172||puzzleTarget.Max!=7172||puzzleGames.Number!=0)
                throw new Exception("拼二默认目标或不限局数错误");
            puzzleTarget.Number=3456;puzzleGames.Number=4;Save();
            if(settings["puzzle_target_score"]!.GetValue<int>()!=3456||settings["puzzle_max_games"]!.GetValue<int>()!=4)
                throw new Exception("拼二自定义分数或局数未保存");
            if(settings.ContainsKey("puzzle_max_moves")||settings.ContainsKey("puzzle_goal"))throw new Exception("仍保留旧拼二限制");
            puzzleTarget.Number=7173;bool rejected=false;
            try { Save(); } catch(InvalidOperationException) { rejected=true; }
            if(!rejected)throw new Exception("拼二允许超过理论最高分");
            puzzleTarget.Number=7172;puzzleGames.Number=0;Save();
            if(settings["puzzle_max_games"]!.GetValue<int>()!=0)throw new Exception("拼二不限局数未保存");
            var puzzleSpec=JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"tools.json")))!.AsArray().First(t=>t!["key"]!.GetValue<string>()=="puzzle")!;
            var legacyPuzzle=new JsonObject { ["puzzle_goal"]="first",["puzzle_max_games"]=100,["puzzle_max_moves"]=3000 };
            MigratePuzzleSettings(legacyPuzzle,puzzleSpec);
            if(legacyPuzzle["puzzle_target_score"]!.GetValue<int>()!=7172||legacyPuzzle["puzzle_max_games"]!.GetValue<int>()!=0||legacyPuzzle.ContainsKey("puzzle_max_moves"))
                throw new Exception("旧拼二冲榜配置迁移错误");
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            Capture("wpf-tools.png");
            await Begin("tour",fake:true);
            if(ToolsPages.SelectedIndex!=1||!Idle||!ToolLogs.Any(l=>l.Text.Contains("巡游完成")))throw new Exception("巡游工具独立桥接失败");
            if(TourTool.Options.First(o=>o.Key=="teams").Teams.Count!=3)throw new Exception("巡游阵容选项未加载");
            TourTool.Options.First(o=>o.Key=="max_battles").Number=25;Save();
            if(settings["tour_options"]!["max_battles"]!.GetValue<int>()!=25)throw new Exception("巡游设置未保存");
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            Capture("wpf-tour.png");
            await Begin("abyss",fake:true);
            if(!Idle||!ToolLogs.Any(l=>l.Text.Contains("已选择压制词缀")))throw new Exception("深渊先遣桥接失败");
            Pages.SelectedIndex=0;SelectedTask=Tasks.First(t=>t.Key=="other");
            AbyssExpander.IsExpanded=true;AbyssSwitch.IsChecked=true;AbyssExpander.BringIntoView();
            if(AbyssTool.Options.First(o=>o.Key=="teams").Teams.Count!=3)throw new Exception("深渊先遣阵容未加载");
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            if(!AbyssOptionsView.IsEnabled||SelectedTask.AbyssOption?.Checked!=true)throw new Exception("深渊先遣未接入其他任务开关");
            Save();
            if(settings["task_options"]!["other"]!["challenge_abyss"]?.GetValue<bool>()!=true)throw new Exception("深渊先遣子任务未保存");
            Capture("wpf-abyss.png");
            AbyssSwitch.IsChecked=false;AbyssExpander.IsExpanded=false;
            Pages.SelectedItem=SettingsTab;
            if(TriggerEventsTool.Options.Count!=4||TriggerEventsTool.Options.Any(o=>!o.Checked))throw new Exception("触发事件默认开关错误");
            triggerSmokePath=Path.Combine(App.DiagnosticsRoot,"wpf-events-autosave.json");
            File.WriteAllText(triggerSmokePath,"{\"unrelated\":\"keep\"}");
            var triggerMerchant=TriggerEventsTool.Options.First(o=>o.Key=="merchant");
            triggerMerchant.Checked=false;
            if(MerchantEventEnabled||JsonNode.Parse(File.ReadAllText(triggerSmokePath))!["trigger_events"]!["merchant"]!.GetValue<bool>())throw new Exception("商人触发关闭未保存");
            foreach(var option in TriggerEventsTool.Options)
            {
                option.Checked=false;
                var savedEvents=JsonNode.Parse(File.ReadAllText(triggerSmokePath))!;
                if(savedEvents["trigger_events"]![option.Key]!.GetValue<bool>()||savedEvents["unrelated"]!.GetValue<string>()!="keep")throw new Exception("事件开关未独立保存");
                option.Checked=true;
            }
            triggerSmokePath=null;MerchantExpander.IsExpanded=true;MerchantExpander.BringIntoView();
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var merchantMode=MerchantTool.Options.First(o=>o.Key=="mode");
            var merchantItems=MerchantTool.Options.First(o=>o.Key=="items");
            var merchantBudget=MerchantTool.Options.First(o=>o.Key=="diamond_budget");
            if(merchantMode.ChoiceId!="skip"||merchantItems.Rows.Any(r=>r.Enabled)||merchantItems.IsAvailable||merchantBudget.IsAvailable)
                throw new Exception("神秘商人默认模式、物品或前置选项错误");
            merchantSmokePath=Path.Combine(App.DiagnosticsRoot,"wpf-merchant-autosave.json");
            File.WriteAllText(merchantSmokePath,"{\"unrelated\":\"keep\"}");
            var merchantModeBox=VisualDescendants(MerchantOptionsView).OfType<System.Windows.Controls.ComboBox>().Single(b=>ReferenceEquals(b.DataContext,merchantMode));
            merchantModeBox.SelectedValue="buy";
            var spore=merchantItems.Rows.First(r=>r.Id=="spore");
            var sporeBox=VisualDescendants(MerchantOptionsView).OfType<System.Windows.Controls.CheckBox>().Single(b=>ReferenceEquals(b.DataContext,spore));
            sporeBox.IsChecked=true;merchantBudget.Number=200;
            merchantItems.Rows.Move(1,0);
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var savedMerchant=JsonNode.Parse(File.ReadAllText(merchantSmokePath))!;
            if(!merchantItems.IsAvailable||!merchantBudget.IsAvailable||savedMerchant["merchant_options"]!["mode"]!.GetValue<string>()!="buy"||
               savedMerchant["merchant_options"]!["items"]![0]!["id"]!.GetValue<string>()!="spore"||
               !savedMerchant["merchant_options"]!["items"]![0]!["enabled"]!.GetValue<bool>()||
               savedMerchant["merchant_options"]!["diamond_budget"]!.GetValue<int>()!=200||savedMerchant["unrelated"]!.GetValue<string>()!="keep")
                throw new Exception("神秘商人自动保存或购买选项异常");
            Capture("wpf-merchant.png");
            merchantModeBox.SelectedValue="stop";
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            if(merchantItems.IsAvailable||merchantBudget.IsAvailable||JsonNode.Parse(File.ReadAllText(merchantSmokePath))!["merchant_options"]!["mode"]!.GetValue<string>()!="stop")
                throw new Exception("神秘商人停止模式未保存或未禁用购买选项");
            merchantModeBox.SelectedValue="random";
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            if(merchantItems.IsAvailable||merchantBudget.IsAvailable||JsonNode.Parse(File.ReadAllText(merchantSmokePath))!["merchant_options"]!["mode"]!.GetValue<string>()!="random")
                throw new Exception("神秘商人随机模式未保存或未禁用购买选项");
            Capture("wpf-merchant-random.png");
            merchantModeBox.SelectedValue="skip";sporeBox.IsChecked=false;merchantBudget.Number=240;
            merchantSmokePath=null;
            Pages.SelectedItem=ToolsTab;ToolsPages.SelectedItem=FreeSummonTab;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            if(FreeSummonEnabled)throw new Exception("免费造唤应默认关闭");
            if(FreeSummonTab.TranslatePoint(new Point(),ToolsPages).X+FreeSummonTab.ActualWidth>ToolsPages.ActualWidth+1)
                throw new Exception("免费造唤页签超出可见区域");
            freeSummonSmokePath=Path.Combine(App.DiagnosticsRoot,"wpf-summon-autosave.json");
            File.WriteAllText(freeSummonSmokePath,"{\"unrelated\":\"keep\"}");
            FreeSummonSwitch.IsChecked=true;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var savedSummon=JsonNode.Parse(File.ReadAllText(freeSummonSmokePath))!;
            if(!savedSummon["free_summon_enabled"]!.GetValue<bool>()||savedSummon["unrelated"]!.GetValue<string>()!="keep")
                throw new Exception("免费造唤未实时保存或覆盖其他设置");
            FreeSummonSwitch.IsChecked=false;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            if(JsonNode.Parse(File.ReadAllText(freeSummonSmokePath))!["free_summon_enabled"]!.GetValue<bool>())
                throw new Exception("免费造唤关闭未保存");
            Capture("wpf-free-summon.png");freeSummonSmokePath=null;
            Pages.SelectedIndex=0;SelectedTask=Tasks.First(t=>t.Key=="other");
            WildExpander.IsExpanded=true;WildExpander.BringIntoView();
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            if(WildGrades.Count!=5||WildGrades.Any(g=>g.Enabled)||WildCaptureEnabled)throw new Exception("野生捕捉不是默认全关");
            var ultimate=WildGrades.First(g=>g.Id=="ultimate");
            if(ultimate.Probability!=80||WildGrades.Where(g=>g.Id is "immortal" or "awakened").Any(g=>g.Probability!=100))throw new Exception("野生捕捉默认概率错误");
            wildSmokePath=Path.Combine(App.DiagnosticsRoot,"wpf-wild-autosave.json");
            File.WriteAllText(wildSmokePath,"{\"unrelated\":\"keep\",\"task_options\":{\"hunt\":{\"team\":\"3\"}}}");
            WildCaptureSwitch.IsChecked=true;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var gradeBox=VisualDescendants(WildGradesList).OfType<System.Windows.Controls.CheckBox>().Single(b=>ReferenceEquals(b.DataContext,ultimate));
            gradeBox.IsChecked=true;
            var probabilityInput=VisualDescendants(WildGradesList).OfType<HandyControl.Controls.NumericUpDown>().Single(n=>ReferenceEquals(n.DataContext,ultimate));
            probabilityInput.Value=85;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var savedWild=JsonNode.Parse(File.ReadAllText(wildSmokePath))!;
            if(!savedWild["wild_capture_enabled"]!.GetValue<bool>()||!savedWild["wild_capture"]!["ultimate"]!["enabled"]!.GetValue<bool>()||savedWild["wild_capture"]!["ultimate"]!["probability"]!.GetValue<int>()!=85)throw new Exception("捕捉修改后未自动写盘");
            if(savedWild["unrelated"]!.GetValue<string>()!="keep"||savedWild["task_options"]!["hunt"]!["team"]!.GetValue<string>()!="3")throw new Exception("捕捉自动保存覆盖其他设置");
            var wildSpec=JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"tools.json")))!.AsArray().First(t=>t!["key"]!.GetValue<string>()=="wild_capture")!;
            var restoredWild=new WildGrade(wildSpec["rarities"]!.AsArray().First(g=>g!["id"]!.GetValue<string>()=="ultimate")!,savedWild["wild_capture"]!["ultimate"]);
            if(!restoredWild.Enabled||restoredWild.Probability!=85)throw new Exception("捕捉设置重载未保留");
            probabilityInput.Value=81;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            if(WildSaveErrorVisibility!=Visibility.Visible||JsonNode.Parse(File.ReadAllText(wildSmokePath))!["wild_capture"]!["ultimate"]!["probability"]!.GetValue<int>()!=85)throw new Exception("无效概率未提示或覆盖了有效值");
            WildCaptureSwitch.IsChecked=false;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            savedWild=JsonNode.Parse(File.ReadAllText(wildSmokePath))!;
            if(savedWild["wild_capture_enabled"]!.GetValue<bool>()||!savedWild["wild_capture"]!["ultimate"]!["enabled"]!.GetValue<bool>()||WildGradesList.IsEnabled)throw new Exception("独立关闭开关未保存、未禁用品级或清掉了选择");
            ultimate.Probability=80;WildCaptureSwitch.IsChecked=true;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            if(WildSaveErrorVisibility!=Visibility.Collapsed)throw new Exception("合法概率没有清除错误");
            var probabilityInputs=VisualDescendants(WildGradesList).OfType<HandyControl.Controls.NumericUpDown>().ToArray();
            if(probabilityInputs.Length!=5||probabilityInputs.Any(n=>n.Increment!=5)||probabilityInputs.Count(n=>n.IsEnabled)!=1)throw new Exception("野生捕捉概率控件步长或前置条件错误");
            var phantom=WildGrades.First(g=>g.Id=="phantom");
            var phantomInput=probabilityInputs.Single(n=>ReferenceEquals(n.DataContext,phantom));
            if(phantom.Probability!=90||phantomInput.Minimum!=90||phantomInput.Maximum!=100)
                throw new Exception("蓝色幻化怪兽捕捉概率默认值或下限不是90%");
            var phantomSpec=wildSpec["rarities"]!.AsArray().First(g=>g!["id"]!.GetValue<string>()=="phantom")!;
            if(new WildGrade(phantomSpec,JsonNode.Parse("{\"enabled\":true,\"probability\":80}"))!.Probability!=90 ||
               new WildGrade(phantomSpec,JsonNode.Parse("{\"enabled\":false,\"probability\":95}"))!.Probability!=95)
                throw new Exception("蓝色捕捉旧设置迁移错误");
            if(VisualDescendants(WildExpander).OfType<System.Windows.Controls.Button>().Any(b=>b.Content?.ToString()=="保存设置")||VisualDescendants(WildExpander).OfType<System.Windows.Controls.TextBlock>().Any(t=>t.Text.Contains("只捕捉勾选品级")))throw new Exception("野生捕捉仍有保存按钮或状态文案");
            Capture("wpf-wild-capture.png");
            ultimate.Enabled=false;WildCaptureSwitch.IsChecked=false;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            wildSmokePath=null;
            WildExpander.IsExpanded=false;AbyssExpander.IsExpanded=false;
            TaskOptions.OptionsScroll.ScrollToTop();
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var other=SelectedTask!;
            var listed=other.OtherSections.SelectMany(s=>new[]{s.Toggle}.Concat(s.Details)).Select(o=>o.Key).Append("challenge_abyss").ToArray();
            if(listed.Length!=other.Options.Count||listed.Distinct().Count()!=listed.Length)throw new Exception("其他任务折叠后遗漏或重复设置");
            var sections=VisualDescendants(TaskOptions).OfType<System.Windows.Controls.Expander>().Where(e=>e.Visibility==Visibility.Visible && e.DataContext is TaskOptionSection).ToArray();
            var expectedGroups=other.OtherSections.Where(s=>s.Details.Any()).Select(s=>s.Toggle.Key).ToHashSet();
            var renderedGroups=sections.Select(e=>((TaskOptionSection)e.DataContext).Toggle.Key);
            if(sections.Length!=expectedGroups.Count||!expectedGroups.SetEquals(renderedGroups)||sections.Any(e=>e.IsExpanded))
                throw new Exception("其他任务分组或默认折叠状态错误");
            Capture("wpf-other-collapsed.png");
            var friends=sections.Single(e=>((TaskOptionSection)e.DataContext).Toggle.Key=="friend_management");
            other.Options.Single(o=>o.Key=="friend_management").Checked=true;
            other.Options.Single(o=>o.Key=="remove_inactive_friends").Checked=false;
            friends.IsExpanded=true;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var friendNumber=VisualDescendants(friends).OfType<HandyControl.Controls.NumericUpDown>().Single(n=>((TaskOption)n.DataContext).Key=="inactive_days");
            if(friendNumber.ActualWidth<70||friendNumber.IsEnabled)throw new Exception("好友折叠设置未渲染或依赖失效");
            other.Options.Single(o=>o.Key=="remove_inactive_friends").Checked=true;
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            if(!friendNumber.IsEnabled)throw new Exception("展开后好友清理天数未启用");
            friendNumber.Value=7;Save();
            friends.IsExpanded=false;friends.IsExpanded=true;
            if(settings["task_options"]!["other"]!["inactive_days"]!.GetValue<int>()!=7)throw new Exception("折叠丢失设置");
            Capture("wpf-other-expanded.png");
            friends.IsExpanded=false;
            foreach(var group in sections.Where(e=>e!=friends))
            {
                group.IsExpanded=true;group.BringIntoView();
                await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
                UpdateLayout();
                foreach(var label in VisualDescendants(group).OfType<System.Windows.Controls.TextBlock>().Where(t=>t.IsVisible && t.DataContext is TaskOption o && t.Text==o.Label))
                    if(label.TranslatePoint(new Point(),TaskOptions).X+label.DesiredSize.Width>TaskOptions.ActualWidth-10)
                        throw new Exception("其他任务选项超出设置栏："+label.Text);
                Capture("wpf-other-"+((TaskOptionSection)group.DataContext).Toggle.Key+".png");
                group.IsExpanded=false;
            }
            if(ToolsPages.Items.OfType<System.Windows.Controls.TabItem>().Any(t=>t.Header?.ToString() is "野生怪兽" or "深渊先遣"))throw new Exception("小工具仍有迁移后的页签");
            var closeWarning=Tasks.First(t=>t.Key=="finish").Options.First(o=>o.Key=="close_app");
            if(!closeWarning.Notice.Contains("无法看到捕捉怪兽")||closeWarning.NoticeVisibility!=Visibility.Visible)throw new Exception("关闭程序缺少捕捉提醒");
            using(var captureResult=JsonDocument.Parse("{\"status\":\"completed\",\"wild_captures\":[{\"rarity\":\"ultimate\",\"message\":\"成功捕捉究极怪兽-幽鬼\"},{\"rarity\":\"awakened\",\"message\":\"觉醒怪兽-示例：未勾选品级\"}]}"))
                HandleEvent("result",captureResult.RootElement);
            if(runLogs.Current?.Title!="野生怪兽 · 结束提醒"||runLogs.Current.IsExpanded!=true||runLogs.Current.Lines[0].Color!="WildUltimateBrush"||runLogs.Current.Lines[1].Color!="WildAwakenedBrush")throw new Exception("野生捕捉结束摘要颜色或展开状态错误");
            using(var emptyWild=JsonDocument.Parse("{\"status\":\"completed\",\"wild_checks\":[{\"status\":\"absent\",\"message\":\"当前野生怪兽未出现，跳过捕捉\"}]}"))
                HandleEvent("result",emptyWild.RootElement);
            if(runLogs.Current?.Title!="野生怪兽 · 检查结果"||runLogs.Current.Lines.Last().Color!="MessageLogBrush")throw new Exception("野生未刷新不应显示捕捉失败");
            using(var wildFailure=JsonDocument.Parse("{\"status\":\"partial\",\"wild_checks\":[{\"status\":\"navigation_failed\",\"message\":\"野生怪兽检查未完成：事件列表未打开；是否刷新尚未确认\"}]}"))
                HandleEvent("result",wildFailure.RootElement);
            if(runLogs.Current?.Title!="野生怪兽 · 检查结果"||runLogs.Current.Lines.Last().Color!="WarningLogBrush")throw new Exception("野生检查失败应明确显示导航告警");
            using(var observed=JsonDocument.Parse("{\"stamina\":5,\"stamina_cap\":163,\"diamonds\":1181,\"gold_text\":\"471万\"}"))
                HandleEvent("resources",observed.RootElement);
            if(!ResourceSummary.Contains("最近观察：体力 5/163"))throw new Exception("资源实时反馈未更新");
            using(var partial=JsonDocument.Parse("{\"status\":\"blocked\",\"resources_end\":null,\"resources_start\":{\"stamina\":123,\"stamina_cap\":163},\"resources_last_observed\":{\"stamina\":5,\"stamina_cap\":163}}"))
                HandleEvent("result",partial.RootElement);
            if(!ResourceSummary.Contains("最近观察：体力 5/163")||ResourceSummary.Contains("123/163"))throw new Exception("停止后资源回退到了开始时数值");
            var run = Begin("run", fake: true);
            await Task.Delay(400);
            if(Logs.Any(l=>l.Text.Contains("捕捉究极怪兽")) || ResourceSummary!="" ||
               LogGroups.Select(g=>g.Run).Distinct().Count()!=1)
                throw new Exception("点击开始后未清除上次运行信息和资源显示");
            if (Idle || !CanStop || StopButton.Visibility != Visibility.Visible) throw new Exception("运行状态未正确显示");
            Capture("wpf-running.png");
            var disabledRows=VisualDescendants(TaskList).OfType<System.Windows.Controls.ListBoxItem>().ToArray();
            if(disabledRows.Length==0||disabledRows.Any(e=>e.IsEnabled||e.Opacity<.7))throw new Exception("运行时任务列表过淡或仍可修改");
            RequestStop(); await run;
            if (!Idle || Status != "已停止") throw new Exception("停止结果错误");
            settings["_smoke_stall"]=true;
            await Begin("diagnostic",fake:true);
            settings.Remove("_smoke_stall");
            if(!Idle||Status!="已停止"||!Logs.Any(l=>l.Text.Contains("连续2秒没有反馈")))throw new Exception("无反馈超时未解除运行状态");
            Capture("wpf-feedback-timeout.png");
            await CheckLogGroups();
            File.WriteAllText(Path.Combine(App.DiagnosticsRoot,"wpf-smoke.json"), JsonSerializer.Serialize(new { status = "passed", tasks = Tasks.Count, bridge = "passed", continue_from_task="passed", stop = "passed", timeout="passed", fixed_columns="passed", gear_selection="passed", dynamic_teams = "passed", dynamic_dungeons="passed", daily_checkbox="passed", dependent_options="passed", task_follow="passed", overview_order="passed", inline_options="passed", team_button_left="passed", reward_labels="passed", tribe_settings="passed", other_settings="passed", other_collapsible="passed", other_tool_migration="passed", resource_reserves="passed", resource_feedback="passed", refill_setting = "passed", log_groups="passed", log_history_limit="passed", log_reset="passed", run_folders="passed", tools_page="passed", puzzle_feedback="passed", puzzle_goals="passed", tour_tool="passed", triad_auto_settle="passed", no_game_input = true }));
        }
        catch (Exception exc)
        {
            File.WriteAllText(Path.Combine(App.DiagnosticsRoot,"wpf-smoke.json"), JsonSerializer.Serialize(new { status = "failed", reason = exc.ToString() }));
        }
        Close();
    }
    private async Task CheckLogGroups()
    {
        var history=new RunLogs();
        for(int i=0;i<12;i++)
        {
            history.Begin("连接与准备");history.Append(new("12:00:00",$"run {i}"));
            history.Task("copies","复制体","运行中");history.Append(new("12:00:01","胜利"));
            history.Task("copies","复制体","完成");
        }
        if(history.Groups.Select(g=>g.Run).Distinct().Count()!=1 || history.Lines.Count()!=2 || history.Groups.Any(g=>g.Run!=12))
            throw new Exception("开始新运行时没有清空之前的信息");
        string testRoot=Path.Combine(App.DiagnosticsRoot,"history-check",Guid.NewGuid().ToString("N"));
        var when=new DateTimeOffset(2026,10,26,4,4,54,TimeSpan.FromHours(8));
        for(int i=0;i<12;i++)
        {
            var record=RunHistory.Start(testRoot,"run",when);
            record.Log("04:04:54",$"run {i}","MessageLogBrush");
            File.WriteAllText(Path.Combine(record.Folder,"frontend-worker.log"),"stderr");
            record.Finish("blocked","offline fixture");
        }
        var folders=Directory.GetDirectories(testRoot).Order().ToArray();
        if(folders.Length!=5 || !folders[0].EndsWith("2026_10_26_04_04_54_007") ||
            !folders[^1].EndsWith("2026_10_26_04_04_54_011") || folders.Any(p=>
                !File.Exists(Path.Combine(p,"frontend-log.jsonl")) ||
                !File.Exists(Path.Combine(p,"frontend-worker.log")) ||
                JsonNode.Parse(File.ReadAllText(Path.Combine(p,"report.json")))!["status"]!.ToString()!="blocked"))
            throw new Exception("运行目录命名、5次保留或启动失败日志归档错误");
        LogGroups.Clear();runLogs.Begin("连接与准备");Append("连接成功 · 超二屏幕 3","SuccessLogBrush");
        void TaskEvent(string key,string state)
        {
            using var data=JsonDocument.Parse(JsonSerializer.Serialize(new[]{key,state}));
            HandleEvent("task",data.RootElement);
        }
        TaskEvent("copies","运行中");Append("已选择队伍2");Append("挑战胜利：自己的复制体（队伍2）");
        TaskEvent("copies","完成");var copies=runLogs.Current!;
        TaskEvent("hunt","运行中");Append("正在挑战第2只猎物，等待结算…");
        var hunt=runLogs.Current!;
        if(copies.IsExpanded || !hunt.IsExpanded || copies.Lines.Count!=2)throw new Exception("切换任务没有自动收起上一项");
        TaskEvent("hunt","运行中");
        if(!ReferenceEquals(hunt,runLogs.Current))throw new Exception("重复任务状态创建了多组日志");
        Pages.SelectedIndex=0;
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);UpdateLayout();
        var control=VisualDescendants(LogList).OfType<System.Windows.Controls.Expander>().Single(e=>ReferenceEquals(e.DataContext,copies));
        control.SetCurrentValue(System.Windows.Controls.Expander.IsExpandedProperty,true);
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
        if(!copies.IsExpanded || !control.IsExpanded)throw new Exception("运行中不能重新展开旧任务");
        Append("本场结算完成");
        if(!copies.IsExpanded)throw new Exception("新消息收起了用户展开的旧任务");
        TaskEvent("hunt","完成");TaskEvent("tower","运行中");Append("羽毛已用完，浮空巨塔完成");
        if(hunt.IsExpanded || !copies.IsExpanded)throw new Exception("切换时未只收起上一任务");
        TaskEvent("tower","完成");
        TaskEvent("copies","运行中");Append("补充免费体力后继续：复制体");
        if(!ReferenceEquals(runLogs.Current,copies)||LogGroups.Count(g=>g.TaskKey=="copies")!=1||copies.Lines.Count!=3)
            throw new Exception("补充体力后没有复用原任务日志");
        TaskEvent("copies","完成");
        using(var result=JsonDocument.Parse("{\"status\":\"completed\"}"))HandleEvent("result",result.RootElement);
        control.SetCurrentValue(System.Windows.Controls.Expander.IsExpandedProperty,false);
        control.SetCurrentValue(System.Windows.Controls.Expander.IsExpandedProperty,true);
        if(!copies.IsExpanded || copies.Lines.Count!=4)throw new Exception("结束后不能展开完整详情");
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
        LogScroll.ScrollToTop();Capture("wpf-task-log-groups.png");
        await CheckCompactLogDetails();
    }
    private static JsonNode manifestFor(string task,string field)=>JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"tasks.json")))!.AsArray().First(t=>t!["key"]!.ToString()==task)!["settings"]!["fields"]!.AsArray().First(f=>f!["key"]!.ToString()==field)!;
    private void CheckInlineOptions()
    {
        UpdateLayout();
        var elements=VisualDescendants(TaskOptions).OfType<FrameworkElement>().Where(e=>e.IsVisible).ToArray();
        var visibleOptions=SelectedTask!.Key=="forest"
            ? SelectedTask.ForestModeIndex==0?SelectedTask.ForestBasicOptions:SelectedTask.ForestAdvancedOptions
            : SelectedTask.Options;
        foreach(var option in visibleOptions.Where(o=>o.Type=="number"))
        {
            var number=elements.OfType<HandyControl.Controls.NumericUpDown>().Single(e=>ReferenceEquals(e.DataContext,option));
            var label=elements.OfType<System.Windows.Controls.TextBlock>().Single(e=>ReferenceEquals(e.DataContext,option)&&e.Text==option.Label);
            var labelPosition=label.TranslatePoint(new Point(),TaskOptions);
            var numberPosition=number.TranslatePoint(new Point(),TaskOptions);
            if(labelPosition.X+label.ActualWidth>numberPosition.X+.5 || Math.Abs(labelPosition.Y+label.ActualHeight/2-numberPosition.Y-number.ActualHeight/2)>2 || label.TextWrapping!=TextWrapping.NoWrap)
                throw new Exception("数值设置的名称和输入框没有在同一行："+option.Label);
        }
        if(elements.OfType<System.Windows.Controls.TextBlock>().Any(e=>e.DataContext is TaskOption o && o.Description.Length>0 && e.Text==o.Description))
            throw new Exception("解释性段落仍然占用设置区");
    }
    private static IEnumerable<DependencyObject> VisualDescendants(DependencyObject parent)
    {
        for(int i=0;i<VisualTreeHelper.GetChildrenCount(parent);i++)
        {
            var child=VisualTreeHelper.GetChild(parent,i);yield return child;
            foreach(var descendant in VisualDescendants(child))yield return descendant;
        }
    }
    private void Capture(string name)
    {
        UpdateLayout();
        var bitmap = new RenderTargetBitmap((int)ActualWidth, (int)ActualHeight, 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(this);
        var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
        Directory.CreateDirectory(App.DiagnosticsRoot);
        using var file = File.Create(Path.Combine(App.DiagnosticsRoot,name)); encoder.Save(file);
    }
}
