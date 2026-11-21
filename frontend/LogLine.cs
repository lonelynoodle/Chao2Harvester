using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Text.RegularExpressions;

namespace Chao2Harvester;

public sealed class LogLine(string time,string text,string color="MessageLogBrush") : INotifyPropertyChanged
{
    public string Time { get; }=time;
    public string Text { get; }=text;
    public string Color { get; }=color;
    public string LastTime { get; private set; }=time;
    public int RepeatCount { get; private set; }=1;
    public string DisplayText=>Text+(RepeatCount>1?$" （×{RepeatCount}）":"");
    public string TimeRange=>RepeatCount>1?$"首次 {Time}，最近 {LastTime}，共 {RepeatCount} 次":Time;
    public bool IsDecision=>Regex.IsMatch(Text,@"已选择|已选定|最终选择|选择结果|已确认压制|已压制|^斗技场：选择第|^复制体目标：");
    public Brush Foreground=>(Brush)Application.Current.FindResource(Color);
    public FontWeight Weight=>IsDecision||Color=="ErrorLogBrush"?FontWeights.SemiBold:FontWeights.Normal;
    public Brush Background=>IsDecision?new SolidColorBrush(System.Windows.Media.Color.FromArgb(22,0,155,135)):Brushes.Transparent;
    public event PropertyChangedEventHandler? PropertyChanged;
    public static void AppendTo(ObservableCollection<LogLine> lines,LogLine line)
    {
        // Merge only adjacent identical messages in this task. Changes of
        // task, message, outcome or severity retain their chronological rows.
        if(lines.LastOrDefault() is { } last && last.Text==line.Text && last.Color==line.Color)
        {
            last.RepeatCount++;last.LastTime=line.LastTime;
            foreach(var name in new[]{nameof(RepeatCount),nameof(DisplayText),nameof(LastTime),nameof(TimeRange)})
                last.PropertyChanged?.Invoke(last,new(name));
        }
        else lines.Add(line);
    }
}

public sealed class LogMessageView : TextBlock
{
    public static readonly DependencyProperty LineProperty=DependencyProperty.Register(nameof(Line),typeof(LogLine),typeof(LogMessageView),new PropertyMetadata(null,OnLineChanged));
    public LogLine? Line { get=>(LogLine?)GetValue(LineProperty);set=>SetValue(LineProperty,value); }
    // Give related choices distinct colors while preserving their actual text.
    private static readonly (string Pattern,string Color)[] Categories=[
        (@"怪兽助战|助战|援军|加入.*?怪兽|召唤此怪兽出战","#8B5AB5"),
        (@"吸血|生命偷取|造成伤害.*?回复自身血量","#B13B78"),(@"攻击力|攻击.*?提升|伤害提升","#C45820"),
        (@"等级提升|怪兽等级","#9B7010"),(@"伤害降低|减伤|受到.*?降低","#2B72B7"),
        (@"生命.*?提升|生命上限|恢复|回复|治疗","#16826A"),
        (@"复活","#8152B5"),(@"霸气|体型|膨胀","#895D38"),(@"移速|移动速度","#007D9C")];
    private static readonly Regex Keywords=new(string.Join("|",Categories.Select(c=>"(?:"+c.Pattern+")")));
    private static void OnLineChanged(DependencyObject d,DependencyPropertyChangedEventArgs e)
    {
        var view=(LogMessageView)d;
        if(e.OldValue is LogLine old)old.PropertyChanged-=view.LineChanged;
        if(e.NewValue is LogLine line)line.PropertyChanged+=view.LineChanged;
        view.Render();
    }
    private void LineChanged(object? sender,PropertyChangedEventArgs e)
    { if(e.PropertyName==nameof(LogLine.DisplayText))Render(); }
    private void Render()
    {
        Inlines.Clear();if(Line is not { } line)return;
        Foreground=line.Foreground;FontWeight=line.Weight;
        string text=line.DisplayText;
        if(!text.StartsWith("暴走增益候选")&&!text.StartsWith("暴走旷野已选择增益"))
        { Inlines.Add(new Run(text));return; }
        int cursor=0;
        foreach(Match match in Keywords.Matches(text))
        {
            Inlines.Add(new Run(text[cursor..match.Index]));
            string color=Categories.First(c=>Regex.IsMatch(match.Value,"^(?:"+c.Pattern+")$")).Color;
            Inlines.Add(new Run(match.Value){Foreground=(Brush)new BrushConverter().ConvertFromString(color)!,FontWeight=FontWeights.SemiBold});
            cursor=match.Index+match.Length;
        }
        Inlines.Add(new Run(text[cursor..]));
    }
}
