# LinkForge

LinkForge 是基于 Python 3.12+、Playwright 和大模型的浏览器自动化项目，采用 `src/` 布局。
目前提供桌面 GUI，主要处理学习通课程任务，同时保留可扩展的浏览器观察、动作执行与 Agent 模块。
应用代码位于 `src/linkforge/`，测试位于 `tests/`，项目说明位于 `docu/`。

本文件仅提供项目介绍和规则路由。根据任务读取下表中所有适用文档；具体规则维护在 `ai/` 中，
无需一次读取全部文档。表内相对路径均以仓库根目录为基准。

## 规则路由表

| 任务或读取时机 | 文档 | 内容 |
|---|---|---|
| 所有项目任务开始时 | [ai/git.md](ai/git.md)、[ai/security.md](ai/security.md) | 协作流程、工作区保护、凭据与用户数据约束 |
| 涉及本机开发环境或项目时 | `D:\Dev\AI\AI.md` | 本机规则入口及环境文档的按需路由 |
| 定位代码、增加模块、调整职责或架构时 | [ai/architecture.md](ai/architecture.md) | 目录职责、模块边界、设计原则 |
| 编写 Python、安装依赖、运行或配置开发工具时 | [ai/python.md](ai/python.md) | Python 版本、uv、编码规范、运行命令 |
| 修改行为、编写测试、检查文档、验证变更或准备 PR 时 | [ai/testing.md](ai/testing.md) | 测试组织、质量检查、验证记录 |
| 提交、推送、创建或评审 PR 时 | [ai/git.md](ai/git.md) | Issue、分支、Commit、PR 模板与评审流程 |
| 构建或验收 Windows 便携版时 | [ai/python.md](ai/python.md)、[ai/testing.md](ai/testing.md)、[Windows 便携版构建与验收](docu/Windows便携版构建与验收.md) | 构建环境、检查要求与发行验收步骤 |
