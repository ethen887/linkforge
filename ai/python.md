# Python 与开发工具

## 环境与依赖

- 使用 Python 3.12+；CI 目前使用 Python 3.12，代码保持 3.12 兼容。
- 使用 `uv` 和已提交的 `uv.lock` 管理项目环境，依赖声明集中在 `pyproject.toml`。
- 不在系统 Python 或共享运行时中安装项目依赖；依赖变更同步维护配置与锁文件。
- 工具配置以 `pyproject.toml` 为准；本机工具链问题按 `D:\Dev\AI\AI.md` 路由排查。

在仓库根目录执行：

```powershell
uv sync --locked
```

需要启动桌面 GUI 时：

```powershell
uv run playwright install chromium
uv run python src/linkforge/gui.py
```

## 编码规范

- 使用四空格缩进，遵循 Ruff 的 108 字符行宽。
- 模块、函数与变量使用 `snake_case`，类使用 `PascalCase`。
- 公共接口提供清晰的类型标注。
- 只对本次需要格式化的文件执行 `uv run ruff format <文件路径>`。
  仅在全仓库格式化属于任务范围时执行 `uv run ruff format .`。
- 质量检查命令统一见 [testing.md](testing.md)，模块边界见 [architecture.md](architecture.md)。

## Windows 打包

- 构建入口为 [scripts/build_windows.ps1](../scripts/build_windows.ps1)，
  调用 [scripts/build_windows.py](../scripts/build_windows.py)；打包配置与运行时钩子位于
  `build-support/windows/`。依赖、GUI 入口或浏览器路径变更时检查对便携版的影响。
- 便携版采用 PyInstaller onedir，包含 Chromium 和 Node 驱动；保留包内组件及依赖许可证，
  不让成品依赖开发机的浏览器缓存或工具 PATH。
- 构建使用新的暂存目录，`build/`、`dist/` 不提交；用户设置、凭据和浏览器用户目录不作为打包输入。
- 构建与发行验收按 [Windows 便携版构建与验收](../docu/Windows便携版构建与验收.md) 执行，
  不在本文件重复维护版本号、产物名称或完整验收清单。
