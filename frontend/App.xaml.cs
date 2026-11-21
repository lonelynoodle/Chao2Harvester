using System.IO;
using System.Threading;
using System.Windows;

namespace Chao2Harvester;

public partial class App : Application
{
    private Mutex? singleton;
    public static string Root { get; } = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, ".."));
    public static bool Smoke => Environment.GetCommandLineArgs().Contains("--smoke");
    public static bool RunRequested=>!Smoke && Environment.GetCommandLineArgs().Contains("--run");
    public static string DiagnosticsRoot=>Path.Combine(Root,"dev","diagnostics","smoke");
    public static string? ActiveRunFolder { get; set; }
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        Directory.SetCurrentDirectory(Root);
        singleton = new Mutex(true, Smoke ? "Local\\Chao2Harvester.Wpf.Smoke" : "Local\\Chao2Harvester.Wpf", out bool created);
        if (!created) { Shutdown(); return; }
        DispatcherUnhandledException += (_, error) =>
        {
            string folder=ActiveRunFolder??Path.Combine(Root,"dev","diagnostics");
            Directory.CreateDirectory(folder);
            File.WriteAllText(Path.Combine(folder,"frontend-error.txt"), error.Exception.ToString());
            error.Handled = true;
            if (Smoke) Shutdown(1);
            else MessageBox.Show(error.Exception.Message, "超二收菜");
        };
        MainWindow = new MainWindow();
        MainWindow.Show();
    }
    protected override void OnExit(ExitEventArgs e) { singleton?.Dispose(); base.OnExit(e); }
}
