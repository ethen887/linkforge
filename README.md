# LinkForge

LinkForge 是一个面向开发者的 Browser Agent Framework，用于构建可观察网页状态、生成结构化决策并执行浏览器动作的 Agent。

> Build reliable browser agents around explicit observation, decision, and action boundaries.

## 项目状态

LinkForge 当前处于早期开发阶段。

当前首先建立稳定的 Browser、Observation、Action 和 Agent Loop 核心边界，面向项目开发者进行使用和测试。

当核心功能、模块接口和工作流稳定后，再增加图形化界面。

## 当前目标

LinkForge 将逐步实现以下能力：

- 浏览器自动化控制
- 结构化网页状态观察
- 结构化浏览器动作执行
- 可扩展的大模型接口
- Browser Agent 环境交互循环
- 结构化日志与错误诊断
- 自动化测试
- 面向多人协作的工程流程

## 设计原则

1. 能够通过确定性规则完成的任务，不交给大模型判断。
2. 核心业务逻辑不能依赖命令行或未来的图形化界面。
3. 浏览器、模型接口和数据库属于可替换的外部实现。
4. 遇到未知页面状态时停止操作，而不是盲目点击。
5. 敏感操作应当支持人工确认。
6. API Key、Cookie和登录状态不得进入Git仓库。
7. 所有正式修改都应通过Issue、功能分支和Pull Request完成。

## 开发流程

项目采用Issue驱动和Pull Request驱动的开发方式。

详细规则请阅读：

[CONTRIBUTING.md](CONTRIBUTING.md)

## 开发阶段

当前阶段：

```text
仓库规范建立
→ Python工程初始化
→ 浏览器基础能力
→ Observation 与 Action
→ Browser Agent Loop
→ 大模型接入
→ LLM Browser Agent
→ CLI 产品化
→ GUI开发
