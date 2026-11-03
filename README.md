# 超二收菜 · Chao2Harvester

用于 Windows / MuMu 模拟器的《超进化物语2》日常任务助手，当前版本 **0.9.66**。通过 MuMu ADB 获取游戏画面，使用 MaaFramework 进行识别，WPF 提供任务设置与运行界面。

## 下载与启动

从 [Releases](https://github.com/lonelynoodle/Chao2Harvester/releases/latest) 下载 Windows 完整发布包并解压。

**mumu打开超进化物语2，然后点击bin下面的exe启动就行**

程序为 `bin/Chao2Harvester.exe`。请保留解压后的完整目录，程序需要同级的 `runtime`、`chao2`、`resource` 和 `config.json`。打开界面后选择任务并点击开始；仅打开程序不会自动操作游戏。

发布包附带 Python 和 .NET 运行环境。若 MuMu 安装位置或 ADB 端口与默认设置不同，请在设置中填写实际路径和地址。

## 功能

- 主线、异象、狩猎、浮空巨塔、永生之茧、部落冒险、凿星裂痕、黑暗森林、斗技场等日常任务。
- 庆典活动、免费奖励、饲星商店、屯屯扑满及其他任务，可按需勾选。
- 保存队伍选择、失败后备用队伍、资源保留和任务模板。
- 页面识别失败后的回退重试、实际结算核验、运行记录与停止操作。
- 拼二大作战、幻境巡游等小工具。

0.9.66 修复主线换队前后的关号识别：局部复读、连续两帧确认、原目标校验和有限重试。保留此前的孢子批量购买、深渊先换队后压制、任务结束不自动回切队伍等规则。

## 从源码构建

源码 ZIP 不包含完整运行环境和编译后的 exe。直接使用请选择 Releases 中的完整发布包。

开发环境：Windows x64、Python 3.12、.NET 10 SDK、MuMu 模拟器。PowerShell 中执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\build-frontend.ps1 -SelfContained
.\.venv\Scripts\python.exe scripts/package_runtime.py
```

构建结果写入 `bin`，便携 Python 写入 `runtime/python`。`package_runtime.py` 要求目标目录不存在，防止混入旧依赖。使用开发虚拟环境时可不生成便携 Python，前端会回退到 `.venv`。

```powershell
.\.venv\Scripts\python.exe -m pytest
.\build-frontend.ps1 -SelfContained -Smoke
```

公开源码不包含真实账号截图和 OCR 记录。依赖私人截图的测试会明确跳过，其余测试正常执行；前端离线检查不会操作游戏。

## 目录

- `chao2/`：Python 任务、识别与工作进程。
- `frontend/`：WPF 界面源码。
- `resource/`：识别模板、OCR 模型和规则。
- `config.json`：默认设置，保留现有任务与模板配置。
- `tests/`：公开回归测试及离线模拟进程。
- `scripts/`：运行环境和发布包构建脚本。

运行时生成的 `reports/`、`debug/`、`config/`、调试截图和本机环境均不提交。反馈问题前请检查日志与截图，移除账号信息。

## 开源许可

项目代码采用 [AGPL-3.0](LICENSE)。MAA 界面来源与改动见 [frontend/UPSTREAM.md](frontend/UPSTREAM.md)，依赖、模型和游戏素材说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。游戏名称、图标和素材归相应权利人所有，本项目不是官方产品。
