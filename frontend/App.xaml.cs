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
        if (!Smoke && !ConfirmFirstUse()) { Shutdown(); return; }
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

    private static bool ConfirmFirstUse()
    {
        string settingsDirectory = Path.Combine(Root, "config");
        string acknowledgement = Path.Combine(settingsDirectory, "first-use-notice-v1.txt");
        if (File.Exists(acknowledgement)) return true;

        const string notice = """
            超二收菜完全免费，可在 GitHub Releases 自行下载。有人冒用项目名义收取下载费、激活费或「防封费」时，请勿付款，谨防诈骗。
            https://github.com/lonelynoodle/Chao2Harvester/releases/latest

            本工具通过模拟器截图进行纯视觉识别，并模拟点击和滑动。项目未获游戏运营方授权。请遵守游戏规则，未经许可请勿在游戏中使用自动化工具。

            使用本工具可能违反游戏规则，并导致误操作、资源损失、账号限制或封禁。在适用法律允许的范围内，使用者自行承担使用风险及相应后果。

            确认后打开程序。选择取消则退出。
            """;
        var choice = MessageBox.Show(notice, "超二收菜 · 首次使用提醒",
            MessageBoxButton.OKCancel, MessageBoxImage.Warning, MessageBoxResult.Cancel);
        if (choice != MessageBoxResult.OK) return false;

        try
        {
            Directory.CreateDirectory(settingsDirectory);
            File.WriteAllText(acknowledgement, "已确认首次使用提醒");
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // A read-only folder can still open the app and show the notice on its next launch.
        }
        return true;
    }

    protected override void OnExit(ExitEventArgs e) { singleton?.Dispose(); base.OnExit(e); }
}
