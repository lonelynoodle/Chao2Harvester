using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.ComponentModel;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace Chao2Harvester;

public sealed class TaskTemplate(string id, string name, JsonObject snapshot) : NotifyModel
{
    public string Id { get; } = id;
    private string name = name;
    public string Name { get=>name; set { if(name==value)return;name=value;Change(); } }
    public JsonObject Snapshot { get; set; } = snapshot;
    public JsonObject ToJson()=>new() { ["id"]=Id,["name"]=Name,["settings"]=Snapshot.DeepClone() };
}

public partial class MainWindow
{
    private readonly Dictionary<string,TaskItem> taskCatalog=[];
    private JsonArray taskManifest=[];
    private bool queueReady;
    private bool loadingTemplate;
    private int nextTemplateNumber=1;
    private readonly DispatcherTimer queueSaveTimer=new() { Interval=TimeSpan.FromMilliseconds(350) };
    private TaskTemplate? selectedTemplate;
    public ObservableCollection<TaskTemplate> TaskTemplates { get; }=[];
    public bool CanDeleteTemplate=>Idle && TaskTemplates.Count>1;
    public bool CanAddTask=>Idle && (AllowRepeatTasks || Tasks.Select(t=>t.Key).Distinct().Count()<taskCatalog.Count);
    private bool allowRepeatTasks;
    public bool AllowRepeatTasks
    {
        get=>allowRepeatTasks;
        set
        {
            if(allowRepeatTasks==value)return;
            allowRepeatTasks=value;
            if(!value)
            {
                var seen=new HashSet<string>();
                foreach(var task in Tasks.ToArray())if(!seen.Add(task.Key))RemoveQueueTask(task);
            }
            Changed();Changed(nameof(CanAddTask));ScheduleQueueSave();
        }
    }
    private string queueSaveError="";
    public string QueueSaveError { get=>queueSaveError; private set { queueSaveError=value;Changed();Changed(nameof(QueueSaveErrorVisibility)); } }
    public Visibility QueueSaveErrorVisibility=>string.IsNullOrEmpty(QueueSaveError)?Visibility.Collapsed:Visibility.Visible;
    public TaskTemplate? SelectedTemplate
    {
        get=>selectedTemplate;
        set
        {
            if(value is null || ReferenceEquals(value,selectedTemplate))return;
            if(!Idle) { Changed();return; }
            try
            {
                if(selectedTemplate is not null)Save();
                ApplyTemplate(value);
                Save();QueueSaveError="";
            }
            catch(Exception e) { QueueSaveError="模板未切换："+e.Message;Changed(); }
        }
    }

    private static JsonArray Keys(IEnumerable<string> keys)=>new(keys.Select(k=>(JsonNode?)JsonValue.Create(k)).ToArray());
    private JsonObject CatalogOptions()=>new(taskCatalog.Values.Select(t=>new KeyValuePair<string,JsonNode?>(t.Key,(Tasks.FirstOrDefault(row=>row.Key==t.Key) ?? t).SaveOptions())));
    private JsonArray InstanceQueue()=>new(Tasks.Select(t=>(JsonNode?)new JsonObject
    {
        ["id"]=t.InstanceId,["key"]=t.Key,["name"]=t.Name,["enabled"]=t.Enabled,["options"]=t.SaveOptions()
    }).ToArray());
    private JsonObject QueueSnapshot()=>new()
    {
        ["task_order"]=Keys(Tasks.Select(t=>t.Key).Distinct()),
        ["tasks"]=Keys(Tasks.Where(t=>t.Enabled).Select(t=>t.Key).Distinct()),
        ["task_options"]=CatalogOptions(),["task_queue"]=InstanceQueue(),["allow_repeat_tasks"]=AllowRepeatTasks,
        ["stamina_order"]=Keys(StaminaPriority.Select(t=>t.Key)),
        ["close_mumu"]=false,["unordered_tasks"]=UnorderedTasks,
        ["task_settings_selection"]=SelectedTask?.InstanceId ?? ""
    };

    private void InitializeTaskQueue()
    {
        // Preserve the existing visible list and old stamina priority on migration.
        if(settings["task_order"] is JsonArray savedOrder)
        {
            var order=savedOrder.Select(k=>k!.GetValue<string>()).Distinct().Where(taskCatalog.ContainsKey).ToArray();
            Tasks.Clear();foreach(var key in order)Tasks.Add(taskCatalog[key]);
        }
        else
        {
            var slots=Tasks.Select((t,i)=>(t,i)).Where(v=>StaminaPriority.Contains(v.t)).Select(v=>v.i).ToArray();
            for(int i=0;i<slots.Length;i++)Tasks[slots[i]]=StaminaPriority[i];
        }
        if(settings["task_templates"] is JsonArray templates)
            foreach(var raw in templates.OfType<JsonObject>())
                if(raw["id"] is not null && raw["settings"] is JsonObject snapshot && !TaskTemplates.Any(t=>t.Id==raw["id"]!.ToString()))
                    RegisterTemplate(new(raw["id"]!.ToString(),raw["name"]?.ToString() ?? "模板",(JsonObject)snapshot.DeepClone()));
        nextTemplateNumber=settings["next_task_template_number"]?.GetValue<int>() ?? TaskTemplates.Count+1;
        if(TaskTemplates.Count==0)
        {
            var initial=QueueSnapshot();
            if(settings["task_queue"] is JsonArray queue)initial["task_queue"]=queue.DeepClone();
            initial["allow_repeat_tasks"]=settings["allow_repeat_tasks"]?.DeepClone() ?? JsonValue.Create(false);
            initial["close_mumu"]=settings["close_mumu"]?.DeepClone() ?? JsonValue.Create(false);
            RegisterTemplate(new(Guid.NewGuid().ToString("N"),NextTemplateName(),initial));
        }
        var active=TaskTemplates.FirstOrDefault(t=>t.Id==settings["active_task_template"]?.ToString()) ?? TaskTemplates[0];
        ApplyTemplate(active);
        Tasks.CollectionChanged+=(_,_)=>
        {
            Changed(nameof(CanAddTask));
            ScheduleQueueSave();
        };
        StaminaPriority.CollectionChanged+=(_,_)=>ScheduleQueueSave();
        queueSaveTimer.Tick+=(_,_)=>FlushQueueSave();
        queueReady=true;
    }

    private string NextTemplateName()
    {
        string name;
        do { name="模板"+nextTemplateNumber++; } while(TaskTemplates.Any(t=>t.Name==name));
        return name;
    }
    private void RegisterTemplate(TaskTemplate template)
    {
        TaskTemplates.Add(template);
        template.PropertyChanged+=(_,_)=>ScheduleQueueSave();
        Changed(nameof(CanDeleteTemplate));
    }
    private void ApplyTemplate(TaskTemplate template)
    {
        var snapshot=template.Snapshot;
        MigrateResourceLimits(snapshot);
        var order=(snapshot["task_order"]?.AsArray() ?? Keys(taskCatalog.Keys)).Select(k=>k!.GetValue<string>()).ToArray();
        if(order.Distinct().Count()!=order.Length || order.Any(k=>!taskCatalog.ContainsKey(k)))throw new InvalidOperationException("模板包含未知或重复任务");
        var enabled=(snapshot["tasks"]?.AsArray() ?? new JsonArray()).Select(k=>k!.GetValue<string>()).ToHashSet();
        bool repeats=snapshot["allow_repeat_tasks"]?.GetValue<bool>() ?? false;
        var queue=snapshot["task_queue"]?.DeepClone().AsArray() ?? new JsonArray(order.Select(key=>(JsonNode?)new JsonObject
        {
            ["id"]=key,["key"]=key,["name"]=taskManifest.First(t=>t!["key"]!.ToString()==key)!["name"]!.ToString(),
            ["enabled"]=enabled.Contains(key),["options"]=snapshot["task_options"]?[key]?.DeepClone()
        }).ToArray());
        // Migrate the removed post-action control into an ordinary visible task.
        // An already enabled finish task had precedence and keeps its own options.
        if(snapshot["close_mumu"]?.GetValue<bool>()==true && !queue.Any(t=>t!["key"]!.ToString()=="finish" && t["enabled"]?.GetValue<bool>()==true))
        {
            var finish=queue.OfType<JsonObject>().FirstOrDefault(t=>t["key"]!.ToString()=="finish");
            if(finish is null)
            {
                finish=new JsonObject { ["id"]="finish_"+Guid.NewGuid().ToString("N"),["key"]="finish",["name"]="结束关闭",
                    ["options"]=snapshot["task_options"]?["finish"]?.DeepClone() ?? new JsonObject() };
                queue.Add(finish);
            }
            finish["enabled"]=true;
            if(finish["options"] is not JsonObject)finish["options"]=new JsonObject();
            finish["options"]!["close_mumu"]=true;enabled.Add("finish");
        }
        var ids=new HashSet<string>();var kinds=new HashSet<string>();var entries=new List<(TaskItem item,List<TaskOption> options,bool enabled,string name)>();
        foreach(var raw in queue)
        {
            string key=raw!["key"]!.GetValue<string>();string id=raw["id"]!.GetValue<string>();
            if(!taskCatalog.ContainsKey(key) || !ids.Add(id))throw new InvalidOperationException("模板包含未知任务或重复实例编号");
            if(!kinds.Add(key) && !repeats)continue;
            var item=id==key?taskCatalog[key]:new TaskItem(key,raw["name"]!.ToString(),taskCatalog[key].Description,true) { InstanceId=id,Hint=taskCatalog[key].Hint };
            var spec=taskManifest.First(t=>t!["key"]!.ToString()==key)!;
            var options=spec["settings"]!["fields"]!.AsArray().Select(f=>new TaskOption(f!,raw["options"]?[f!["key"]!.ToString()])).ToList();
            foreach(var option in options) { option.BindDependency(options);_ = option.ToJson(); }
            entries.Add((item,options,raw["enabled"]?.GetValue<bool>() ?? true,raw["name"]?.ToString() ?? item.Name));
        }
        // Keep settings of removed tasks available for a later Add operation.
        var prepared=new Dictionary<string,List<TaskOption>>();
        foreach(var spec in taskManifest)
        {
            string key=spec!["key"]!.GetValue<string>();
            prepared[key]=spec["settings"]!["fields"]!.AsArray().Select(f=>new TaskOption(f!,snapshot["task_options"]?[key]?[f!["key"]!.ToString()])).ToList();
            foreach(var option in prepared[key]) { option.BindDependency(prepared[key]);_ = option.ToJson(); }
        }
        loadingTemplate=true;
        try
        {
            SelectedTask=null;
            foreach(var (key,item) in taskCatalog)
            {
                item.Enabled=enabled.Contains(key);item.Options.Clear();
                foreach(var option in prepared[key]) { item.Options.Add(option);WatchOption(option); }
            }
            Tasks.Clear();
            foreach(var (item,options,on,name) in entries)
            {
                item.Name=name;item.Enabled=on;item.Options.Clear();
                foreach(var option in options) { item.Options.Add(option);WatchOption(option); }
                WatchTask(item);Tasks.Add(item);
            }
            allowRepeatTasks=repeats;Changed(nameof(AllowRepeatTasks));
            StaminaPriority.Clear();
            var stamina=(snapshot["stamina_order"]?.AsArray() ?? Keys(["copies","hunt","main"]))
                .Select(k=>k!.ToString()).Where(k=>k is "copies" or "hunt" or "main").Distinct().ToList();
            foreach(var key in new[]{"copies","hunt","main"})if(!stamina.Contains(key))stamina.Add(key);
            foreach(var key in stamina)StaminaPriority.Add(taskCatalog[key]);
            UnorderedTasks=snapshot["unordered_tasks"]?.GetValue<bool>() ?? UnorderedTasks;
            selectedTemplate=template;Changed(nameof(SelectedTemplate));
            Changed(nameof(UnorderedTasks));
            string? selection=snapshot["task_settings_selection"]?.ToString();
            SelectedTask=Tasks.FirstOrDefault(t=>t.InstanceId==selection) ?? Tasks.FirstOrDefault();
            Changed(nameof(CanDeleteTemplate));Changed(nameof(CanAddTask));
        }
        finally { loadingTemplate=false; }
    }
    private void WatchOption(TaskOption option)
    {
        option.PropertyChanged+=(_,e)=> { if(e.PropertyName is nameof(TaskOption.Checked) or nameof(TaskOption.Number) or nameof(TaskOption.ChoiceId))ScheduleQueueSave(); };
        WatchRows(option.Rows);WatchRows(option.Teams);WatchRows(option.Stages);
    }
    private readonly System.Runtime.CompilerServices.ConditionalWeakTable<TaskItem,object> watchedTasks=new();
    private void WatchTask(TaskItem item)
    {
        if(watchedTasks.TryGetValue(item,out _))return;
        watchedTasks.Add(item,new object());
        item.PropertyChanged+=(_,e)=> { if(e.PropertyName is nameof(TaskItem.Enabled) or nameof(TaskItem.Name))ScheduleQueueSave(); };
    }
    private void WatchRows<T>(ObservableCollection<T> rows) where T:INotifyPropertyChanged
    {
        void Watch(T row)=>row.PropertyChanged+=(_,e)=>
        {
            if(e.PropertyName is "Enabled" or "Limit" or "TeamId" or "Id")ScheduleQueueSave();
        };
        foreach(var row in rows)Watch(row);
        rows.CollectionChanged+=(_,e)=>
        {
            if(e.Action!=NotifyCollectionChangedAction.Move && e.NewItems is not null)
                foreach(T row in e.NewItems)Watch(row);
            ScheduleQueueSave();
        };
    }
    private void ScheduleQueueSave()
    {
        if(!queueReady || loadingTemplate || !Idle)return;
        queueSaveTimer.Stop();queueSaveTimer.Start();
    }
    private void FlushQueueSave()
    {
        queueSaveTimer.Stop();
        if(!queueReady || loadingTemplate || !Idle)return;
        try { Save();QueueSaveError=""; }
        catch(Exception e) { QueueSaveError="设置尚未保存："+e.Message; }
    }
    private void SaveTaskTemplates()
    {
        if(selectedTemplate is null)return;
        selectedTemplate.Snapshot=QueueSnapshot();
        foreach(var template in TaskTemplates)
            if(string.IsNullOrWhiteSpace(template.Name))template.Name=NextTemplateName();
        settings["task_templates"]=new JsonArray(TaskTemplates.Select(t=>(JsonNode?)t.ToJson()).ToArray());
        settings["active_task_template"]=selectedTemplate.Id;
        settings["next_task_template_number"]=nextTemplateNumber;
    }
    private bool AddQueueTask(string key)
    {
        if(!Idle || !taskCatalog.TryGetValue(key,out var source) || (!AllowRepeatTasks && Tasks.Any(t=>t.Key==key)))return false;
        var item=NewQueueItem(source,source.SaveOptions(),source.Name,Tasks.Any(t=>t.InstanceId==key)?key+"_"+Guid.NewGuid().ToString("N"):key);
        int finish=Tasks.ToList().FindIndex(t=>t.Key=="finish");
        Tasks.Insert(key=="startup"?0:finish<0?Tasks.Count:finish,item);SelectedTask=item;
        return true;
    }
    private void AddQueueTaskClick(object sender,RoutedEventArgs e)
    {
        if(!Idle)return;
        var menu=new ContextMenu();
        foreach(var task in taskCatalog.Values.Where(t=>AllowRepeatTasks || !Tasks.Any(row=>row.Key==t.Key)))
        {
            var item=new MenuItem { Header=task.Name };
            item.Click+=(_,_)=>AddQueueTask(task.Key);menu.Items.Add(item);
        }
        menu.PlacementTarget=(FrameworkElement)sender;menu.IsOpen=menu.HasItems;
    }
    private TaskItem NewQueueItem(TaskItem source,JsonObject options,string name,string id)
    {
        var item=new TaskItem(source.Key,name,source.Description,true) { InstanceId=id,Hint=source.Hint };
        var spec=taskManifest.First(t=>t!["key"]!.ToString()==source.Key)!;
        foreach(var field in spec["settings"]!["fields"]!.AsArray())
            item.Options.Add(new(field!,options[field!["key"]!.ToString()]));
        foreach(var option in item.Options) { option.BindDependency(item.Options);WatchOption(option); }
        WatchTask(item);return item;
    }
    private TaskItem? CopyQueueTask(TaskItem source)
    {
        if(!Idle || !AllowRepeatTasks || !Tasks.Contains(source))return null;
        var copy=NewQueueItem(source,source.SaveOptions(),source.Name,source.Key+"_"+Guid.NewGuid().ToString("N"));
        Tasks.Insert(Tasks.IndexOf(source)+1,copy);SelectedTask=copy;return copy;
    }
    private void CopyQueueTaskClick(object sender,RoutedEventArgs e)
    {
        if(sender is FrameworkElement { DataContext:TaskItem item })CopyQueueTask(item);
    }
    private void RenameQueueTaskClick(object sender,RoutedEventArgs e)
    {
        if(!Idle || sender is not FrameworkElement { DataContext:TaskItem item })return;
        var input=new TextBox { Text=item.Name,MaxLength=80,Margin=new Thickness(0,0,0,16) };
        var ok=new Button { Content="确定",IsDefault=true,Width=76,Margin=new Thickness(0,0,8,0) };
        var cancel=new Button { Content="取消",IsCancel=true,Width=76 };
        var buttons=new StackPanel { Orientation=Orientation.Horizontal,HorizontalAlignment=HorizontalAlignment.Right };
        buttons.Children.Add(ok);buttons.Children.Add(cancel);
        var panel=new StackPanel { Margin=new Thickness(20) };panel.Children.Add(input);panel.Children.Add(buttons);
        var dialog=new HandyControl.Controls.Window { Owner=this,Title="重命名任务",Width=320,SizeToContent=SizeToContent.Height,
            ResizeMode=ResizeMode.NoResize,WindowStartupLocation=WindowStartupLocation.CenterOwner,Content=panel,ShowInTaskbar=false };
        ok.Click+=(_,_)=> { if(!string.IsNullOrWhiteSpace(input.Text))dialog.DialogResult=true; };
        dialog.Loaded+=(_,_)=> { input.Focus();input.SelectAll(); };
        if(dialog.ShowDialog()==true)item.Name=input.Text.Trim();
    }
    private void RemoveQueueTaskClick(object sender,RoutedEventArgs e)
    {
        if(Idle && sender is FrameworkElement { DataContext:TaskItem item })RemoveQueueTask(item);
    }
    private void RemoveQueueTask(TaskItem item)
    {
        if(!Idle)return;
        if(Tasks.Count(t=>t.Key==item.Key)==1 && !ReferenceEquals(item,taskCatalog[item.Key]))
        {
            var saved=item.SaveOptions();var catalog=taskCatalog[item.Key];catalog.Options.Clear();
            var spec=taskManifest.First(t=>t!["key"]!.ToString()==item.Key)!;
            foreach(var field in spec["settings"]!["fields"]!.AsArray())catalog.Options.Add(new(field!,saved[field!["key"]!.ToString()]));
            foreach(var option in catalog.Options)option.BindDependency(catalog.Options);
        }
        Tasks.Remove(item);
        if(ReferenceEquals(SelectedTask,item))SelectedTask=Tasks.FirstOrDefault();
    }
    private TaskTemplate AddTaskTemplate()
    {
        Save();
        var template=new TaskTemplate(Guid.NewGuid().ToString("N"),NextTemplateName(),QueueSnapshot());
        RegisterTemplate(template);SelectedTemplate=template;return template;
    }
    private void AddTemplateClick(object sender,RoutedEventArgs e)
    {
        if(!Idle)return;
        try { AddTaskTemplate();QueueSaveError=""; }
        catch(Exception error) { QueueSaveError="模板未添加："+error.Message; }
    }
    private bool DeleteTaskTemplate(TaskTemplate template,bool confirmed)
    {
        if(!confirmed || !Idle || TaskTemplates.Count<=1 || !TaskTemplates.Contains(template))return false;
        if(ReferenceEquals(selectedTemplate,template))SelectedTemplate=TaskTemplates.First(t=>t!=template);
        if(ReferenceEquals(selectedTemplate,template))return false;
        TaskTemplates.Remove(template);Changed(nameof(CanDeleteTemplate));Save();return true;
    }
    private void DeleteTemplateClick(object sender,RoutedEventArgs e)
    {
        if(!CanDeleteTemplate || SelectedTemplate is null)return;
        var template=SelectedTemplate;
        DeleteTaskTemplate(template,MessageBox.Show(this,$"删除“{template.Name}”？其任务顺序和设置将一并删除。","删除模板",MessageBoxButton.YesNo,MessageBoxImage.Question,MessageBoxResult.No)==MessageBoxResult.Yes);
    }

    private async Task SmokeContinueFromTask()
    {
        if(!App.Smoke)throw new InvalidOperationException("续跑检查只能离线运行");
        var template=SelectedTemplate!;var snapshot=QueueSnapshot();
        try
        {
            AllowRepeatTasks=true;
            var earlier=Tasks.First(t=>t.Key=="hunt");earlier.Enabled=true;
            var start=CopyQueueTask(earlier) ?? throw new Exception("无法创建续跑测试任务");
            start.Name="从这里继续";start.Enabled=true;
            var later=CopyQueueTask(start) ?? throw new Exception("无法创建后续同名任务");
            later.Options.First(o=>o.Key=="team").ChoiceId="3";
            var disabled=Tasks.First(t=>t.Key=="arena");disabled.Enabled=false;
            Tasks.Move(Tasks.IndexOf(disabled),Tasks.IndexOf(start)+1);
            UnorderedTasks=true;SelectedTask=start;Save();
            var expected=Tasks.Skip(Tasks.IndexOf(start)).Where(t=>t.Enabled).Select(t=>t.InstanceId).ToArray();
            settings["_smoke_expected_suffix"]=Keys(expected);
            TaskList.ScrollIntoView(start);UpdateLayout();
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var buttons=VisualDescendants(TaskList).OfType<Button>().Where(b=>b.Name=="StartFromTaskButton").ToArray();
            var startButton=buttons.Single(b=>ReferenceEquals(b.DataContext,start));
            if(!startButton.IsEnabled || buttons.Single(b=>ReferenceEquals(b.DataContext,disabled)).IsEnabled)
                throw new Exception("续跑按钮未遵守任务勾选状态");
            startButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            if(Idle || startButton.IsEnabled || earlier.State!="本轮跳过" || disabled.State!="未启用")
                throw new Exception("续跑启动状态或前序任务标记错误");
            var deadline=DateTime.UtcNow.AddSeconds(15);
            while(!Idle && DateTime.UtcNow<deadline)await Task.Delay(100);
            if(!Idle || Status!="本轮完成" || !Logs.Any(l=>l.Text=="离线续跑队列已核对："+string.Join(",",expected)))
                throw new Exception("从任务条续跑未通过桥接验证："+Status);
            if(!UnorderedTasks || !settings["unordered_tasks"]!.GetValue<bool>() ||
                settings["task_queue"]!.AsArray().Count!=Tasks.Count || !Tasks.Contains(earlier) || disabled.Enabled)
                throw new Exception("续跑改写了原有顺序、勾选或模板");
            Capture("wpf-continue-from-task.png");
            start.Enabled=false;Save();
            settings["_smoke_expected_single_task"]=start.InstanceId;
            TaskList.ScrollIntoView(start);UpdateLayout();
            await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
            var onlyButton=VisualDescendants(TaskList).OfType<Button>().Single(b=>b.Name=="RunOnlyTaskButton"&&ReferenceEquals(b.DataContext,start));
            if(!onlyButton.IsEnabled)throw new Exception("未勾选任务不能单独运行");
            onlyButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            if(Idle || onlyButton.IsEnabled || later.State!="本轮跳过" || start.State!="待执行")
                throw new Exception("单条运行启动状态错误");
            deadline=DateTime.UtcNow.AddSeconds(15);
            while(!Idle && DateTime.UtcNow<deadline)await Task.Delay(100);
            if(!Idle || Status!="本轮完成" || !Logs.Any(l=>l.Text=="离线单条队列已核对："+start.InstanceId) || start.Enabled)
                throw new Exception("单条运行未通过桥接验证或改写了勾选");
        }
        finally
        {
            settings.Remove("_smoke_expected_suffix");
            settings.Remove("_smoke_expected_single_task");
            template.Snapshot=snapshot;ApplyTemplate(template);Save();
        }
    }

    private async Task SmokeTaskTemplates()
    {
        if(!App.Smoke)throw new InvalidOperationException("模板检查只能离线运行");
        var original=SelectedTemplate!;var snapshot=QueueSnapshot();
        if(!GongSolutions.Wpf.DragDrop.DragDrop.GetIsDragSource(TaskList) ||
           !GongSolutions.Wpf.DragDrop.DragDrop.GetIsDropTarget(TaskList))throw new Exception("任务拖动未启用");
        var hunt=taskCatalog["hunt"];
        var initialIndex=Tasks.IndexOf(hunt);
        Tasks.Move(initialIndex,1);Save();
        if(settings["task_order"]![1]!.ToString()!="hunt")throw new Exception("拖动顺序未保存");
        RemoveQueueTask(hunt);Save();
        if(settings["tasks"]!.AsArray().Any(k=>k!.ToString()=="hunt") || !AddQueueTask("hunt") || AddQueueTask("hunt"))throw new Exception("任务增删或去重错误");
        hunt=Tasks.First(t=>t.Key=="hunt");
        hunt.Options.First(o=>o.Key=="auto_settle").Checked=false;
        await Task.Delay(700);
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
        if(settings["task_options"]!["hunt"]!["auto_settle"]!.GetValue<bool>())throw new Exception("任务选项未实时保存："+QueueSaveError+"；timer="+queueSaveTimer.IsEnabled);
        var second=AddTaskTemplate();second.Name="晚间收菜";
        Tasks.First(t=>t.Key=="hunt").Options.First(o=>o.Key=="auto_settle").Checked=true;RemoveQueueTask(Tasks.First(t=>t.Key=="forest"));Save();
        SelectedTemplate=original;
        if(Tasks.First(t=>t.Key=="hunt").Options.First(o=>o.Key=="auto_settle").Checked || !Tasks.Any(t=>t.Key=="forest"))throw new Exception("模板之间设置泄漏");
        SelectedTemplate=second;
        if(!Tasks.First(t=>t.Key=="hunt").Options.First(o=>o.Key=="auto_settle").Checked || Tasks.Any(t=>t.Key=="forest"))throw new Exception("切换模板丢失任务或设置");
        if(DeleteTaskTemplate(second,false) || TaskTemplates.Count!=2)throw new Exception("取消确认却删除模板");
        if(!DeleteTaskTemplate(second,true) || TaskTemplates.Count!=1 || SelectedTemplate!=original)throw new Exception("模板删除或回退错误");
        AllowRepeatTasks=true;
        hunt=Tasks.First(t=>t.Key=="hunt");
        var copy=CopyQueueTask(hunt) ?? throw new Exception("允许重复后无法复制任务");
        copy.Name="狩猎第二轮";copy.Options.First(o=>o.Key=="auto_settle").Checked=true;
        if(hunt.Options.First(o=>o.Key=="auto_settle").Checked || copy.InstanceId==hunt.InstanceId)throw new Exception("复制任务没有独立设置或编号");
        if(!AddQueueTask("hunt") || Tasks.Count(t=>t.Key=="hunt")!=3)throw new Exception("重复添加任务失败");
        Tasks.Move(Tasks.IndexOf(copy),0);Save();
        if(settings["task_queue"]![0]!["name"]!.ToString()!="狩猎第二轮")throw new Exception("实例顺序或重命名未保存");
        var duplicateSnapshot=QueueSnapshot();original.Snapshot=duplicateSnapshot;ApplyTemplate(original);
        if(Tasks.Count(t=>t.Key=="hunt")!=3 || !AllowRepeatTasks || Tasks[0].InstanceId!=copy.InstanceId)throw new Exception("重复任务未随模板恢复");
        AllowRepeatTasks=false;Save();
        if(Tasks.Count(t=>t.Key=="hunt")!=1 || Tasks[0].InstanceId!=copy.InstanceId || AddQueueTask("hunt") || CopyQueueTask(Tasks[0]) is not null)throw new Exception("关闭重复未保留最上面的任务，或复制仍可用");
        Tasks.Clear();SelectedTask=null;Save();
        if(settings["task_order"]!.AsArray().Count!=0 || settings["tasks"]!.AsArray().Count!=0)throw new Exception("空任务列表未保存");
        var legacy=(JsonObject)snapshot.DeepClone();legacy["close_mumu"]=true;
        foreach(var row in legacy["task_queue"]!.AsArray().Where(t=>t!["key"]!.ToString()=="finish").ToArray())legacy["task_queue"]!.AsArray().Remove(row);
        original.Snapshot=legacy;ApplyTemplate(original);Save();
        var migrated=Tasks.Single(t=>t.Key=="finish");
        if(!migrated.Enabled || !migrated.Options.First(o=>o.Key=="close_mumu").Checked || settings["close_mumu"]!.GetValue<bool>())throw new Exception("旧结束关闭选项未迁移到可见任务");
        original.Snapshot=snapshot;ApplyTemplate(original);Save();
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
        Capture("wpf-task-templates.png");
    }
}
