# Windows 安装版构建与验收

关联 Issue：#71。

## 构建

在 Windows x64 上安装 uv、64 位 Python 和 Inno Setup 7。
仓库构建依赖由 uv.lock 锁定；Inno Setup 是单独安装的系统构建工具。

```powershell
cd D:\Project\linkforge
powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1
```

编译器会从 PATH、当前用户 Programs 和 Program Files 中查找，也可以明确指定：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_installer.ps1 -IsccPath "C:\路径\Inno Setup 7\ISCC.exe"
```

脚本先同步锁定依赖，重新构建 PyInstaller onedir 和内置 Chromium，运行冻结 EXE 自检。
自检成功后生成便携 ZIP，并使用同一新构建目录编译 Setup。不要把开发目录或日常使用过的程序目录作为安装源。

当前版本输出：

- `dist/LinkForge-v0.1.0-beta.1-windows-x64-setup.exe`
- `dist/LinkForge-v0.1.0-beta.1-windows-x64-setup.exe.sha256`

版本取自新构建目录的 BUILD-INFO.json。setup.exe 包含整个程序、浏览器及许可证，无需用户安装 Python。

## 安装与用户数据

中文向导按当前用户安装，不请求管理员权限。默认安装到 `%LOCALAPPDATA%\Programs\LinkForge`，支持选择目录。
默认创建开始菜单入口，桌面快捷方式可选；静默安装不会自动启动程序。

安装器写入 `installed.ini` 标记，使冻结应用将日志写到 `%LOCALAPPDATA%\LinkForge\logs`。
未带标记的便携版仍写 EXE 同级 `logs`，源码版仍写仓库 `logs`。
GUI 的“打开日志文件夹”使用实际日志位置。不要手动删除安装标记。

浏览器目录、QSettings 和系统凭据机制沿用现有实现。
固定 AppId 为 `LinkForge.Desktop`，覆盖安装默认沿用原安装目录。升级前关闭程序及其浏览器。
普通卸载只删除安装文件和快捷方式，不清理用户日志、登录状态、QSettings 或凭据。
当前覆盖安装不承诺从更高版本降级，也不提供自动更新。

## 验收

在尚未安装 LinkForge 的 Windows 测试账户中运行自动验收：

```powershell
uv run --locked python scripts/verify_installer.py dist/LinkForge-v0.1.0-beta.1-windows-x64-setup.exe
```

脚本会核对 SHA-256，在 build 下的中文带空格目录中静默安装、自检、覆盖安装并卸载。
它会临时创建当前用户的卸载登记和开始菜单快捷方式，验收后由卸载器移除。
如果该账户已经安装 LinkForge，会拒绝执行，以免影响日常安装。
报告、截图和自检日志保留，真实用户配置和凭据不会被自检读取。
本地覆盖安装验证使用同一候选版本，不能替代跨版本升级验收。

```powershell
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run mypy src
```

发布前验证：

- 在干净 Windows x64 环境中运行中文安装向导，确认免管理员安装及目录选择。
- 从开始菜单与可选桌面快捷方式启动，确认 GUI、内置 Chromium 与日志入口正常。
- 保存配置并登录，关闭程序后覆盖安装，确认配置与登录目录保留。
- 验证中文及带空格安装路径下的 `--self-test`，并检查报告和截图。
- 卸载后确认程序和快捷方式移除，用户数据保留。
- 使用真实课程验收当前支持的任务流程，单元测试及离线自检不能替代这一步。

构建与验收文件位于 build/ 和 dist/，不提交 Git。测试安装必须使用隔离目录，避免覆盖日常使用的安装。

## 本次候选验收记录（2026-10-09）

候选文件：`LinkForge-v0.1.0-beta.1-windows-x64-setup.exe`，374,535,976 字节。
使用本机 Inno Setup 7 编译，SHA-256：

```text
d29da7afac29d904efef1e0001c67f90e6001d6c4c3dd6ba727b3d35770f22f7
```

- 新构建的冻结程序离线自检通过，含 Qt、系统凭据库、内置 Chromium 和浏览器目录持久化。
- 自动安装验收通过：中文带空格路径下首次安装、自检、同版本覆盖安装、自检及卸载。
- 开始菜单入口和 installed.ini 存在；安装版日志位于用户数据目录。
- 卸载后测试程序、开始菜单入口及卸载登记已移除，自检日志保留。
- 人工查看自检截图：中文正常，主要控件无重叠。
- `uv run pytest`：604 项通过。
- `uv run ruff format --check .`、`uv run ruff check .`、`uv run mypy src`：通过。
- 本机报告与截图：`build/安装验收 空格-v7bq7132/`。

未完成项：干净 Windows 环境、中文安装向导的交互检查、桌面快捷方式、跨版本升级及真实课程验收。
本次安装验收不读取真实课程、用户配置或已保存的 API Key。
