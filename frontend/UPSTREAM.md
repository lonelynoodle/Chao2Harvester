# MAA 界面来源与改动

上游：[MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights)，MAA Team，AGPL-3.0。
固定源码版本：`fb19933e5d7e708873d4e7edb7e5065cfdd6908f`（dev-v2）。

直接复用的样式：

- `Styles/Button.xaml` ← `src/MaaWpfGui/Res/Styles/Button.xaml`
- `Styles/CheckBox.xaml` ← `src/MaaWpfGui/Res/Styles/CheckBox.xaml`
- `Styles/ListBox.xaml` ← `src/MaaWpfGui/Res/Styles/ListBox.xaml`
- `Styles/MaaLight.xaml` ← `src/MaaWpfGui/Res/Themes/Light.xaml`
- `Styles/NumericUpDown.xaml` ← `src/MaaWpfGui/Res/Styles/NumericUpDown.xaml`
- `Styles/Divider.xaml` ← `src/MaaWpfGui/Res/Styles/Divider.xaml`
- `Styles/Geometries.xaml` ← `src/MaaWpfGui/Res/Styles/Basic/Geometries.xaml`

`MainWindow.xaml` 由上游 `Views/UI/RootView.xaml`、`Views/UI/TaskQueueView.xaml` 中的窗口、横向标签页、任务列表、完成后动作、开始/停止和日志区域裁剪改编。小工具区域参考 `ToolboxView.xaml`，阵容编辑参考 `FightSettingsUserControl.xaml` 的 `StagePlan`；输入样式沿用 MAA 的 HandyControls 资源。

保留 WPF、HandyControls 3.6.0 和 gong-wpf-dragdrop 4.0.0；主题改为青绿色。去掉方舟专属配置、核心任务、托盘和更新服务，新增超二任务设置、模板、资源配置、运行历史、小工具及 Python 工作进程桥接。没有移植 MaaCore 或明日方舟任务。

`App.xaml.cs`、`MainWindow.xaml.cs` 与 `chao2/gui_worker.py` 接入超二后台，启动界面不会自动执行游戏任务。停止指令由标准输入传递，父进程关闭时工作进程响应停止。

本地改编代码采用 AGPL-3.0，完整许可证见项目根目录 `LICENSE`。原样式的版权声明保留在源码中，依赖许可见 `THIRD_PARTY_NOTICES.md`。
