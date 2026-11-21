using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Threading;
using System.Text.Json;

namespace Chao2Harvester;

public partial class MainWindow
{
    private void LogScrollChanged(object sender,ScrollChangedEventArgs e)=>RefreshStickyLogHeader();
    private void LogLayoutUpdated(object? sender,EventArgs e)=>RefreshStickyLogHeader();
    private void RefreshStickyLogHeader()
    {
        if(StickyLogHeader is null || LogList is null || !LogScroll.IsVisible)return;
        LogGroup? pinned=null;
        foreach(var group in LogGroups.Where(g=>g.IsExpanded))
        {
            if(LogList.ItemContainerGenerator.ContainerFromItem(group) is not FrameworkElement container)continue;
            var view=VisualDescendants(container).OfType<Expander>().FirstOrDefault();
            if(view is null || !view.IsVisible)continue;
            double top=view.TranslatePoint(new Point(),LogScroll).Y;
            // Pin only while this group's own detail intersects the top edge.
            // The next group must never inherit a previous task's header.
            if(top< -1 && top+view.ActualHeight>32){pinned=group;break;}
        }
        if(!ReferenceEquals(StickyLogHeader.DataContext,pinned))StickyLogHeader.DataContext=pinned;
        var visibility=pinned is null?Visibility.Collapsed:Visibility.Visible;
        if(StickyLogHeader.Visibility!=visibility)StickyLogHeader.Visibility=visibility;
    }
    private void CollapseStickyLog(object sender,RoutedEventArgs e)
    {
        if(StickyLogHeader.DataContext is LogGroup group)group.IsExpanded=false;
        RefreshStickyLogHeader();
    }

    private async Task CheckCompactLogDetails()
    {
        currentMode="run";
        using(var partial=JsonDocument.Parse("{\"status\":\"partial\",\"close_app_requested\":true}"))HandleEvent("result",partial.RootElement);
        if(!closeAfterResult)throw new Exception("已授权部分完成后的关闭请求未生效");
        using(var stopped=JsonDocument.Parse("{\"status\":\"stopped\",\"close_app_requested\":true}"))HandleEvent("result",stopped.RootElement);
        if(closeAfterResult)throw new Exception("用户停止后不能自动关闭");
        var history=new RunLogs();history.Begin("准备");
        foreach(var time in new[]{"01:00:00","01:00:15","01:00:30"})history.Append(new(time,"等待结算…"));
        var repeated=history.Lines.Single();
        if(repeated.RepeatCount!=3 || repeated.Time!="01:00:00" || repeated.LastTime!="01:00:30" || !repeated.DisplayText.Contains("×3"))
            throw new Exception("重复日志未即时合并或丢失时间范围");
        history.Append(new("01:00:31","选择增益"));history.Append(new("01:00:32","等待结算…"));
        if(history.Lines.Count()!=3)throw new Exception("日志合并跨过了中间的真实事件");
        history.Task("nest","谜之巢穴","运行中");history.Append(new("01:00:33","等待结算…"));
        if(history.Current!.Lines.Single().RepeatCount!=1)throw new Exception("日志合并跨过了任务边界");
        history.Append(new("01:00:34","等待结算…","ErrorLogBrush"));
        if(history.Current.Lines.Count!=2)throw new Exception("日志合并吞掉了不同级别的错误");

        SelectedTask=Tasks.Single(t=>t.Key=="nest");
        var option=SelectedTask.Options.Single(o=>o.Key=="auto_deity");
        if(!option.Checked)throw new Exception("谜之巢穴自动神灵选项默认值错误");
        option.Checked=false;option.Checked=true;
        Status="运行中 · 谜之巢穴";
        runLogs.Begin("连接与准备");runLogs.Task("nest","谜之巢穴","运行中");var nest=runLogs.Current!;
        for(int i=0;i<80;i++)Append($"挑战进度 {i+1}，本场尚未结算");
        for(int i=0;i<3;i++)Append("暴走旷野挑战中，等待成绩结算…");
        Append("暴走增益候选1：怪兽助战，加入一只怪兽");
        Append("暴走增益候选2：攻击力提升50%");
        Append("暴走增益候选3：吸血提升10%");
        Append("暴走旷野已选择增益：怪兽助战，加入一只怪兽");
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);UpdateLayout();
        LogScroll.ScrollToEnd();
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);UpdateLayout();RefreshStickyLogHeader();
        if(StickyLogHeader.Visibility!=Visibility.Visible || !ReferenceEquals(StickyLogHeader.DataContext,nest))
            throw new Exception("长日志滚动后任务标题未固定在顶部");
        var messages=VisualDescendants(LogList).OfType<LogMessageView>().Where(v=>v.Line?.Text.StartsWith("暴走增益候选")==true).ToArray();
        var colors=messages.SelectMany(v=>v.Inlines.OfType<Run>()).Where(v=>v.FontWeight==FontWeights.SemiBold).Select(v=>v.Foreground.ToString()).Distinct().Count();
        if(colors<3 || !nest.Lines.Last().IsDecision || nest.Lines.Last().Weight!=FontWeights.SemiBold)
            throw new Exception("增益分类颜色或已确认选择强调未生效");
        if(messages.Any(v=>v.ActualHeight>25))throw new Exception("单行日志间距仍过大");
        Capture("wpf-compact-sticky-logs.png");
        LogScroll.ScrollToVerticalOffset(250);
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
        double offset=LogScroll.VerticalOffset;Append("此消息不能打断用户翻阅");
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);
        if(Math.Abs(LogScroll.VerticalOffset-offset)>1)throw new Exception("新增消息抢走了用户的阅读位置");
        CollapseStickyLogButton.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);UpdateLayout();RefreshStickyLogHeader();
        if(nest.IsExpanded || StickyLogHeader.Visibility!=Visibility.Collapsed)
            throw new Exception("固定标题不能收起任务或遗留了旧标题");
    }
}
