# Loca — Coding Agent Harness

> 6 周路线图 + 实时进度清单。每完成一项就勾选，状态同步更新。

最后更新：2026-09-11 10:58

---

## 整体进度

| Week | 主题 | 状态 | 完成度 |
|------|------|------|--------|
| 1 | Provider 抽象层 | ✅ 完成 | 100% |
| 2 | Tool 协议 + 基础工具 | ✅ 完成 | 100% |
| 3 | 执行循环 + 错误恢复 | ✅ 完成 | 100% |
| 4 | Session 持久化 + Checkpoint | ⬜ 未开始 | 0% |
| 5 | 可观测性 + 多 Provider | ⬜ 未开始 | 0% |
| 6 | Benchmark + 报告 | ⬜ 未开始 | 0% |

---

## Week 1 — Provider 抽象层 ✅ 已完成

- [x] 建项目脚手架（`pyproject.toml` + 包结构 + venv）
- [x] 定义 `Message` / `ToolCall` / `Usage` / `ChatRequest` / `ChatResponse` / `StreamChunk` 等公共类型
- [x] 写 `LLMProvider` 抽象基类
- [x] 实现 `DeepSeekProvider`（流式 + 工具调用 + `reasoning_content` 分离）
- [x] 写 `OpenAIProvider` / `AnthropicProvider` stub（缺 key 时抛 NotImplementedError）
- [x] 实现 `get_provider()` / `available_providers()` registry
- [x] 写 10 个离线单元测试
- [x] 写 3 个 DeepSeek 端到端测试（问一句话、流式累积、registry 解析）
- [x] 真实跑通 `13 passed`（含 e2e）

**Week 1 交付物**：Provider 抽象完整，能真实调 DeepSeek 流式对话；多 provider 架构已搭好。

---

## Week 2 — Tool 协议 + 4 个基础工具 ✅ 已完成

### Tool 抽象层

- [x] `Tool` 抽象基类 + `to_openai_tool()` 辅助方法
- [x] **JSON Schema 校验器**（`loca/tools/validation.py`）— 用 `jsonschema` 库，模型输出不合规时抛 `SchemaValidationError`
- [x] `ToolRegistry` 注册/查找/列出工具

### 4 个基础工具

- [x] **`read_file`**（`loca/tools/filesystem.py`）— 读文件，支持行号切片、行截断、UTF-8 校验
- [x] **`write_file`** — 写文件（overwrite/append 两种模式、自动创建父目录、1MB 上限）
- [x] **`edit_file`** — 字符串替换编辑（unique match 校验、global_replace 模式、返回 unified diff）
- [x] **`bash`**（`loca/tools/bash.py`）— 执行 shell 命令，30s 超时（可调，上限 600s）、stdout/stderr 分离、行长/行数/字节三重截断、`cwd` 沙箱校验、隔离 `LOCA_*` 环境变量

### 测试

- [x] 校验器测试：10 个（合法/非法、嵌套、enum、错类型）
- [x] `read_file` 测试：13 个（happy path、错误路径、沙箱、长行截断）
- [x] `write_file` 测试：10 个（创建/覆盖/append/子目录/沙箱/容量上限）
- [x] `edit_file` 测试：10 个（unique/global/无匹配/空 find/UTF-8/沙箱）
- [x] `bash` 测试：13 个（echo/退出码/stderr/cwd 沙箱/超时/截断/环境隔离）
- [x] **流式 tool_call 装配回归测试**（`tests/test_deepseek_stream.py`，4 个）— 钉住「参数碎片拼完才吐出一整个 call」
- [x] e2e 测试：让 DeepSeek 真的调 `bash "echo hello"` 并在回答中体现

### 交互

- [x] `scripts/interactive_chat.py` — 流式对话 CLI
- [x] **HTML 前端**（`web/server.py` + `web/index.html`）— FastAPI + SSE，深色聊天 UI，工具调用/结果卡片、token 统计
- [x] **CLI REPL**（`loca chat`）— 流式输出 + 工具调用实时打印 + 多轮 transcript 回灌
- [x] **一键启动入口**（`.vscode/launch.json`）— VS Code `F5` 启动 CLI / Web GUI / 测试套件；`loca/__main__.py` 支持 `python -m loca`

### 项目脚手架增强

- [x] 把项目从 C 盘迁到 `D:\Projects\loca`（用户偏好 D 盘）
- [x] `.vscode/settings.json` — pytest 配置、虚拟环境关联、formatter
- [x] `.vscode/extensions.json` — 推荐 Python / pytest / ruff 扩展
- [x] `.vscode/launch.json` — 6 个一键运行/调试配置（CLI、Web、诊断、离线测试、全量测试）
- [x] `conftest.py` — 自动加载 `.env` 环境变量
- [x] `pyproject.toml` 注册 `live` marker — 离线/联网测试可分流（`pytest -m "not live"`）

**Week 2 验收标准**：能用 DeepSeek 通过工具调用 `bash "echo hello"` 看到结果。✅ 已达标

---

## Week 3 — 执行循环 + 错误恢复 ✅ 已完成

### 主循环（`loca/core/loop.py`）

- [x] `调模型 → 解析 tool_calls → 执行 → 把结果塞回 context`，直到模型不再要求工具
- [x] 终止条件：无 `tool_calls` 即 `DONE`
- [x] 最大步数限制（默认 20，超出后 `DONE(reason="max_steps")`）
- [x] `last_transcript`：暴露完整会话消息，供多轮对话复用（系统提示词不会被重复插入）
- [x] 每次 provider 调用前做上下文预算裁剪
- [x] 请求发出时对消息列表做快照，避免后续 append 污染已记录的请求（trace 友好）

### 错误恢复（`loca/core/recovery.py`）

- [x] **工具层自纠**：未知工具 / 参数不合 schema / 工具内部异常 → `ToolResult(is_error=True)`，模型下一轮据此修正
- [x] **瞬时故障重试**：`RetryingProvider` 指数退避 + 抖动（可注入 `sleep`，便于测试）
  - 分类：`APITimeoutError` / `RateLimitError` / `APIConnectionError` / 5xx / `httpx` 超时连接错误 → 可重试；4xx、鉴权失败 → 立刻失败
  - 支持 `status_code` 与 `__mro__` 名字匹配，不 import 厂商 SDK
  - **流式语义**：只在「尚未吐出任何 chunk」时重试 —— 已产出内容绝不重放，避免重复输出与重复工具调用
- [x] **输出截断恢复**：`finish_reason=length` → 追加「从断点继续，不要重复」指令并重新请求（`EventType.RECOVERY`）
- [x] **上下文压缩**：`trim_messages()` 估算 token 并按需丢弃最旧轮次
  - 始终保留 system prompt 与最近 `keep_recent` 条
  - **剔除孤儿 tool 消息**（父 assistant tool_call 已被裁掉时），否则 OpenAI 协议会 400
  - 通过 `EventType.CONTEXT_TRIMMED` 事件上报裁剪量
- [x] **不可恢复异常**：转成 `EventType.ERROR` 事件（带 `retryable` 标记），不抛出、不打断 SSE 流
- [x] token 估算器：ASCII ~4 字符/token，CJK ~1 字符/token，无需下载分词器

> 设计取舍：重试用自研退避（`recovery.py`）而非 tenacity。流式「吐字前才可重试」的语义用生成器表达最直接，tenacity 的 `retry_if_exception` 无法干净地表达「已 emit 就不重试」。tenacity 保留在依赖里，留给 Week 5 provider 层限流用。

### 交互

- [x] **`loca` CLI 真正可用**（此前是 `raise NotImplementedError`）
  - `loca chat` — 带工具的交互式 REPL（多轮、工具卡片、重试/裁剪提示、token 统计）
  - `loca chat --no-tools` — 纯流式聊天
  - `loca serve` — 起 Web UI
  - `loca tools` / `loca providers` — 自检命令
- [x] `scripts/interactive_chat.py` 收敛成 `loca chat` 的薄启动器（去掉重复实现）
- [x] Web UI 新增 `context trimmed` / `recovery` / `error` 三类事件的展示

### 测试

- [x] 单测：循环终止条件、最大步数、错误注入（`tests/test_loop.py`）
- [x] 重试与裁剪：`tests/test_recovery.py` 25 项（退避时序、流式不重放、重试耗尽、孤儿 tool 消息、token 估算、截断续写）
- [x] CLI：`tests/test_cli.py` 10 项（`run_turn` 渲染、多轮 transcript、子命令）
- [x] Web SSE：`tests/test_web_server.py` 6 项（事件映射、error 事件、history 透传）
- [x] e2e（真实 DeepSeek）：模型用 `write_file` 写脚本 → 用 `bash` 执行 → 引用输出

**Week 3 验收**：✅ 已跑通「写脚本并执行」的完整多步任务（`test_deepseek_writes_and_runs_a_script`）。

**测试统计**：`123 passed, 1 skipped`（其中 6 项是真实 DeepSeek e2e）；`ruff check .` 全绿。

---

## Week 4 — Session 持久化 + Checkpoint ⬜ 未开始 ← **下一步**

> 起手点已备好：`AgentLoop.last_transcript` 里就是完整的 `list[Message]`，
> 直接序列化即可落库；`EventType` 已经覆盖逐步轨迹所需的全部事件。
> Week 3 的「上下文压缩」第一半（token 估算 + 按需裁剪）已在
> `loca/core/recovery.py` 完成，Week 4 只需在其上补「按模型切分器精确计数」
> 与「摘要早期消息」。

- [ ] **Session 持久化**（`loca/observability/storage.py`）
  - [ ] SQLite 存储：消息历史、配置、metadata
  - [ ] session_id 命名 + 列出/恢复/删除 session
- [ ] **Checkpoint**
  - [ ] 每次工具执行前存文件快照
  - [ ] 支持回滚到指定 checkpoint
  - [ ] CLI 子命令 `loca rollback <session_id> <step>`
- [ ] **上下文压缩**（`loca/core/context.py`）
  - [ ] token 计数（按模型不同切分器）
  - [ ] 超出阈值时摘要早期消息（替代当前的直接丢弃）
- [ ] **测试**
  - [ ] session 恢复、checkpoint 还原
  - [ ] 上下文压缩前后 token 对比

**Week 4 验收**：关掉 CLI 重开能继续上次的任务。

---

## Week 5 — 可观测性 + 多 Provider ⬜ 未开始

- [ ] **Trace 模块**（`loca/observability/trace.py`）
  - [ ] 每步记录：prompt、response、tool_calls、tool_results、token、耗时
  - [ ] JSONL / SQLite 双写
- [ ] **Reporter**（`loca/observability/reporter.py`）
  - [ ] `loca report <session_id>`：渲染漂亮的执行轨迹
  - [ ] token 统计、工具调用次数、错误率
- [ ] **Anthropic Provider 完整实现**（有 key 后）
  - [ ] `messages.create` 适配 Anthropic 协议
  - [ ] tool_use blocks → `ToolCall` 转换
  - [ ] 流式 event stream 适配
- [ ] **OpenAI Provider 完整实现**（5 行，DeepSeek 已经走通 OpenAI 协议）
- [ ] **测试**
  - [ ] trace 落盘 + reporter 输出
  - [ ] provider 切换在相同任务上结果一致

**Week 5 验收**：能跑真实 coding 任务并看完整 trace 报告。

---

## Week 6 — Benchmark + 报告 ⬜ 未开始

- [ ] **评估 harness**（`loca/eval/benchmark.py`）
  - [ ] 任务定义格式（prompt + 工具集 + 验证函数 + 评分）
  - [ ] 并发跑 N 个任务
  - [ ] pass@1 / pass@10 / 错误分类
- [ ] **自带 30-50 个 coding 任务**（`loca/eval/tasks/`）
  - [ ] 简单：单文件修改、bug 修复
  - [ ] 中等：跨文件改动、加测试
  - [ ] 困难：算法实现、依赖升级
- [ ] **对比报告**
  - [ ] DeepSeek vs（如果接了）Anthropic 在任务集上的表现
  - [ ] token 消耗、成功率、平均步数
- [ ] **文档 + 博客**
  - [ ] 完整 README（架构图、quick start、设计取舍）
  - [ ] 一篇 1500-2000 字的技术博客草稿
  - [ ] 简历项目描述

**Week 6 验收**：能在 30 个任务上跑出 pass@1 报告，并写出可发布的博客。

---

## 本次会话变更日志

### 2026-09-11（第五次）— 初始化 git 仓库并建立首个提交

用户要求把进度 push 到远程仓库。核查后发现**项目从未 `git init`**（`.gitignore` 写了但没仓库），所以先补齐本地版本控制。

- **环境发现**：git 不在 `PATH` 上 —— 它装在 WorkBuddy 的 PortableGit（`…\binaries\PortableGit\versions\1.2.0\cmd\git.exe`，v2.55.0），因此所有 git 操作都要走绝对路径。提交身份已全局配置：`Lyrico <1137005501qq@gmail.com>`。
- **仓库清理**（提交前）：
  - `Web_GUI_启动与关闭全流程.png` → 移入 `docs/images/web-gui-lifecycle.png`
  - 删除 SSE 调试残留 `sse_raw.txt`
  - `.gitignore` 新增 `.workbuddy/`（工具产生的开发笔记，属本地数据不入库）
  - 新增 `.gitattributes`：`* text=auto eol=lf` + 二进制/Windows 脚本例外。此前 `git add` 时每个文件都报 `LF will be replaced by CRLF`，不加这个以后每次改动都会产生整文件换行符 diff。
- **安全审计**：`git add -A` 后显式检查暂存区，确认 `.env`（含 DeepSeek API key）、`.venv/`、`.workbuddy/` **均未进入**。
- **首个提交**：`63ccfa0` on `main`，51 files changed / 6687 insertions。提交信息按模块分节说明 `providers/` `tools/` `core/` `cli.py` `web/` `tests/` 的设计要点。
- **回归**：提交后 `pytest` → 123 passed, 1 skipped；`ruff check .` → 全绿。

### 2026-09-11（第四次）— CLI 使用文档 + 修掉工作目录歧义

用户接着问「CLI 从哪启动」。核查时发现 `loca chat` 完全可用，但**默认工作目录设成了 `playground/`，引起一个真实歧义**：

- **实测暴露的坑**：让 CLI（workspace = `playground\`）"在 playground 里创建 hello.py"，模型写到了 `playground\playground\hello.py` —— 因为**模型不知道自己的工作目录就叫 playground**，它按仓库结构理解，就多套了一层。目录命名引起误解，不是模型的错。
- **修法**：
  - `loca chat (CLI REPL)` 默认配置改为**工作目录 = 项目根**（与 Web GUI 的 `DEFAULT_WORKSPACE` 一致），说"读 README.md"不再有歧义
  - 保留沙箱需求，另开一个配置 `loca chat (sandboxed to playground/)`
  - launch.json 从 6 个配置增至 7 个
- **清掉测试残留**：删除 `playground/playground/hello.py` 与整个 `playground/`（仅含该测试产物）
- **新增 `docs/running-the-cli.md`**（中文，8 节）：CLI vs GUI 选择表、两种启动方式、真实对话逐行解读（`→` / `✓` 怎么读）、一轮统计（`steps`/`tokens`/`finish`/`prompt`+`completion`）的含义、**`Ctrl+C` 的两种含义**（答题中=只打断本轮并回到 `you:`；等待输入时=退出）、工作目录专章、参数速查、常见问题
- **`.vscode/extensions.json`**：补 `ms-python.debugpy`（让 `"type": "debugpy"` 的依赖显式化），移除已废弃的 `littlefoxteam.vscode-python-test-adapter`（`settings.json` 用的是 Python 扩展内置 pytest 支持）
- **README 双语两侧**更新配置表（7 项）并加上 CLI 指南链接

### 2026-09-11（第三次）— 新增 Web GUI 运行指南

用户要一份「怎么启动、怎么关闭」的详细教程（自述非科班出身，网络概念不熟）。

- **新增 `docs/running-the-web-gui.md`**（中文，10 节）：
  - 概念铺垫：服务端/客户端、端口、`127.0.0.1`，用「自家客厅开窗口」类比；讲清 SSE 为什么是"一个字一个字蹦出来"的
  - 两种启动方式：VS Code `F5`（推荐）与终端 `.venv\Scripts\python.exe -m loca.cli serve`，并解释**为什么不能直接敲 `loca serve`**（console script 不在 PATH）
  - 三种"确认活着"的办法，含 `/api/health` 三个字段的逐项解读
  - 关闭：`Shift+F5`（调试）/ 终端 `Ctrl+C`，以及"怎么确认真的关了"
  - **排错专章**：端口占用的真实报错原文 + 三步定位（`netstat -ano | findstr :8765` 读最后一列 PID → `tasklist` 确认 → `taskkill /F /PID`），另给 PowerShell 一行版与换端口方案
  - 参数速查 + 常见问题速查表 + 一页速查卡片
- **安全性说明**：明确指出**不要**把 `--host` 改成 `0.0.0.0`，否则等于把能执行任意 shell 的 agent 暴露给局域网
- **`web/index.html`**：内嵌 SVG data-URI favicon，消掉浏览器自动请求 `favicon.ico` 产生的 404 噪音（新手会把 404 当成故障）
- **README 双语两侧**均加上指向该指南的链接
- **教程里所有命令与输出均实测**：端口占用报错用 socket 占位真实复现（`[Errno 10048]`，exit 3）；`netstat` / `taskkill` 完整走了一遍（PID 8012 杀掉后端口释放、curl 变 connection refused）

### 2026-09-11（第二次）— README 改为中英双语

- **`README.md` 重写为双语**：中文在前（`# 中文文档`），英文在后（`# English`），顶部加语言导航锚点；英文部分保持原文措辞不变
- **修正过时数据**：README 原先写「123 offline tests + 6 live e2e」，实际离线 116 + 联网 7（总 123）
- **`.env.example` 加中文注释**（逐行对照，非替换），既然是给用户看的模板就保持一致
- 范围说明：`loca_roadmap.md` 仍是纯中文工作清单（双语会让日常勾选变啰嗦），代码注释与 docstring 保持英文（Python 生态惯例）

### 2026-09-11 — 补齐「两个界面」的启动入口

问题：GUI/CLI 其实早就有了，但**没有一键入口** —— `loca.exe` 装在 `.venv\Scripts\` 里，不开虚拟环境就不在 PATH 上，所以在项目里"找不到界面"。

- **新增 `.vscode/launch.json`** —— VS Code 原生一键启动（`Ctrl+Shift+D` → 选配置 → `F5`）：
  - `loca chat (CLI REPL)`：集成终端跑交互式 CLI，沙箱到 `playground/`
  - `loca chat --no-tools`：纯流式聊天，用来隔离 provider 层问题
  - `loca serve (Web GUI)`：起 uvicorn **并自动打开浏览器**（`serverReadyAction`）
  - `loca tools / providers`：诊断配置
  - `pytest (offline)` / `pytest (all, hits real API)`：离线套件与含真实 API 的套件
- **新增 `loca/__main__.py`** —— `python -m loca chat` 现在可用，不依赖 console script 在 PATH 上
- **`live` marker 正式化**（`pyproject.toml` + 两个 e2e 文件 + `test_cli.py`）：
  - 离线/联网测试不再只能靠文件名区分，`pytest -m "not live"` 成为正式用法
  - 实测：全量 `123 passed` / 离线 `116 passed, 7 deselected` / 联网 `7 passed`
- **README 重写「两个界面」章节** —— 补上 CLI REPL 的实际交互样例、子命令表、Web GUI 说明、VS Code 配置对照表
- **`.gitignore`**：放行 `launch.json`，忽略 `playground/`（CLI 的临时沙箱）与 `.ruff_cache/`
- **验证方式**：后台常驻启动 uvicorn → `GET /api/health` 返回 `providers_with_keys: ["deepseek"]` → 真实 SSE 打 `bash "echo gui-smoke-ok"`，观察到 `text → tool_call(bash) → tool_result → text` 完整闭环
- **已知遗留**：pytest 有 1 条 `DeprecationWarning`（`anyio.abc.BlockingPortal`），来自 starlette 内部，非项目代码，不处理

### 2026-09-10（第三次）— Week 2 收口 + Week 3 完成
- **Week 2 收口**：`bash` 工具、13 个 bash 测试、HTML 前端（FastAPI + SSE）、流式 tool_call 装配回归测试 —— 全部核对通过，标记 Week 2 完成
- **新增 `loca/core/recovery.py`**：
  - `is_transient()` 瞬时错误分类（不 import 厂商 SDK，按 `status_code` + MRO 名字匹配）
  - `RetryingProvider` 指数退避 + 抖动，可注入 `sleep`/`on_retry`
  - `trim_messages()` / `estimate_tokens()` / `count_tokens()` 上下文预算与裁剪
- **`AgentLoop` 增强**：
  - `retries`（默认 2）与 `context_token_budget`（默认 48k）参数
  - 不可恢复异常 → `EventType.ERROR` 事件，不再打断 SSE 流
  - `finish_reason=length` → 自动续写（`EventType.RECOVERY`）
  - `last_transcript` 暴露完整会话；修复「回灌历史导致 system 重复插入」
- **修掉两个真实 bug**：
  - `ChatRequest` 持有 `messages` 同一列表引用，后续 append 会污染已记录的请求 → 改为发请求时快照
  - `loca providers` 没加载 `.env`，误报「no key」
- **`loca` CLI 落地**：`chat` / `serve` / `tools` / `providers` 四个子命令，`scripts/interactive_chat.py` 收敛为薄启动器
- **Web UI**：新增 `context_trimmed` / `recovery` / `error` 事件渲染
- **新增测试**：`test_recovery.py`(25) + `test_cli.py`(10) + `test_web_server.py`(6) + 1 个多步 e2e
- **代码质量**：`ruff check .` 从 58 项问题清到全绿（补行尾换行、删未用 import、拆分超长行；`UP042` 按设计取舍显式 ignore）
- **测试总数**：`56 passed` → **`123 passed, 1 skipped`**（含 6 项真实 DeepSeek e2e）
- **验证方式**：真实启动 uvicorn，用 curl 打 SSE 观察 `text → tool_call → tool_result → text → done` 全链路

### 2026-09-10（第二次）
- **Week 2 进度**：
  - 新增 `WriteFileTool`（overwrite/append、自动创建父目录、1MB 上限）
  - 新增 `EditFileTool`（unique match 校验、global_replace、unified diff 返回）
  - 新增 20 个测试（write_file 10 个 + edit_file 10 个）
  - 修复：WriteFile "new file" 标志位（之前在写入后才检查 path.exists()）
  - 修复：edit_file 空 find 测试改用 `pytest.raises(SchemaValidationError)`（schema 层 minLength 拦截）
- **文件位置变更**：`loca_roadmap.md` 从桌面迁到 `D:\Projects\loca\loca_roadmap.md`（用户偏好跟随项目）
- **测试总数**：从 36 升到 56 passed

### 2026-09-10（第一次）
- **Week 1 标记完成**：13 passed（含 3 个真实 DeepSeek e2e）
- **Week 2 进度**：
  - 新增 `loca/tools/validation.py`（JSON Schema 校验器）
  - 新增 `loca/tools/filesystem.py`（`ReadFileTool` + 路径沙箱策略）
  - 新增 `tests/test_validation.py`（10 个测试）
  - 新增 `tests/test_filesystem.py`（13 个测试，含沙箱拒绝路径遍历）
  - 修复：路径遍历 ValueError 改为返回 `ToolResult(is_error=True)`
  - 修复：测试断言用行号前缀而不是字符匹配（避免 header 干扰）
- **项目脚手架**：
  - 项目从 C 盘迁到 `D:\Projects\loca`（用户偏好 D 盘）
  - 加 `.vscode/settings.json` 和 `.vscode/extensions.json`
  - 加 `conftest.py`（自动加载 `.env`）
- **新增**：`scripts/interactive_chat.py`（流式对话 CLI）
- **测试总数**：从 13 升到 36 passed
- **文件位置变更**：`loca_roadmap.md` 从桌面迁到 `D:\Projects\loca\loca_roadmap.md`（用户偏好跟随项目）

### 2026-09-06
- 创建 `loca_roadmap.md` 初版
- 完成 Week 1 全套脚手架

---

## 怎么用这份清单

- **每完成一项**：把 `[ ]` 改成 `[x]`
- **每次会话结束**：在"变更日志"追加一段
- **想看进度**：直接看顶部"整体进度"表

需要修改直接编辑文件，或者告诉我"勾上 Week 2 的 X 项"我同步。
