# AGENTS.md — Loca 项目规范与协作指南

> 本文档为各类 AI 编程助手（如 Antigravity, Cursor, Claude Code, GitHub Copilot 等）及人类开发者在本项目中工作时的最高准则。进行任何修改前必须严格阅读并遵循。

---

## 1. 项目概览 (Project Overview)

**Loca** 是一个轻量级、零重型框架依赖（无 LangChain / LlamaIndex）的工业级 Coding Agent Harness（运行时底座）。
* **核心目标**：统一 DeepSeek / Anthropic / OpenAI 工具调用协议，提供高容错流式执行循环、双 Shell 宿主安全防御、断点续聊与原子级快照回滚、全链路 Trace 与自动化行为式评测基准。
* **语言与版本**：Python 3.13+
* **主代码目录**：`loca/` (Harness 核心), `web/` (FastAPI + SSE Web GUI), `tests/` (自动化测试), `docs/` (项目文档)

---

## 2. 开发环境与常用命令 (Environment & Commands)

### 2.1 运行环境规范
* **必须使用本地虚拟环境**：所有命令必须在 `.venv` 下执行：
  * Windows PowerShell: `.\.venv\Scripts\python.exe` 或 `.\.venv\Scripts\pytest.exe`
  * Git Bash: `./.venv/Scripts/python`
* **宿主 Shell 区别（Windows 环境）**：
  * **`bash` (Git Bash)**：默认与优先使用的 POSIX Shell。用于运行测试、git、构建脚本和通用命令行工具。路径格式优先使用 MSYS 前缀（如 `/d/Projects/loca`）或正斜杠（`D:/Projects/loca`），避免在 bash 中使用反斜杠 `\`。
  * **`powershell` (Windows PowerShell)**：仅在涉及 Windows 原生能力（服务、注册表、特定 cmdlet）时调用。注意 PowerShell 5.1 不支持 `&&`，需使用 `;` 串联。

### 2.2 核心检验命令
进行任何功能或重构改动后，**必须运行并确保全部通过**：

```powershell
# 1. 离线单元测试（必须 100% 通过，当前基准：485 项通过）
.\.venv\Scripts\pytest.exe -m "not live"

# 2. 单个文件或特定测试用例
.\.venv\Scripts\pytest.exe tests/test_agents.py -k test_build_agent

# 3. 静态代码分析与代码格式检查（必须零 warning/error 退出）
.\.venv\Scripts\ruff.exe check .

# 4. 评测集完整性与 Grader 自检（36 题必须全部正常通过）
.\.venv\Scripts\python.exe -m loca.cli bench verify
```

### 2.3 本地服务启动命令
```powershell
# 启动 CLI REPL 交互界面
.\.venv\Scripts\python.exe -m loca.cli chat

# 启动 Web GUI 服务（自动暴露在 127.0.0.1:8765）
.\.venv\Scripts\python.exe -m loca.cli serve --host 127.0.0.1 --port 8765
```

---

## 3. 架构分层与依赖流向规范 (Architecture & Boundaries)

本项目具有极为严格的单向依赖层次，**坚决杜绝任何反向依赖或循环依赖**：

```
       ┌────────────────────────┐
       │   CLI / Web / Eval     │ (入口层 / 应用层)
       └───────────┬────────────┘
                   │
                   ▼
       ┌────────────────────────┐
       │     loca.agents        │ (组装层：定义 AgentSpec 与 build_agent)
       └───────────┬────────────┘
                   │
     ┌─────────────┼──────────────┐
     ▼             ▼              ▼
┌──────────┐ ┌───────────┐ ┌──────────────┐
│loca.core │ │loca.tools │ │loca.providers│
└──────────┘ └───────────┘ └──────────────┘
     │             │              │
     └─────────────┼──────────────┘
                   ▼
       ┌────────────────────────┐
       │  loca.observability    │ (基础设施：Trace, Checkpoint, Storage)
       └────────────────────────┘
```

### 依赖红线守则：
1. **`loca.core` 是通用纯净 Harness**：
   * `loca.core` 只负责执行循环控制流、上下文压缩与事件总线分发。
   * **绝对禁止**在 `loca.core` 中导入 `loca.agents`、`loca.providers` 或 `loca.tools`。
2. **`loca.agents` 是组装层**：
   * 负责将 Spec、工具列表、Provider、SessionStore 组装为运行时 `AgentRuntime`。
   * **下层模块严禁反向导入 `loca.agents`**。
3. **`loca.eval.tasks` 夹具隔离**：
   * `loca/eval/tasks/` 下的代码是评测题目与故意包含缺陷的夹具（seed code），**不要对其运行代码格式化或自动修复它的 Lint 警告**（`ruff` 已在配置中排除该目录）。

---

## 4. 关键设计原则与防御策略 (Core Principles)

1. **零崩溃保证与自愈反馈**：
   * 模型吐出的 Tool Calling 参数在执行前必须经过 [loca.tools.validation](file:///d:/Projects/loca/loca/tools/validation.py) 基于 `Draft7Validator` 的强类型前置校验。
   * 参数校验失败必须抛出格式化错误信息并回灌至 Agent 上下文，引导模型自我修正，绝不能让未捕获异常中断主事件循环。
2. **只读工具并发与保序性**：
   * 单步多工具调用若均为只读工具（如 `read_file`），底层支持并行加速，但回灌的 Tool Result 和 SSE 事件流必须严格保持调用顺序。
3. **宿主安全与破坏性指令拦截**：
   * `bash` 与 `powershell` 工具必须始终通过绝对路径解析，严禁使用 `shell=True`。
   * 必须维持高危指令过滤机制（拦截 `rm -rf /`、`rm -rf C:\`、`format` 等）。
   * 必须维护子进程树超时强杀机制（基于 Windows Job Objects / `CREATE_NEW_PROCESS_GROUP`），防止僵尸/孤儿进程占用端口。
4. **状态持久化与文件安全**：
   * 破坏性写文件操作（`write_file`, `edit_file`）前必须自动保存文件快照，确保可安全回滚。
   * 回滚操作恢复历史快照时，对于该步骤新建的文件应采取**物理删除**，而非置空。

---

## 5. 编码规范 (Coding Style Guidelines)

* **类型标注**：全量开启强类型标注，文件头部包含 `from __future__ import annotations`。使用现代联合类型（`X | None`、`list[str]`、`tuple[str, ...]`），避免过时的 `typing.Optional` / `typing.Union`。
* **代码行长**：严格遵守最大 **100 字符** 行长限制。
* **注释与文档保持**：保留既有的高质量设计文档型注释（docstrings），不得以“重构”为由随意删减阐明设计决策的注释。
* **Git Commit 规范**：使用标准语义化提交（Conventional Commits），如：
  * `feat(...)`: 新功能
  * `fix(...)`: 缺陷修复
  * `test(...)`: 测试补充
  * `refactor(...)`: 重构

---

## 6. 开发者与 Agent 协作自查清单 (Checklist)

修改代码后，在回复用户或提交 PR 之前，执行以下自查：
- [ ] 运行 `.\.venv\Scripts\pytest.exe -m "not live"`，485 项测试全部通过（0 失败，0 报错）。
- [ ] 运行 `.\.venv\Scripts\ruff.exe check .`，无任何静态检查警告。
- [ ] 检查依赖流向：没有破坏 `core` 与 `agents` 之间的解耦单向流。
- [ ] 确认没有意外篡改 `loca/eval/tasks/` 中的任务种子与评测夹具。
