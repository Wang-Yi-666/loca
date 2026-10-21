# Loca

> **轻量级、零框架依赖的工业级 Coding Agent Harness**  
> 从零自研的 Agent 运行时底座：统一 DeepSeek / Anthropic / OpenAI 工具调用协议，具备高容错流式执行循环、双 Shell 宿主安全防御、断点续聊与原子级代码回滚、全链路 Trace 与自动化行为式评测基准。

---

## 为什么从零自研 Harness？

主流 Agent 项目往往简单地将提示词贴在 LLM SDK 之上，或者重度依赖 LangChain、LlamaIndex 等高阶框架。但在真实的自动化编码场景中，**95% 的工程复杂度都集中在 Harness（运行时底座）这一层**：

- **协议碎片化**：不同模型厂商在 Tool Calling、思考内容（`reasoning_content`）、流式参数碎片分发上的行为各异；
- **执行脆弱性**：网络抖动、模型输出被 Token 截断、工具参数不合法容易导致 Agent 执行流直接崩溃；
- **并发与阻塞**：长耗时推理与命令执行会挂死异步 Web 事件循环；多文件读取时串行等待让执行延时倍增；
- **宿主安全风险**：缺乏防护的 Shell 调用可能因模型幻觉或注入攻击触发灾难性误删（如 `rm -rf /`），超时也极易产生孤儿后台进程；
- **缺乏退路**：代码一旦被模型改坏，缺少确定性的原子级快照撤销机制；
- **缺乏量化依据**：改动效果缺少固定、严密、防拟合的评测基准，优化沦为盲目调优。

**Loca 刻意摒弃一切重型 Agent 框架，核心控制流全部自主实现。** 代码层次清晰透明，所有关键决策均可测、可控、可复现。

---

## 核心架构与工程亮点

### 1. 跨厂商统一协议层
- **多模型无缝切换**：抽象厂商中立的 `LLMProvider` 接口，支持 DeepSeek、OpenAI 与 Anthropic。DeepSeek / OpenAI 共享协议兼容层，Anthropic 走独立的流式事件与工具映射翻译层。
- **参数严格校验**：基于 `jsonschema` 对模型吐出的工具调用进行前置校验，参数畸形时抛出结构化错误回灌模型自愈，杜绝运行时异常打断 Agent。
- **一致性保证**：同一任务在三家厂商上的流式事件与工具分发均有参数化回归测试钉牢。

### 2. 高容错流式执行循环
- **首包前防抖重试**：针对限流（429）、网关超时（504）等瞬时故障实施指数退避重试，且**严格限制在首个分片到达前重试**，坚决不向用户重放已看到的内容。
- **截断自动续写**：遇到 `finish_reason=length` 触发长度超限时，自动无缝注入「继续」指令完成拼接。
- **摘要式压缩**：Token 预算超限时，调度模型将早期对话提炼为核心摘要钉在窗口头部（支持 `tiktoken` 真实分词），避免粗暴丢弃历史造成关键信息失忆。
- **异常优雅降级**：不可恢复的 Provider 异常以标准 `error` 事件回传，不掐断 SSE 连接与长轮询。

### 3. 高并发与异步非阻塞设计
- **Web 端后台工作线程池**：FastAPI / SSE 服务端将同步阻塞的 Agent 执行循环解耦至后台独立工作线程，通过 `asyncio.Queue` 实现线程安全推流，彻底解决长耗时推理阻塞 Uvicorn 事件循环导致 `/api/health` 假死的问题。
- **只读工具并发加速**：单步批次工具调用若均为只读操作（如同时 `read_file` 多个文件），自动通过线程池并发拉取，严格维持结果回灌与事件流的保序性，成倍降低阅读耗时。

### 4. 双 Shell 宿主纵深防御
- **原生双 Shell 支持**：针对 Windows 开发机场景，提供现代双解释器：`bash`（Git Bash，默认主力，跑测试/Git）与 `powershell`（处理 Windows 专有 cmdlet 与注册表），均解析为显式绝对路径，彻底告别脆弱的 `shell=True`。
- **高危破坏性指令拦截**：内置敏感模式前置拦截机制，拦截 `rm -rf /`、`rm -rf C:\`、`del /s /q`、`format`、`shutdown` 等毁灭性指令，阻断破坏并反馈错误引导模型自纠。
- **超时强杀进程树**：基于 `CREATE_NEW_PROCESS_GROUP` 与系统底层 API，执行超时后精准强杀整棵子进程树，杜绝后台死锁与孤儿进程占用端口。
- **三维输出截断**：按行长、行数、总字节三重防护截断输出，并完全隔离宿主敏感的 `LOCA_*` 环境变量。

### 5. 断点续聊与原子级快照回滚
- **SQLite WAL 状态持久化**：默认落地 `~/.loca/sessions.db`，会话随时跨进程恢复续聊；
- **写前快照与精准回滚**：`write_file` 与 `edit_file` 执行前自动为目标文件保存原子快照。通过 `loca rollback <session> <step>` 可一键回滚到任意历史步之前；新建的文件会被**物理删除**而非清空，Web GUI 提供一键 `↩ undo` 操作。

### 6. 全链路双写可观测性（Trace）
- **SQLite + JSONL 双写冗余**：记录每个模型步的 Prompt 摘要、回复、思考内容（`reasoning`）、工具执行耗时与 Token 开销。即便数据库损坏或删除，纯文本 `.jsonl` 镜像仍可用于复盘。
- **结构化报告渲染**：`loca report <session>` 支持终端美化表格打印、`--verbose` 展开逐步细节及 `--json` 供自动化脚本消费。

### 7. 行为式自动化评测基准（Benchmark）
- **36 个自带实战任务**：覆盖简单、中等、困难三个层级（涵盖单测修复、算法实现、重构排错等）。
- **行为式判分，不比代码 Diff**：跑真实的执行循环与真实工具，只看最终行为（执行 `pytest`、比对标准输出、运行校验脚本）。
- **严格沙箱与防作弊机制**：判分用例存放在 `hidden/` 目录下，模型执行期间物理不可见；判分前才覆写回沙箱，模型修改自身测试用例完全无效。
- **任务集自校验（Verify）**：`loca bench verify` 自动校验「初始状态必挂、参考答案必过」，从机制上排除假阴性与噪音干扰。

---

## 项目代码结构

```
loca/
├── cli.py             # 统一 CLI 入口：chat / sessions / rollback / report / bench / serve / tools
├── agents.py          # 具名 Agent 策略定义（提示词 / 工具集 / 预算限额）及唯一装配点 build_agent()
├── providers/         # 厂商中立的 LLM 抽象层 + DeepSeek / OpenAI / Anthropic 适配实现
├── tools/             # 工具抽象协议 + read_file / write_file / edit_file / bash / powershell + 注册表
├── core/              # 核心执行循环（AgentLoop）、事件系统、错误恢复、上下文压缩管理器
├── observability/     # SQLite 持久化（SessionStore）、快照与回滚管理器（CheckpointManager）、Trace 收集与报告
└── eval/              # Benchmark 评测基准：36 道实战题目、并发执行引擎、自动化判分与自校验

web/                   # FastAPI + SSE 异步非阻塞服务端与单页 Web 聊天应用
scripts/               # 快速启动辅助脚本
docs/                  # 深度实战与设计指南（CLI、Web GUI、会话回滚、轨迹报告、评测集）
tests/                 # 485 项全离线自动化测试套件 + 8 项真实 API 端到端测试
```

---

## 评测数据（最新实测）

- **模型**：DeepSeek 默认模型（`deepseek-chat`）
- **环境**：现代双 Shell（Git Bash 主力 + PowerShell）+ 宿主安全防御底座
- **任务集**：36 道自带行为式任务，每题单次运行，4 并发执行
- **核心指标**：**pass@1 = 97.2%（35/36）**

| 难度分级 | 题目数量 | 通过题数 | 通过率 | 平均 Token 消耗 / 题 | 平均步数 / 题 |
|---|---:|---:|---:|---:|---:|
| 简单（simple） | 14 | 13 | 92.9% | 11,355 | 5.2 |
| 中等（medium） | 12 | 12 | 100.0% | 16,803 | 5.8 |
| 困难（hard） | 10 | 10 | 100.0% | 18,686 | 5.4 |
| **全量合计** | **36** | **35** | **97.2%** | **15,074** | **5.3** |

*整轮消耗 536k tokens，并发墙钟耗时 72 秒（1.2 分钟）。困难题（Hard）10/10 全部满分通过。原始报告存档于 [`docs/benchmarks/deepseek-36.json`](docs/benchmarks/deepseek-36.json)，评测复现与归因详见 [`docs/benchmark.md`](docs/benchmark.md)。*

---

## 运行环境约定

**原生针对 Windows 开发机环境深度优化**，不做无实效的跨平台分支假设，确保每行系统交互代码真实可靠：

| 维度 | 技术约定 |
|---|---|
| **操作系统** | Windows 10 / 11 |
| **解释器** | **bash**（Git Bash，默认主力执行环境）+ **powershell**（Windows 专有管理） |
| **工作区路径** | 严格 Windows 路径规范，如 `D:\Projects\repo`（拒绝 `/d/repo` 盘符相对路径隐患） |
| **Python** | 3.13+ |

---

## 快速开始

```powershell
# 1. 创建并激活虚拟环境
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. 安装项目及开发依赖
pip install -e ".[dev]"

# 3. 配置环境变量
Copy-Item .env.example .env
# 打开 .env 填入你的 DEEPSEEK_API_KEY

# 4. 执行全量离线测试
pytest -v
```

---

## 交互使用

Loca 提供 CLI 终端与 Web GUI 两种使用模式，均通过同一入口逻辑装配。

### 1. 终端流式 REPL —— `loca chat`

```text
$ loca chat --workspace D:\Projects\repo
loca · provider deepseek · 5 tool(s) · workspace D:\Projects\repo

you › 请阅读 README.md 并总结核心优势
assistant → read_file(path='README.md')
✓ read_file
assistant Loca 的核心优势主要体现在三个方面...
                        steps 1  ·  tokens 812  ·  finish stop
```

**常用 CLI 指令速查：**

| 命令 | 说明 |
|---|---|
| `loca chat` | 启动交互式 Agent 对话（默认持久化至 SQLite） |
| `loca chat --workspace <dir>` | 指定 Agent 的沙箱工作区目录 |
| `loca chat --session <id>` | 恢复指定会话断点续聊（不存在则新建） |
| `loca chat --no-tools` | 纯流式模型直聊模式（用于隔离排查 Provider 异常） |
| `loca chat --no-save` | 一次性体验模式（不落库、不留检查点） |
| `loca sessions` | 列出历史所有已保存的会话记录与步数 |
| `loca rollback <session> <step>` | 将指定会话的文件状态还原到第 `<step>` 步之前 |
| `loca report <session>` | 渲染打印该会话的完整执行轨迹与耗时统计（支持 `--verbose` / `--json`） |
| `loca bench run` | 并发执行 36 道自动化评测基准并输出通过率报告 |
| `loca serve` | 启动 Web 界面服务端（默认挂载在 `http://127.0.0.1:8765`） |

*REPL 内置快捷指令：`/help`、`/compact`（手动压缩上下文）、`/rollback`（撤销最近一次文件修改）、`/session`、`/trace`。*

### 2. 单页 Web GUI —— `loca serve`

通过 `loca serve` 启动内置的 FastAPI 服务，直接在浏览器中与 Agent 交互：
- 渲染独立的流式文本、思考气泡、工具调用卡片与执行耗时；
- 支持实时更换已验证的工作区路径；
- 每个文件写入步骤均展示快照卡片，并提供图形化 `↩ undo` 一键回滚撤销。

### 3. VS Code 一键调试集成

项目根目录配齐了完善的 `.vscode/launch.json`，按 `Ctrl+Shift+D` 即可选中一键启动：
- `loca chat (CLI REPL)`：直接在 VS Code 集成终端启动交互式对话；
- `loca serve (Web GUI)`：启动后台服务并**自动调起浏览器**打开页面；
- `pytest (offline)`：一键离线回归验证所有 485 项单元测试。

---

## 质量保证

项目遵循高标准的工业代码质量规范：
- **测试覆盖**：**485 项全离线自动化测试**（零失败、零跳过）+ **8 项真实 DeepSeek API 端到端集成测试**，全量合计 **493 项测试**；
- **静态检查**：全仓库通过 `ruff check .` 零告警静态分析；
- **架构隔离**：核心循环与外部接口完全解耦，入口模块禁止自行初始化循环，单一装配点确保功能无遗漏。

---

## 深入参考文档

- 📖 [CLI 终端运行与交互详解](docs/running-the-cli.md)
- 🌐 [Web GUI 架构与网络排错说明](docs/running-the-web-gui.md)
- 💾 [会话持久化、检查点与快照回滚机制](docs/sessions-and-rollback.md)
- 📊 [执行轨迹（Trace）双写与报告解析](docs/traces-and-reports.md)
- 🎯 [自动化评测集（Benchmark）设计与可信度剖析](docs/benchmark.md)
- 📝 [复盘思考：如何科学评测一个 Coding Agent](docs/blog-benchmarking-a-coding-agent.md)

---

## 许可证

[MIT](LICENSE)
