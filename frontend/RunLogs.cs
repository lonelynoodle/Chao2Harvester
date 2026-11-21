using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows;
using System.Windows.Media;

namespace Chao2Harvester;

public class LogGroup(int run, string? taskKey, string title, string state) : INotifyPropertyChanged
{
    public int Run { get; } = run;
    public string? TaskKey { get; } = taskKey;
    public string Title { get; } = title;
    public string Time { get; } = DateTime.Now.ToString("HH:mm:ss");
    public ObservableCollection<LogLine> Lines { get; } = [];
    private bool expanded = true;
    private string state = state;
    public bool IsExpanded { get => expanded; set { expanded=value;Changed(); } }
    public string State { get => state; set { state=value;Changed();Changed(nameof(Foreground)); } }
    public Brush Foreground => (Brush)Application.Current.FindResource(State switch {
        "运行中"=>"PrimaryBrush", "完成"=>"SuccessLogBrush",
        "待校准" or "已安全停止" or "异常结束" or "连接失败"=>"ErrorLogBrush",
        "已停止" or "部分完成"=>"WarningLogBrush", _=>"SecondaryTextBrush" });
    public event PropertyChangedEventHandler? PropertyChanged;
    private void Changed([CallerMemberName] string? name=null) => PropertyChanged?.Invoke(this,new(name));
}

public class RunLogs
{
    public ObservableCollection<LogGroup> Groups { get; } = [];
    public LogGroup? Current { get; private set; }
    public IEnumerable<LogLine> Lines => Groups.SelectMany(g=>g.Lines);
    private int run;

    public void Begin(string title)
    {
        run++;
        Groups.Clear();Current=null;
        Open(null,title,"运行中");
    }
    private LogGroup Open(string? key,string title,string state)
    {
        if(Current is not null)Current.IsExpanded=false;
        Current=new(run,key,title,state);Groups.Add(Current);
        return Current;
    }
    public void Append(LogLine line)
    {
        if(Current is null)Open(null,"运行准备","");
        LogLine.AppendTo(Current!.Lines,line);
    }
    public LogGroup Task(string key,string title,string state)
    {
        if(state=="运行中")
        {
            if(Current is { State:"运行中" } && Current.TaskKey==key)return Current;
            if(Current is { TaskKey:null,State:"运行中" })Current.State="完成";
            var existing=Groups.LastOrDefault(g=>g.Run==run && g.TaskKey==key);
            if(existing is not null)
            {
                if(Current is not null)Current.IsExpanded=false;
                Current=existing;Current.State=state;Current.IsExpanded=true;
                return Current;
            }
            return Open(key,title,state);
        }
        var group=Groups.LastOrDefault(g=>g.Run==run && g.TaskKey==key);
        if(group is null)
        {
            group=new(run,key,title,state) { IsExpanded=false };
            Groups.Add(group);
        }
        group.State=state;
        return group;
    }
    public void Finish(string state)
    {
        if(Current?.State=="运行中")Current.State=state;
    }
    public void Summary(string title)=>Open(null,title,"");
}
