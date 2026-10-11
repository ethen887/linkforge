# 测试与质量检查

## 测试组织

- 使用 `pytest`。测试文件命名为 `test_<feature>.py`，测试类为 `Test<Feature>`，
  测试函数为 `test_<behavior>`。
- `tests/unit/` 与 `tests/integration/` 按产品模块组织；浏览器集成测试位于
  `tests/integration/browser/`，共享测试替身放在 `tests/fakes.py`。
- 行为变更增加或更新对应单元测试。
- 需要真实 Chromium 等运行时的跨模块测试放入 `tests/integration/`；当前项目按目录组织，
  未配置独立的 `integration` pytest marker，不依赖 `-m integration` 选择测试。
- 自动化测试必须能在没有真实课程账号和模型凭据时安全运行。
- 日常验证先运行与改动相关的测试；文档变更检查内容、链接和差异。

## 隔离与回归范围

- 浏览器与平台集成测试使用本地 HTML、data URL 或临时文件，模型调用使用测试替身；
  不把真实课程或付费模型服务作为默认测试依赖。
- GUI 测试沿用 [conftest.py](../tests/unit/ui/conftest.py) 中的 offscreen、临时 `QSettings` 与
  `FakeCredentialStore` 隔离，不读取或写入真实用户设置和系统凭据。
- 浏览器持久化测试使用 `tmp_path` 下的独立 profile，日志测试使用临时日志目录。
- 调整应用生命周期或 GUI 线程时覆盖启动失败、运行失败、停止请求及资源清理；
  调整平台识别或导航时覆盖未知状态与完成证据不足的分支。
- [smoke_quiz.py](../src/linkforge/platforms/chaoxing/smoke_quiz.py) 会访问真实课程、调用模型并提交
  测验与讨论，仅在用户明确授权该真实课程验证范围时运行，不纳入默认测试或 CI。
- 文档检查包括相对链接、代码块闭合、命令与当前配置一致，以及 `git diff --check`；
  只修改文档且未准备 PR 时无需为此启动真实课程或运行完整代码测试。

## 完整质量检查

在仓库根目录执行，开 PR 前必须完成：

```powershell
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run mypy src
```

浏览器测试需要 Playwright Chromium，安装命令见 [python.md](python.md)。
CI 在面向 `main` 的 push 和 PR 上执行上述四项检查，Linux GUI 测试使用
`QT_QPA_PLATFORM=offscreen`；具体配置见 [ci.yml](../.github/workflows/ci.yml)。

## 验证记录

- 报告实际执行的命令和结果，区分相关测试通过与完整质量检查通过。
- 发现已有失败时记录证据，不为通过检查扩大本次修改范围。
- 未执行或受环境限制的检查说明原因，不将其报告为通过。
- 便携版源码测试通过、成品离线自检通过、干净 Windows 验收通过与真实课程验证通过分别记录；
  具体步骤见 [Windows 便携版构建与验收](../docu/Windows便携版构建与验收.md)。
