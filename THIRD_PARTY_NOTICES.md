# 第三方组件与素材

项目代码采用 AGPL-3.0；下列组件、模型和素材保留各自许可与版权。

- **MAA WPF 界面代码**：[MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights)，MAA Team，AGPL-3.0。具体版本、复用文件和修改见 `frontend/UPSTREAM.md`。完整许可证见根目录 `LICENSE`。
- **MaaFramework 5.14.3**：[MaaFramework](https://github.com/MaaXYZ/MaaFramework)，LGPL-3.0。使用官方 Python wheel 和动态链接库，未修改框架源代码；随附许可位于 `runtime/python/Lib/site-packages/maafw-5.14.3.dist-info/`。
- **MaaAgentBinary 1.0.1**：MaaFramework 的依赖，随原 wheel 保留版权与许可。本项目自定义显示屏控制器没有调用其触摸代理。
- **opencv-python-headless 4.14.0.94**：[opencv-python](https://github.com/opencv/opencv-python)。完整许可和第三方说明见 `licenses/opencv-python-LICENSE.txt`、`licenses/opencv-3RD-PARTY.txt`。
- **HandyControls 3.6.0**：[HandyControls](https://github.com/ghost1372/HandyControls)，MIT。完整许可随前端位于 `bin/HandyControls-LICENSE.txt`。
- **gong-wpf-dragdrop 4.0.0**：[gong-wpf-dragdrop](https://github.com/punker76/gong-wpf-dragdrop)，BSD-3-Clause。完整许可随前端位于 `bin/Gong-WPF-DragDrop-LICENSE.txt`。
- **.NET / WPF**：[dotnet/wpf](https://github.com/dotnet/wpf)，MIT 等组件许可证。完整发布包附带 Windows x64 运行时及其许可文件。
- **Python 3.12**：[Python](https://www.python.org/)，PSF 等许可证，原文位于 `runtime/python/LICENSE.txt`。NumPy、Pillow、StrEnum 及原生依赖按原 wheel 分发，其许可证保留于对应 dist-info 目录；版本见 `requirements-runtime.lock`。pytest 等开发依赖只列于 `requirements.lock`，不加入运行环境。
- **PaddleOCR ONNX 模型与字典**：[MAA PaddleOCR 资源](https://github.com/MaaAssistantArknights/MaaAssistantArknights/tree/3b4f06dd8684f8540092c810f4951d8ea78b6685/resource/PaddleOCR)。检测和识别模型已与该提交中 `det/inference.onnx`、`rec/inference.onnx` 做 SHA-256 对照，字节完全相同；`keys.txt` 去除换行格式差异后逐行一致。上游 MAA 采用 AGPL-3.0，基础 [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) 采用 Apache-2.0。未修改模型或宣称自行训练。
- **nneonneo/2048-ai 的 Expectimax 与行估值方法**：[2048-ai](https://github.com/nneonneo/2048-ai)，Robert Xiao 与贡献者，MIT。`chao2/puzzle_solver.py` 参考其搜索、缓存及估值方法，使用 Python 实现游戏内3×3棋盘规则；未使用其4×4二进制程序。完整上游许可见 `licenses/2048-ai-MIT.txt`。
- **《超进化物语2》游戏图标与识别素材**：图标和裁剪后的界面模板用于游戏识别与展示，游戏名称、商标和美术归原权利人所有，不属于本项目对代码授予的许可。本工具不是官方产品。

本项目没有包含 MAA 的明日方舟任务或 MaaCore。
