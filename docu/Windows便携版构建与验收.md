# Windows 便携版构建与验收

关联 Issue：<https://github.com/ethen887/linkforge/issues/65>

## 构建

在 Windows x64 使用 64 位 Python 3.12 与 uv，从仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

该命令同步 uv.lock，安装包内 Chromium，再按 build-support/windows/LinkForge.spec 构建。
首次需要联网下载依赖和浏览器。每次使用新的 build/windows-* 暂存目录，
避免把先前运行生成的日志、登录状态或人工添加的文件带进候选包。

输出为 dist/LinkForge-v0.1.0-beta.1-windows-x64.zip 及 .zip.sha256。
构建脚本也打印未压缩候选目录。build/ 与 dist/ 不提交 Git。
Python 包版本采用 0.1.0b1，发行文件名采用 v0.1.0-beta.1。
版本变更时同步更新使用说明。

运行时钩子强制使用包内浏览器与 Node 驱动，不依赖构建电脑的环境变量。
构建子进程的 PATH 仅包含当前 Python 和 Windows 系统目录，避免其他开发工具的
ICU 等同名 DLL 被误收集；spec 同时拒绝来自虚拟环境、Python 和 Windows 以外的二进制。
API Key、Qt 用户设置和浏览器用户目录不会作为打包输入。
发行包保留依赖许可证、构建环境版本清单和补充许可证原文。

## 自动化检查

```powershell
uv run --locked pytest
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy src
```

## 成品离线自检

开发机可先执行以下脚本，它校验 SHA-256、检查 ZIP 中没有用户数据目录，
解压到新的中文空格路径，移除子进程 PATH 中的开发工具，并设置无效外部浏览器和
Node 路径来验证运行时钩子能使用包内组件：

```powershell
uv run --locked python scripts/verify_windows.py dist/LinkForge-v0.1.0-beta.1-windows-x64.zip
```

先解压 ZIP 到新的中文、带空格路径。使用下列方式运行，确保等待 EXE 退出：

```powershell
$packageExe = 'D:\测试目录\LinkForge\LinkForge.exe'
$reportFile = 'D:\测试目录\package-check.json'
$checkProcess = Start-Process -FilePath $packageExe -ArgumentList @('--self-test', ('"' + $reportFile + '"')) -PassThru -Wait -WindowStyle Hidden
$checkProcess.ExitCode
Get-Content -LiteralPath $reportFile
```

自检使用临时 INI 配置和浏览器用户目录，不读取普通用户的设置或 API Key。
凭据库仅操作 LinkForge.PackageCheck 服务下新建的随机测试条目，结束后删除。
检查包含：Qt 窗口截图、设置重新读取、Windows 凭据后端、包内 Chromium
路径、离线页面操作、两次启动浏览器后的测试 Cookie 持久化、日志生成。
输出 JSON 和 PNG；错误细节位于程序同级 logs。自检不会调用模型或访问课程。

开发机自检不等于干净系统验收，也不覆盖真实 API 连通性及课程兼容性。

## 干净 Windows 人工验收

在没有 Python/uv/Node.js、没有 Playwright 缓存的 Windows x64 机器或虚拟机上：

- [ ] 完整解压后双击启动，中文界面和反馈入口正常。
- [ ] 程序同级生成 logs，按钮打开正确目录。
- [ ] 在不可写的程序目录运行时给出可操作提示。
- [ ] 默认浏览器目录位于用户 LocalAppData；自定义路径被保留。
- [ ] 配置自己的 API Key，启动内置浏览器，手动登录课程。
- [ ] 关闭重启后配置和 API Key 可恢复，登录有效时可复用。
- [ ] 验证视频、PDF/电子书、测验、讨论、跨章节导航与完成节点跳过。
- [ ] 停止及关闭窗口清理浏览器；等待当前任务边界的行为符合说明。
- [ ] 新版解压到另一目录后仍读取相同设置和登录数据。
- [ ] 记录系统版本、模型、覆盖功能与失败情况，不记录凭据或完整课程链接。

## 发布

候选包验收、PR 审查和合并后，才创建版本标签及 GitHub Release。
若合并前源码有变化，重新构建并验证候选包。
上传 ZIP 和 SHA-256；发布说明必须保留课程末尾完成判定等已知限制。
不得将本机自检描述为已通过全新 Windows 或真实课程验收。
