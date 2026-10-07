# Windows v0.1.0-beta.1 候选包验收记录

日期：2026-10-07。关联 Issue：<https://github.com/ethen887/linkforge/issues/65>。
分支：`codex/windows-portable-release`。

本记录针对本地候选包；尚未公开发布，也尚未完成干净 Windows 和真实课程验收。

## 候选产物

- 文件：`dist/LinkForge-v0.1.0-beta.1-windows-x64.zip`
- 大小：421,474,090 字节（约 402 MiB）。
- SHA-256：`a208cd0caf55f22c257a2163ce1d1dcfbdf7d45a2c2ed8c3739d6173fed3ef43`
- 格式：PyInstaller onedir，内置 Chromium 和 Playwright Node 驱动。
- 构建环境：Windows 11 x64（10.0.26200）、Python 3.12.14、PyInstaller 6.22.3、Playwright 1.62.0。
- Python 项目版本：`0.1.0b1`。

## 已完成检查

| 检查 | 结果 |
| --- | --- |
| `uv run --locked pytest --tb=short -q` | 539 passed，包含 12 项新增测试 |
| `uv run --locked ruff format --check .` | 148 个文件格式通过 |
| `uv run --locked ruff check .` | 通过 |
| `uv run --locked mypy src` | 通过 |
| `git diff --check` | 通过 |
| `powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1` | 生成候选目录、ZIP 与校验文件 |
| `uv run --locked python scripts/verify_windows.py dist/LinkForge-v0.1.0-beta.1-windows-x64.zip` | 最终 ZIP 自检通过 |

成品自检从 ZIP 解压到中文且带空格的新目录，并移除子进程 PATH 中的开发工具。
故意传入不存在的外部 Chromium 和 Node 路径后，运行时钩子仍正确使用包内组件。

通过的成品检查：

- `frozen=true`，确认执行的是 EXE。
- 原生 Windows Qt 界面能够构建与渲染，人工检查截图中文清晰、控件无明显重叠。
- 临时 QSettings 配置保存及重新读取成功。
- Windows 原生 keyring 后端可写入、读取并删除独立的临时测试条目。
- Chromium 路径位于发布包内，可加载离线 HTML 页面。
- 同一临时浏览器用户目录关闭并再次启动后，测试 Cookie 仍存在。
- 日志生成在 EXE 同级 logs 目录。
- ZIP SHA-256 匹配，未包含 logs、browser-profile、.venv 或 .env 路径。

本地详细报告与界面截图：`build/验收 空格-vwffu391/package-check.json` 和同名 PNG。
此目录属于本机验收产物，不提交 Git，也不进入发布 ZIP。

## 已修复的打包问题

- editable 安装在元数据枚举中重复出现，导致许可证收集失败；现按包名及版本去重。
- 开发机 PATH 中其他工具的 ICU DLL 被误收集，导致 QtWidgets 无法加载；
  构建 PATH 已隔离，spec 同时校验二进制来源。
- Windows Qt offscreen 后端截图无法正确显示字体；成品自检改为原生 Windows
  字体引擎下的隐藏窗口渲染，不修改普通用户界面的字体设置。

## 尚需人工验收

- [ ] 在没有 Python、uv、Node.js 和 Playwright 缓存的独立 Windows x64 环境运行。
- [ ] 使用用户自己的模型配置、学习通账号，验证真实课程中的各类任务。
- [ ] 在真实使用中关闭并重启应用，确认配置、API Key 和有效登录状态复用。
- [ ] 将新版解压到另一目录，验证既有用户配置及浏览器目录仍可使用。
- [ ] 在不可写目录实际启动候选 EXE，检查错误提示；当前已有单元测试覆盖该分支。
- [ ] 验证真实课程执行时的停止和退出行为；本次保留既有逻辑并通过回归测试。

本机未检测到可用的 Windows Sandbox 启动程序。开发机隔离 PATH 的自检不能替代
干净系统验收。尚未调用真实模型或处理用户课程，也未宣称整个课程能可靠判定完成。

后续验收步骤见 [Windows 便携版构建与验收](Windows便携版构建与验收.md)。
