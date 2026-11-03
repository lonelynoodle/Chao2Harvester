using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace Chao2Harvester;
public partial class TaskOptionsView : UserControl
{
    public static readonly DependencyProperty OtherContentProperty=DependencyProperty.Register(
        nameof(OtherContent),typeof(object),typeof(TaskOptionsView));
    public object? OtherContent { get=>GetValue(OtherContentProperty);set=>SetValue(OtherContentProperty,value); }
    public TaskOptionsView()
    {
        InitializeComponent();
        DataContextChanged+=(_,_)=>OptionsScroll.ScrollToTop();
    }
    private void AddTeam(object sender,RoutedEventArgs e)
    {
        if(((FrameworkElement)sender).DataContext is TaskOption option)option.AddTeam();
    }
    private void RemoveTeam(object sender,RoutedEventArgs e)
    {
        if(((FrameworkElement)sender).DataContext is TeamRow row)row.Owner.RemoveTeam(row);
    }
    private void AddStage(object sender,RoutedEventArgs e)
    {
        if(((FrameworkElement)sender).DataContext is TaskOption option)option.AddStage();
    }
    private void RemoveStage(object sender,RoutedEventArgs e)
    {
        if(((FrameworkElement)sender).DataContext is StageRow row)row.Owner.RemoveStage(row);
    }
    private void RouteScroll(object sender,MouseWheelEventArgs e)
    {
        if(e.Handled)return;
        e.Handled=true;
        OptionsScroll.ScrollToVerticalOffset(OptionsScroll.VerticalOffset-e.Delta);
    }
}
