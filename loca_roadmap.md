# Loca — Coding Agent Harness

> 6 周路线图 + 实时进度清单。每完成一项就勾选，状态同步更新。

最后更新：2026-09-18 17:06

---

## 平台约定：只支持 Windows

**明确不做多环境支持。** 目标是本地 Windows 开发机上的单用户 agent，多平台分支只会引入没人跑的代码路径。所有代码按 Windows 假设写。

| 项目 | 约定 |
|---|---|
| 平台 | Windows 10 / 11 |
| Shell | **cmd.exe**（不是 PowerShell，也不是 Git Bash） |
| 路径 | Windows 路径（`D:\repo`）；不接受 `/d/repo` 这类 Git-Bash 写法 |
| Python | 3.13+ |

落到代码上的三处约束：

1. `ShellTool` 固定把命令交给 cmd.exe —— `shell=True` + `executable=_shell_executable()`（仅当 `%COMSPEC%` basename 是 `cmd` 才用，否则回退 `cmd.exe`），不支持 POSIX 分支。工具描述与系统提示词都写明"用 `dir`/`type`/`del`，不是 `ls`/`cat`/`rm`"。
2. 命令行渲染改用 cmd 的引号风格（整行双引号、内部引号翻倍），不再用 `shlex.quote` 的 POSIX 单引号。
3. `--workspace` 直接拒绝 `/d/repo` 形态：`ntpath` 会把它当盘符相对路径，静默解析成 `D:\d\repo`（空目录）—— 「不报错但结果全错」，必须挡在门口。

---

## 整体进度

| Week | 主题 | 状态 | 完成度 |
|------|------|------|--------|
| 1 | Provider 抽象层 | ✅ 完成 | 100% |
| 2 | Tool 协议 + 基础工具 | ✅ 完成 | 100% |
| 3 | 执行循环 + 错误恢复 | ✅ 完成 | 100% |
| 4 | Session 持久化 + Checkpoint | ✅ 完成 | 100% |
| 5 | 可观测性 + 多 Provider | ✅ 完成 | 100% |
| 6 | Benchmark + 报告 | ✅ 完成 | 100% |

---

## Week 1 — Provider 抽象层 ✅ 已完成

- [x] 建项目脚手架（`pyproject.toml` + 包结构 + venv）
- [x] 定义 `Message` / `ToolCall` / `Usage` / `ChatRequest` / `ChatResponse` / `StreamChunk` 等公共类型
- [x] 写 `LLMProvider` 抽象基类
- [x] 实现 `DeepSeekProvider`（流式 + 工具调用 + `reasoning_content` 分离）
- [x] 写 `OpenAIProvider` / `AnthropicProvider` stub（缺 key 时抛 NotImplementedError）
  > ⚠️ **已过时**（2026-09-18 审查确认）：Week 5 已把两者改成完整实现，
  > 缺 key 时抛 `ValueError`。全仓库（排除评测夹具）已无任何 `NotImplementedError`。
  > 这一条保留为历史记录，不再代表当前代码。
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
- [x] **`shell`**（`loca/tools/shell.py`，原名 `bash.py`）— 执行 cmd.exe 命令，30s 超时（可调，上限 600s）、stdout/stderr 分离、行长/行数/字节三重截断、`cwd` 沙箱校验、隔离 `LOCA_*` 环境变量

### 测试

- [x] 校验器测试：10 个（合法/非法、嵌套、enum、错类型）
- [x] `read_file` 测试：13 个（happy path、错误路径、沙箱、长行截断）
- [x] `write_file` 测试：10 个（创建/覆盖/append/子目录/沙箱/容量上限）
- [x] `edit_file` 测试：10 个（unique/global/无匹配/空 find/UTF-8/沙箱）
- [x] `shell` 测试：13 个（echo/退出码/stderr/cwd 沙箱/超时/截断/环境隔离）
- [x] **流式 tool_call 装配回归测试**（`tests/test_deepseek_stream.py`，4 个）— 钉住「参数碎片拼完才吐出一整个 call」
- [x] e2e 测试：让 DeepSeek 真的调 `shell "echo hello"` 并在回答中体现

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

**Week 2 验收标准**：能用 DeepSeek 通过工具调用 `shell "echo hello"` 看到结果。✅ 已达标

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

> 设计取舍：重试用自研退避（`recovery.py`）而非 tenacity。流式「吐字前才可重试」的语义用生成器表达最直接，tenacity 的 `retry_if_exception` 无法干净地表达「已 emit 就不重试」。**tenacity 已于 2026-09-12 从依赖中移除**（无人 import，留着只是让依赖清单说谎）；Week 5 若真要做限流再按需加回。

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
- [x] e2e（真实 DeepSeek）：模型用 `write_file` 写脚本 → 用 `shell` 执行 → 引用输出

**Week 3 验收**：✅ 已跑通「写脚本并执行」的完整多步任务（`test_deepseek_writes_and_runs_a_script`）。

**测试统计**：`123 passed, 1 skipped`（其中 6 项是真实 DeepSeek e2e）；`ruff check .` 全绿。

---

## Week 4 — Session 持久化 + Checkpoint ✅ 已完成

### Session 持久化（`loca/observability/storage.py`）

- [x] **SQLite 存储**（`SessionStore`）：`sessions` / `messages` / `checkpoints` / `meta` 四张表
  - [x] 消息历史 + 配置 + metadata（workspace / provider / model / 自定义 JSON）
  - [x] `Message` ↔ 行 的序列化往返（含 `tool_calls` / `tool_call_id` / `reasoning_content`）
  - [x] 外键 `ON DELETE CASCADE`：删会话自动清消息与检查点
  - [x] `PRAGMA journal_mode=WAL`：`loca sessions` 读的时候不阻塞 `loca chat` 写
  - [x] `SCHEMA_VERSION` 落表，便于后续迁移判断
- [x] **session_id 命名 + 列出/恢复/删除**
  - [x] 自动 id：`20260911-113509-a1b2c3`（时间戳 + 随机后缀）
  - [x] `ensure_session()` 一次调用完成「恢复或新建」，并告诉调用方是哪种
  - [x] `list_sessions()` 按最近更新排序、带消息数；标题自动取第一条用户消息
  - [x] **步数计数器持久化**（`next_step`）—— 修掉「重启后 checkpoint step 归零导致回滚目标有歧义」的真实 bug
- [x] **transcript 整体重写**（`save_transcript`）：循环交来的是累积消息列表，且会因上下文裁剪而**变短**，所以用 `DELETE` + 批量插入的事务，而不是追加式日志

### Checkpoint（`loca/observability/checkpoint.py`）

- [x] **执行前快照**：`CheckpointManager.capture()` 在 `write_file` / `edit_file` 运行前存下目标文件
  - [x] 文本存原文，二进制走 base64，超 2 MB 只记名字（`restorable=False`）
  - [x] 路径一律存成**工作区相对的 POSIX 路径**，会话库可跨机器/盘符迁移
  - [x] 沙箱复用同一套规则：越界路径不读也不写
  - [x] `tracked={工具名: (参数名,)}` 可扩展，加工具不用改模块
- [x] **回滚到指定 checkpoint**：`rollback(session_id, step)`
  - [x] 语义：还原到「第 `step` 步**执行之前**」→ 撤销 `step` 及其之后的全部改动
  - [x] 范围内检查点**从新到旧**依次应用，最早的 pre-state 最终胜出
  - [x] 原本不存在的文件 → **删除**（而非清空）
  - [x] `RollbackReport.settled()`：同一文件被多次改动时，报告呈现的是**最终状态**而不是流水账
  - [x] 限制如实上报：`shell` 造成的改动不可回滚、超限文件 `skipped`
- [x] **CLI 子命令** `loca rollback <session_id> <step>`
- [x] 循环在工具执行前发出 `EventType.CHECKPOINT` 事件（CLI 渲染 `⛁ checkpoint @ step N · files`）

### 上下文压缩（`loca/core/context.py`）

- [x] **token 计数（按模型区分）**
  - [x] `TokenCounter` 抽象 + `HeuristicTokenCounter`（ASCII/CJK 双系数，按模型前缀选 profile）
  - [x] `TiktokenTokenCounter`：装了 `tiktoken` 就用真分词器，没装静默回退（不引入硬依赖）
  - [x] 默认系数与 Week 3 的估算器逐位一致，升级不会悄悄改变既有裁剪行为
- [x] **超出阈值时摘要早期消息**（替代直接丢弃）
  - [x] `provider_summarizer()`：用会话自己的 provider 做一次非流式 `chat()` 生成摘要
  - [x] 摘要以 `user` 消息承载（带 `[Earlier conversation summary]` 标记）—— 存成 `system` 会在回灌历史时被滤掉
  - [x] 摘要**钉在窗口里**，只对最近的消息做裁剪，避免大 tool 结果把它挤掉
  - [x] 摘要调用失败 → 降级为裁剪，绝不让压缩本身搞死这一轮
  - [x] `ContextManager.compact()` 支持手动触发（REPL `/compact`）
- [x] 新事件 `EventType.CONTEXT_SUMMARIZED`，CLI / Web UI 都有展示

### 交互

- [x] `loca chat --session <id>`（恢复或新建）· `--db` · `--no-save` · `--model` · `--keep-recent` · `--no-summarize`
- [x] `loca sessions [list|show|rm] [id]`：列表 / 完整对话 + 检查点清单 / 删除
- [x] REPL 命令：`/help` · `/compact` · `/session`
- [x] 每轮结束持久化（步数 + transcript 一起存）
- [x] Web UI 转发并渲染 `checkpoint` / `context_summarized`；`web/server.py` 的事件映射抽成可单测的 `_serialize_event()`
- [x] `.vscode/launch.json` 增至 9 个配置（新增 `loca chat --session (resume)`、`loca sessions (list)`）

### 测试

- [x] `tests/test_storage.py` 18 项：序列化往返、增删查改、级联删除、排序、标题推导、步数计数器跨重启
- [x] `tests/test_checkpoint.py` 20 项：文本/二进制/超限快照、沙箱拒绝、回滚语义（还原、删除、多步从新到旧）、最终状态汇总、循环集成
- [x] `tests/test_context.py` 25 项：模型 profile、与 Week 3 估算器一致性、摘要装配、降级路径、摘要保护、`compact()`、循环集成
- [x] `tests/test_cli.py` 新增 11 项：`sessions` 三个动作、`rollback`、REPL 命令、参数默认值
- [x] `tests/test_web_server.py` 新增 2 项：新事件的 SSE 映射
- [x] **真实 e2e**：`test_session_survives_a_restart` —— 起两个**独立进程**，第一个让它记住 4711，第二个问它数字是多少，答对才算过

**Week 4 验收标准**：关掉 CLI 重开能继续上次的任务。✅ 已达标（e2e 实测 + 手工两进程实测）

**测试统计**：`210 passed, 1 skipped`（离线）/ `8 passed`（联网）；合计 `218 passed, 1 skipped`；`ruff check .` 全绿。

> 设计取舍：
> 1. 会话库默认放 `~/.loca/sessions.db`（可用 `--db` / `$LOCA_DB` 覆盖），一个库装所有项目，每条会话记自己的 workspace —— 比在仓库里生成 `.loca/` 更干净，也不怕误提交。
> 2. transcript 用「整体重写」而非追加：上下文裁剪会让消息列表变短，追加式日志会和「模型实际看到的内容」漂移。
> 3. checkpoint 只覆盖文件工具。`shell` 能碰任何东西，为每条命令快照整个工作区不现实 —— 与其假装能撤销，不如在报告里明说。

---

## Week 5 — 可观测性 + 多 Provider ✅ 已完成

> `loca/observability/` 在 Week 4 建好（storage + checkpoint），Week 5 在其中补齐 `trace.py`（逐步轨迹）与 `reporter.py`（轨迹渲染），并把三家 provider 全部落地。

### Trace 模块（`loca/observability/trace.py`）

- [x] **每「模型步」一条轨迹**（`StepTrace`）—— prompt 摘要、回复文本、推理内容（`reasoning_content`）、工具调用、工具结果、token、耗时、`finish_reason`、重试次数、上下文动作（裁剪 / 摘要）、检查点
- [x] **`TraceRecorder` 作为事件 sink** 挂在 `AgentLoop` 的事件流上，循环签名只多一个可选 `recorder=`，核心逻辑零改动
  - [x] `STEP_START` 收尾上一步并开启新步；`DONE` 收尾最后一步；**`ERROR` 也立刻收尾** —— provider 抛错时循环直接 return、不会 yield `DONE`，不收尾就会丢掉出错那一步
  - [x] 工具耗时用 `(工具名, 起始时钟)` 的**列表队列**配对，而不是 `dict[工具名] = 时钟`（同一个工具连续调两次会被覆写）
- [x] **双写**：SQLite `traces` 表（`SCHEMA_VERSION` 1→2，用 `CREATE TABLE IF NOT EXISTS` 兼容旧库）+ JSONL 镜像
  - [x] JSONL 路径 `$LOCA_TRACE_DIR` 可覆盖，默认 `<会话库父目录>/traces/<session>.jsonl`
  - [x] 读 JSONL 时**跳过坏行**（写到一半中断不至于让整份轨迹打不开）
- [x] `SessionStore` 新增 `save_trace` / `list_traces` / `count_traces` / `delete_traces`；删会话时轨迹一并清理

### Reporter（`loca/observability/reporter.py`）

- [x] `summarize(steps)` → `TraceSummary`：步数、总 token、模型耗时、工具耗时、工具调用次数、工具错误数、错误率、失败步清单、重试次数、压缩次数、裁剪次数、涉及文件
- [x] `render()` Rich 表格：总览面板 + 每步一行；`--verbose` 展开 prompt / 回复 / 工具输出预览
- [x] `render_json()` 返回纯字符串（不接 console），`loca report --json` 可以直接管道给脚本
- [x] `gather()`：DB 优先、JSONL 兜底 —— 轨迹行被清过也不至于空手而归
- [x] 所有渲染都过 `rich.markup.escape` —— agent 输出里的 `[xxx]` 不会被 Rich 当成样式标签吞掉

### 交互

- [x] **`loca report [<session_id>]`** —— 不给 id 就报最近一条（提示语走 `stderr`，保证 `--json` 的输出干净可解析）；`--limit`（默认 0 = 全部）/ `--verbose` / `--json`
- [x] `loca chat --no-trace` 可整轮关掉轨迹；`TraceRecorder` 在 `finally` 里收尾「正在飞的那一步」
- [x] REPL 新增 `/trace` 命令
- [x] `loca sessions rm` 顺手报告一并删掉了多少条轨迹

### 多 Provider

- [x] **抽出 `OpenAICompatibleProvider`**（`providers/openai_compat.py`）—— DeepSeek 与 OpenAI 共用：payload 构造、响应解析、流式分片合并、`usage` / `finish_reason` 映射、工具参数 JSON 解析、`LOCA_<NAME>_BASE_URL` / `LOCA_<NAME>_MODEL` 覆盖
- [x] `DeepSeekProvider` / `OpenAIProvider` 收敛成三个类属性（`name` / `default_base_url` / `default_model`）
- [x] **Anthropic 完整实现**（`providers/anthropic.py`）—— 纯函数协议翻译层，不发网络请求就能测：
  - [x] `messages`：system 抽到顶层、`tool` 结果转 `tool_result` block、assistant 的 tool_call 转 `tool_use` block
  - [x] `tools`：JSON Schema → Anthropic `input_schema`
  - [x] 流式：`content_block_start` / `delta` / `stop` 翻译成统一的 `StreamChunk`，工具调用在 `content_block_stop` 才发完整调用
  - [x] `stop_reason` 映射（`tool_use` → `tool_calls`、`max_tokens` → `length`）；`cache_read_input_tokens` 计入 prompt token
  - [x] `build_payload` 始终带 `max_tokens`（Anthropic 必填）；`anthropic` SDK 懒导入，缺包时报 `pip install "loca[anthropic]"`
- [x] `pyproject.toml` 新增可选依赖 `anthropic = ["anthropic>=0.40"]`
- [x] registry 注释更新：三家都已实现，DeepSeek 仍为默认

### 测试

- [x] `tests/test_trace.py` **27 项**：每模型步一条记录（工具轮 = 2 步、纯回复 = 1 步）、出错步被收尾、工具耗时配对、双写位置解析、JSONL 坏行容错、清空
- [x] `tests/test_reporter.py` **25 项**：汇总数字、Rich 渲染与 markup 转义、JSON 输出、CLI 集成（默认取最近会话、缺会话时报错、`--limit`）
- [x] `tests/test_anthropic.py` **33 项**：消息 / 工具 / 流式翻译的纯函数测试（含缓存 token、缺 SDK 的报错文案）
- [x] `tests/test_provider_parity.py` **19 项**：同一任务在 DeepSeek / OpenAI / Anthropic 上产出一致（非流式、流式、工具调用、usage），外加 registry 解析
- [x] `test_cli.py` 新增 7 项、`test_storage.py` 新增 1 项覆盖新子命令与轨迹表
- [x] **真实 e2e 验收**：`loca chat --session w5-demo` 让 DeepSeek 真建了 `hello.py` 并运行；`loca report w5-demo` 普通 / `--verbose` / `--json` 三种输出逐一核对；JSONL 镜像对应落盘
- [x] `docs/traces-and-reports.md`（中文，新增）—— 会话和轨迹的区别、每步字段、双写位置、报告怎么读、FAQ

**Week 5 验收标准**：能跑真实 coding 任务并看完整 trace 报告。✅ 已达标（真实跑通并逐项核对输出）

**测试统计**：`ruff check .` 全绿；离线 `315 passed, 1 skipped`；联网 `8 passed`；合计 `323 passed, 1 skipped`。

> 设计取舍：
> 1. **轨迹按「模型步」而不是「用户轮」记**。一轮输入常常触发多次模型调用（先要工具、再给答复），按轮记会把最需要看的中间过程糊成一团。
> 2. **trace 与 checkpoint / rollback 共用同一个 `global_step`**。`STEP_START` 事件新增 `global_step` 字段，于是报告里的「第 3 步改了 `a.py`」可以直接抄成 `loca rollback <session> 3`，不必再换算出另一套编号。
> 3. **双写而不是二选一**。SQLite 便于查询和级联删除，JSONL 便于 `jq` 与跨库留存；两者由同一份 `StepTrace` 序列化而来，不会漂移。
> 4. **provider 分层而不是三家各写一套**。DeepSeek 走的本来就是 OpenAI 协议，硬拆两份只会让两边慢慢长歪；Anthropic 的差异（消息结构、工具格式、流式事件）大到值得单独一层，但那一层是纯函数，离线就能测。

---

## Week 6 — Benchmark + 报告 ✅ 已完成

- [x] **评估 harness**
  - [x] 任务定义格式：`task.json`（prompt + 难度 + tags + `timeout_s`/`max_steps` + `checks`）+ `workspace/`（起始工作区）+ `hidden/`（判分文件）+ `solution/`（参考答案）
  - [x] 三种判分方式：`pytest`（跑测试套件）/ `run`（比 stdout + 退出码）/ `script`（调任务自带的 `verify(workspace)`）
  - [x] 行为式判分，不看 diff —— 接受「另一种正确写法」
  - [x] `ThreadPoolExecutor` 并发跑 N 个任务；每次尝试独立沙箱 + 独立 provider 实例 + 独立会话 id
  - [x] `pass@1`（按尝试）与 `pass@k`（按任务）**分开算**，不混成一个成功率
  - [x] 七类 outcome 分开记：`passed` / `wrong_answer` / `max_steps` / `provider_error` / `timeout` / `crash` / `grader_error`
  - [x] `grader_error` 单独报警并标注「任务集的 bug，不是模型的失败」
  - [x] 协作式墙钟超时（在流式事件之间检查，而不是假装能掐断 HTTP 客户端）—— 如实写进模块文档
  - [x] 成本按「每个**通过**」算（`tokens/pass`、`steps/pass`），失败得便宜不算效率高
- [x] **自带 36 个 coding 任务**（`loca/eval/tasks/`）
  - [x] 简单 14 题：单文件 bug 修复（边界、可变默认参数、真值判断、整除、切片、递归基线、排序 key、去重保序…）+ 1 题实现小函数
  - [x] 中等 12 题：跨文件改动（补 import、改签名与调用点、搬模块、加校验层、加 CLI flag、插件注册表、日志解析、重试助手、分页边界…）
  - [x] 困难 10 题：算法实现（LRU、拓扑排序、CSV 行解析、罗马数字、表达式求值、合并区间、单词折行、JSON Pointer、Dijkstra、滑动窗口限流）
  - [x] 每题都带 `solution/` 参考答案，用来证明「这题做得出来」
  - [x] **任务集自检** `loca bench verify`：逐题确认「起始工作区判不过 + 参考答案判得过」→ 36/36 全过
- [x] **对比报告**
  - [x] 真实跑分：DeepSeek 默认模型 × 36 题 × 1 次 × 4 并发 → **pass@1 = 91.7%（33/36）**
  - [x] 按难度分解：simple 92.9% / medium 100% / hard 80.0%
  - [x] token 消耗 399,218（11,120 tokens/通过）、5.27 步/通过、墙钟 67 秒
  - [x] 三个失败案例逐个归因（见 `docs/benchmark.md` 第 6 节）
  - [x] `--compare a,b` 支持多 provider 并排（Anthropic 需要一个 key 才能实跑，本次未跑）
  - [x] Rich 表格 + `--json` 双输出；`--out` 落盘（原始报告入库 `docs/benchmarks/deepseek-36.json`）
- [x] **文档 + 博客**
  - [x] `docs/benchmark.md`（中文）—— 任务格式、判分为什么可信（`hidden/` 防作弊 + 行为式判分 + 任务集自检 + 失败分类）、命令用法、报告字段、真实跑分与失败归因、怎么加新题、已知限制、FAQ
  - [x] `docs/blog-benchmarking-a-coding-agent.md`（中文，约 1,900 字）—— 四个设计陷阱 + 真实数字 + 「三个失败都不是算法问题」的复盘
  - [x] README 补 Week 6、跑分表格、`loca bench` 命令、新文档入口（中英双语）
  - [x] `docs/resume-project-description.md` 更新 Week 6 部分
- [x] **测试**
  - [x] `tests/test_eval_tasks.py` **51 项**：加载与校验（缺字段 / 难度非法 / 坏 JSON / 重复 id / checks 缺 kind）、沙箱生命周期（seed 不含 hidden、`restore_hidden` 覆盖模型改过的判分文件）、三种判分方式的全部分支、`verify_task_set`（良构 / 起始就通过 / 无解 / 无参考答案 / 判分器崩 / 清理 / `--keep`）、真实题目端到端
  - [x] `tests/test_benchmark.py` **31 项**：`run_attempt` 七类 outcome 全覆盖、trace 与 session 落库、防作弊（模型改判分文件无效）、`run_benchmark` 聚合 / pass@1 vs pass@k / 难度分组 / 失败计数 / grader fault / 空选集报错 / 进度回调 / 沙箱清理与保留、报告渲染（JSON 形状、markup 转义、通过率、broken grader 警告、verbose、对比表）
  - [x] 新增一条回归测试：**「自带任务的 seed 不能等于参考答案」** —— 防止将来某次手滑把答案写回工作区，让题目悄悄失效

**Week 6 验收**：能在 30 个任务上跑出 pass@1 报告，并写出可发布的博客。✅ 已达标（36 题、pass@1 = 91.7%、博客约 1,900 字）

**测试统计**：`ruff check .` 全绿；离线 `397 passed, 1 skipped`（398 收集）；联网 `8 passed`；合计 `405 passed, 1 skipped`（406 收集）。

> 设计取舍：
> 1. **判分文件藏起来、判分前再盖回去**。模型看不到断言（只能从 prompt 推理真实需求），而且把测试改成 `pass` 也没用。一个测试专门钉住这条性质 —— 这是整套评测的信任基础。
> 2. **判行为不判 diff**。diff 判分测的是「模型能不能猜到我脑子里那份答案」，不是「能不能解决问题」。代价是任务作者要写得出判据，收益是「另一种正确写法」也能拿分。
> 3. **任务集自己先体检**。`loca bench verify` 不需要 provider、不花 token，却能挡住两种最隐蔽的坏题：起始就通过的题（等于没测）和参考解都过不了的题（报的全是噪音）。
> 4. **失败分七类**。把 harness 的异常（`crash`）和出题人的错误（`grader_error`）单独拿出来，才不会让它们混进「模型不行」的统计里。
> 5. **pass@1 与 pass@k 分开**。`pass@1` 低但 `pass@k` 高 = 题能做但模型不稳（该加采样/重试）；两个都低 = 能力问题（重试没用）。混成一个数字就分不出来了。

---

## 本次会话变更日志

### 2026-09-18 — 提交推送：Week 4-6 的改动按 5 批提交并推送到 GitHub

用户指令：「就这样先commit项目上去，按照你认为合理的节奏来commit就行」。

**为什么不能按周拆**：这不是「新写的代码按周提交」，而是把已经堆在工作区的四批改动
（Week 4 / Windows-only / Week 5 / Week 6）**事后**整理成提交历史。而 `loca/cli.py`
（+801 行，含 sessions / rollback / report / bench 四个新命令）、`loca/core/loop.py`
（+136 行）、`README.md`、`loca_roadmap.md` 这几个文件**同时承载多批改动**。
git 按文件快照提交，拆不开 —— 强行拆就得手工构造中间态，那不是真实历史。

**最终 5 批**（按依赖自下而上，每批的文件边界自洽）：

| # | commit | 主题 | 文件数 |
|---|---|---|---|
| 1 | `9a6483c` | observability：会话存储 / 检查点 / 上下文压缩 / 轨迹 | 16 |
| 2 | `24c0a50` | providers：OpenAI 兼容层 + 真实 OpenAI / Anthropic | 9 |
| 3 | `b65a65d` | eval：36 题评测集 + 并发 runner + 报告 | 174 |
| 4 | `dbbf17c` | cli：四个新子命令接线 + Windows-only shell 改名 | 11 |
| 5 | `f0571af` | docs：README / 路线图 / 审查报告 / 面试手册 | 8 |

**验证**：
- HEAD 全绿 —— 因为 `worktree == HEAD`，测工作区就等于测 HEAD：`ruff` rc=0，
  `pytest -m "not live"` → **397 passed, 1 skipped**（8 项 live 未选）
- 任务集全部入库：165 文件 / 36 个 `task.json` / 36 个 hidden 判分器 / 41 个参考答案
- 历史里**没有** `.env` / `.venv/` / `.workbuddy/` / `.loca/`
- 推送成功以**服务端事实**为准：`git ls-remote --heads origin` 返回 `f0571af`，与本地 HEAD 一致

**踩到的坑（已写进记忆）**：
1. 推送必须显式走本机代理 `127.0.0.1:7897`（`-c http.proxy=…`，且要在沙箱外执行）——
   沙箱注入的代理连不上 GitHub（`CONNECT tunnel failed, response 502`），去掉代理直连又超时
2. `PortableGit\…\etc\gitconfig.lock` 每次网络操作都会被留下（0 字节），
   导致下一次操作报 `could not lock config file`
3. push 后 `refs/remotes/origin/main` 会消失（`status -sb` 显示 `[gone]`），
   需要 `git fetch origin --prune` 重建 —— 但远端其实已经更新了

**未做**：审查报告里的 P1/P2 **一个都没修** —— 本轮只提交，不改代码。

### 2026-09-18 — 全项目审查：167 个勾选项逐条对代码 + 12 项缺陷（含 3 个 P1）

用户指令：「现在请你进行整个项目的审查，根据计划书来，最后写入对应报告中」。

完整报告见 **[`docs/project-audit.md`](docs/project-audit.md)**（九节，含复现脚本清单）。
这里只记结论。

**审查结论**：6 周目标全部真实达成，**167 个勾选项约 155 条在代码里逐条成立（92.7%）**，
12 条属于「声明成立、边界不成立」或「描述已过时」。**没有一个勾选项是空的。**

**验证方式（全部本机实测，不是推断）**

| 项 | 结果 |
|---|---|
| `ruff check .` | rc=0，All checks passed |
| `pytest -m "not live"` | 398 收集 → **397 passed, 1 skipped** |
| `pytest -m "live"` | **8 passed** |
| `loca bench verify` | **all 36 task(s) check out**（25.6s） |
| `loca --help` | 8 个文档化子命令全部存在 |
| 跑分证据复算 | pass@1 = 0.9167、33/36、399,218 tok、66.9s、255.94s —— **与文档逐位一致** |

**跑分归因逐字复核**（这是本次最看重的一项）：
`impl-expression-evaluator` 实际是 `1 failed, 15 passed`（文档写「16 条过 15 条」✓）；
`impl-word-wrap` 实际是 `9 failed, 2 passed`（文档写「11 条只过 2 条」✓，且 `steps: 4` ✓）；
`fix-recursion-base-case` 失败用例正是 `test_negative_is_rejected` 的 `DID NOT RAISE ValueError` ✓。
**三名失败的叙述与判分器原始输出完全对得上。**

**发现的 3 个 P1 缺陷**（均已在报告里复现，且都不影响已归档的跑分）

1. **`shell` 的超时不是上限** —— `timeout=2s` 的命令实测跑了 **8.09 秒**。
   `shell=True` 下超时只杀 `cmd.exe`，孙进程仍持有管道写端，`communicate()` 必须等它退出。
   一条 `timeout=30` 的 `pytest` 能把整个会话挂住。
2. **`_shell_executable()` 的回退值是裸 `"cmd.exe"`** —— 把 `%COMSPEC%` 指向 PowerShell 后，
   用它执行命令得到 `FileNotFoundError: [WinError 2]`。`CreateProcess` 的 lpApplicationName
   是相对路径时不搜索 PATH。**这段代码存在的唯一目的就是防这个场景，而它在这个场景下是坏的。**
   测试只断言返回的字符串，从不真的跑一条命令。
3. **回滚遇到「同一步内多次改动同一文件」会还原成中间版本** —— 同一步三次 `write_file`
   （v1→v2→v3）后 `rollback(sid, 1)`，文件应被**删除**（它在该步内才创建），实际留下 `'v2'`。
   根因：`rows.sort(key=lambda r: r.step, reverse=True)` 只按 `step` 排序，同一步内靠稳定排序
   保留了「最旧优先」，与 docstring 承诺的语义正好相反。报告同时列出
   `restored=['f.txt','f.txt'] deleted=['f.txt']` 三种矛盾动作。

**另有 12 条 P2 + 11 条 P3**，摘要：
`read_file` 无总量上限（实测 5,000 行返回 290,202 字符）、`edit_file` 把整个文件 LF 改写成 CRLF、
OpenAI 流式不请求 usage 导致 token 恒 0、`finish_reason=None` 被映射成 `ERROR`、
超时路径绕过截断、一条合法标量 JSONL 会让 `loca report` 崩溃、
任务集自检把「没有参考答案」判为合格、**归档报告 `"model": null`（证据文件无法自证模型）**。

**目录数字口径问题**：简历/README 的「评测集 128 个文件 / 5,994 行」实测 = 124 个夹具 `.py`
+ **4 个生成脚本**；5,994 = 2,510 + **3,484**。该数字**排除了 36 个 `task.json`（含题面）**，
而 **58% 是生成脚本**。真实夹具规模是 **161 文件 / 3,103 行**。已写进报告建议改口径。

**计划书更正**：Week 1 第 5 条（`NotImplementedError` stub）已加注「Week 5 已取代」；
Week 4「会话库可跨机器迁移」的卖点未完全兑现（`rollback` 不传 `--workspace` 时仍用
录制时的绝对路径），已在报告里列为限制。

**新增文档**：`docs/project-audit.md`。
**新增脚本**（`.workbuddy/scratch/`，gitignored）：`audit_inventory.py` · `audit_numbers.py` ·
`audit_repro.py` · `audit_f6.py` · `audit_final.py` · `audit_round2.py`。

**未做**：**没有修任何缺陷**（本次只审查）。修复顺序建议见报告第 7 节。
**git 仍未提交**（用户明确要求先不交）。

### 2026-09-18 — Week 6 完成：36 题评测集 + 真实跑分 + 博客

用户指令：「请继续完成 week6 的内容，并根据需要修改简历描述」。Week 6 范围 = 评估 harness + 自带任务集 + 对比报告 + 文档与博客。

**新增三个模块**

| 文件 | 职责 |
|---|---|
| `loca/eval/tasks.py` | 任务模型（`EvalTask` / `TaskSet` / `TaskError` / `CheckResult`）、加载与校验、三种判分方式（`pytest` / `run` / `script`）、沙箱生命周期 |
| `loca/eval/benchmark.py` | `run_attempt()` / `run_benchmark()`（线程池并发）、七类 outcome 分类、`BenchmarkReport` 聚合（pass@1 / pass@k / 难度分解 / 成本）、`compare()`、`verify_task_set()` 任务集自检 |
| `loca/eval/report.py` | `render()` / `render_json()` / `render_comparison()` —— Rich 表格与 JSON 双输出，全部过 `rich.markup.escape` |

**新增 36 道任务**（`loca/eval/tasks/<id>/`）：14 简单 + 12 中等 + 10 困难，每题含 `workspace/`（埋着缺陷）、`hidden/`（判分文件）、`solution/`（参考答案）、`task.json`。生成脚本归位到 `loca/eval/tasks/_generate/`（`load_tasks` 按设计跳过 `_` 前缀目录，ruff 也排除了整个 `tasks/` 树）。

**改动的既有文件**：`cli.py`（`bench` 子命令：`list` / `run` / `verify`，含 `--compare` 多 provider 对比）、`eval/__init__.py`（导出全部公共符号）、`observability/storage.py`（WAL 后加 `PRAGMA busy_timeout = 5000`，多线程写会话库不再撞 `database is locked`）、`pyproject.toml`（ruff `extend-exclude = ["loca/eval/tasks"]` —— 任务是**夹具代码**，里面故意留着可变默认参数、未用变量、错比较，lint 它们等于在最该报错的地方把报错关掉）。

**过程中发现并修掉的真实问题**

1. **`ContextManager` 少传 `budget`** —— `run_attempt()` 里构造 `ContextManager(model=…, summarizer=…)` 时漏了必填的关键字参数 `budget`，导致**只要传了 `store_path` 就必然 `TypeError`**，被兜底成 `crash`。这个 bug 是"带会话落库跑一遍评测"这条路完全走不通，而默认参数下测不出来。修法是补齐 `budget` / `keep_recent`，并把「上下文预算」和「是否持久化」拆开 —— 预算应该像 `loca chat` 一样独立于 `--no-save`，否则评测测的是一个没人会用的配置。
2. **`save_transcript` 断言会话必须先存在** —— 评测的会话 id 是自动生成的（`bench-<task>-a<N>`），从没走过 `ensure_session()`，于是第一次存对话就 `AssertionError: session … vanished mid-save`。修法是在建有 store 时先 `ensure_session()`，与 CLI 的做法对齐。
3. **`restore_hidden` 覆盖语义被写错成断言** —— 单元测试里让模型"改判分文件"再判分，验证覆盖确实发生。
4. **验收测试发现了自己的写题漏洞** —— 任务集自检 `loca bench verify` 36/36 通过；但在生成阶段人工核对时抓出两处**判分比题面严格**的问题：JSON Pointer 题要求拒绝前导零、罗马数字题要求拒绝小写，而两处 `prompt` 里都没写这条要求。这类题会把"模型猜不到"算成"模型答错了"，已补进题面。
5. **回归防护**：新增一条测试断言「自带任务的 seed 内容不能等于参考答案」。这是为了防我自己 —— 如果将来某次手滑把答案写回 `workspace/`，题目会**静默失效**（不做也能满分），而所有其它测试都还是绿的。

**真实跑分（2026-09-18，DeepSeek 默认模型，36 题 × 1 次 × 4 并发）**

| 难度 | 题量 | 通过 | 通过率 | tokens/通过 | 步数/通过 |
|---|---:|---:|---:|---:|---:|
| simple | 14 | 13 | 92.9% | 8,071 | 4.9 |
| medium | 12 | 12 | 100% | 12,591 | 5.7 |
| hard | 10 | 8 | 80.0% | 17,901 | 7.1 |
| **合计** | **36** | **33** | **91.7%** | **11,120** | **5.3** |

整轮 399,218 tokens、墙钟 67 秒（累计 256 秒）。三个失败**没有一个是算法写不出来**：`fix-recursion-base-case`（simple）漏了负数入参的 `ValueError`、`impl-expression-evaluator`（hard）漏拒 `1++2`、`impl-word-wrap`（hard）返回字符串而非「行的列表」。全是**题面写明但没逐条落实的边界与返回类型契约** —— 这是本周最有价值的发现，也直接指向下一步该在 harness 层做什么。原始报告入库 `docs/benchmarks/deepseek-36.json`。

**测试统计**：`ruff check .` 全绿；离线 `397 passed, 1 skipped`（398 收集）；联网 `8 passed`；合计 `405 passed, 1 skipped`（406 收集）。
新增 `test_eval_tasks.py`(51) + `test_benchmark.py`(31) = **82 项**。

**新增文档**：`docs/benchmark.md`（中文）—— 任务格式、判分为什么可信、命令用法、报告字段、真实跑分与失败归因、怎么加新题、已知限制、FAQ；`docs/blog-benchmarking-a-coding-agent.md`（中文，约 1,900 字）—— 四个设计陷阱 + 真实数字 + 复盘。README 中英两侧同步。

**未做**：**git 仍未提交**（用户明确要求先不交）。工作区现在堆着 Week 4 + Windows-only + 改名 + Week 5 + Week 6 五批改动。

### 2026-09-12 — Week 5 完成：Trace + Reporter + 三 Provider 全部落地

用户指令：「现在请你继续往下做 week5，别忘了写日志」。Week 5 范围 = 可观测性（逐步骤轨迹 + 报告）+ Anthropic/OpenAI 完整实现。

**新增三个模块**

| 文件 | 职责 |
|---|---|
| `loca/observability/trace.py` | `TraceRecorder`（事件 sink）+ `StepTrace`：每模型步一条轨迹，双写 SQLite + JSONL |
| `loca/observability/reporter.py` | `summarize()` / `render()` / `render_json()` / `gather()`：把轨迹渲染成总览表或 JSON |
| `loca/providers/openai_compat.py` | `OpenAICompatibleProvider`：DeepSeek / OpenAI 共用的协议实现 |

**重写的文件**：`providers/anthropic.py`（从 stub 变成完整的纯函数协议翻译层）、`providers/deepseek.py` 与 `providers/openai.py`（收敛成三个类属性）。

**改动的既有文件**：`observability/storage.py`（`SCHEMA_VERSION` 1→2 + `traces` 表 + 四个新方法）、`observability/__init__.py`（导出新 API）、`core/loop.py`（`STEP_START` 事件补 `global_step`）、`core/events.py`（事件字段文档）、`cli.py`（`report` 子命令 + `--no-trace` + `/trace` + 删会话时报告轨迹数）、`pyproject.toml`（`anthropic` 可选依赖）。

**过程中发现并修掉的真实问题**

1. **`_call_started` 用错了容器** —— 初版声明成 `dict[str, float]` 却对它 `.append(...)`，直接 `AttributeError`。改成 `list[tuple[str, float]]`：同一个工具连续调两次时，字典会把第一次的起始时钟覆写掉，配出来的耗时是错的。
2. **出错的那一步永远不会被收尾** —— `_finalize()` 原本只在下一次 `STEP_START` 或 `DONE` 时触发，但 provider 抛异常时循环直接 `return`，不会 yield `DONE`。于是「模型调用失败」这一步在报告里凭空消失 —— 而这恰恰是最该看的一步。改成 `ERROR` 事件也立刻收尾。
3. **`render_json` 签名与调用方不一致** —— 定义成 `render_json(data, console)` 但 CLI 按 `render_json(data)` 调。改为纯返回字符串，`--json` 也不走 Rich console，保证管道输出干净。
4. **Rich 把 agent 的输出当成了样式标签** —— agent 回复里出现 `[user]` 之类的方括号，Rich 会当成 markup 去解析并吞掉。所有渲染路径统一过 `rich.markup.escape`。
5. **`list_sessions` 在同秒创建时排序颠倒** —— 原本 `ORDER BY updated_at DESC, session_id DESC`，而自动 id 是「时间戳 + 随机后缀」，同一秒内建的会话谁排前面全看随机后缀，于是「最近会话」可能指到旧的那条。改用 `rowid DESC`（即插入顺序），`loca report` 不带 id 时的默认目标才是对的。
6. **registry 测试直接 `import anthropic` 会挂** —— 环境里没装 anthropic SDK。加了一个注入 stub 模块的 fixture，另补一项测试验证「缺包时报的错必须提示 `pip install "loca[anthropic]"`」—— 报错文案也是给人用的接口。

**测试统计**：`ruff check .` 全绿；离线 `315 passed, 1 skipped`（共 316 项收集）；联网 `8 passed`；合计 `323 passed, 1 skipped`（共 324 项）。
新增 `test_trace.py`(27) + `test_reporter.py`(25) + `test_anthropic.py`(33) + `test_provider_parity.py`(19) = 104 项，另 `test_cli.py` +7、`test_storage.py` +1。

**验证方式（不只跑单测）**：起真实 CLI 让 DeepSeek 建了个 `hello.py` 并执行，然后 `loca report <session>` 三种形态逐一核对 —— 普通表格、`--verbose` 展开、`--json` 管道；确认总览里的 token / 工具调用数 / 涉及文件与 JSONL 镜像（`traces/<session>.jsonl`，2 行）一致。验收后清掉临时目录与库。

**新增文档**：`docs/traces-and-reports.md`（中文）—— 会话和轨迹的区别、每个模型步记了哪些字段、轨迹双写在哪、`loca report` 的输出怎么读、token 与耗时怎么算、限制与 FAQ。README 中英两侧同步：Week 5 勾选、测试数更新、目录结构、CLI 命令表（`report` / `--no-trace`）、文档链接。

**未做**：**git 未提交**（用户明确要求先不交）。当前工作区堆着 Week 4 + Windows-only + 改名 + Week 5 四批改动。

### 2026-09-12 — `bash` → `shell` 改名 + 移除 tenacity

用户拍板：git 先不提交，另外两个悬而未决的问题直接改掉。

**1. 工具改名：`bash` → `shell`（含模块与类名）**

Windows 上跑的是 cmd.exe，却把工具叫 `bash`，等于让模型和读者同时被名字骗一次。既然平台已经明确，名字就该诚实。

- `loca/tools/bash.py` → **`loca/tools/shell.py`**
- `BashTool` → **`ShellTool`**，`Tool.name` 从 `"bash"` 改为 **`"shell"`**
- 转录标签同步：`<bash command=...>` → **`<shell command=...>`**
- 注册入口 `register_default_tools()` 同步（`loca/tools/__init__.py`）
- 顺带清掉引用点：`cli.py` 回滚提示语「shell tool cannot be rolled back」、`observability/checkpoint.py` 模块注释、`tools/registry.py` 注释
- 测试：`tests/test_bash.py` → **`tests/test_shell.py`**；`test_e2e_agent.py` 的两个真实 e2e 改成「Use the **shell** tool …」并断言 `name == "shell"`；`test_deepseek_stream.py` / `test_context.py` / `test_checkpoint.py` / `test_cli.py` 里的示例数据一并改名（含把示例命令 `ls` 换成 `dir`）
- 新增一项 `test_tool_is_named_shell_not_bash`，把这个决定钉住
- 文档：README（中英）的工具清单、`docs/sessions-and-rollback.md`、`docs/running-the-web-gui.md` 同步

> 影响面提醒：**旧会话数据库里的检查点记录仍写着 `bash`**。回滚逻辑只按「工具名 → 参数名」映射找 `write_file` / `edit_file`，shell 从来不在追踪名单里，所以旧数据不受影响。

**2. 移除 `tenacity` 依赖**

重试早就换成自研退避（`core/recovery.py`），`tenacity` 在整个仓库里**零 import**，却在 `pyproject.toml` 里挂着「留给 Week 5 限流用」的名头。没人用的依赖只会让依赖清单说谎 —— 删掉。Week 5 真要做限流，按需再加，那时才知道需要哪个 API。

**测试统计**：`ruff` 全绿；离线 `210 passed, 1 skipped`；联网 `8 passed`；合计 `218 passed, 1 skipped`。
其中联网 e2e 是**实打实验证了改名**：模型拿到名为 `shell` 的工具，照样正确调用并把 `echo hello` 的输出引用回来。

### 2026-09-11（第七次）— 明确「只用 Windows + cmd」，清掉多环境分支

用户拍板：环境一定是 Windows 路径，不做多环境支持，只用 Windows 的 cmd。据此把代码、提示词、测试、文档统一到 Windows 假设。

- **`loca/tools/bash.py`**
  - 模块 docstring 明写「Windows only，没有 POSIX/macOS 分支」。
  - 工具描述从 `POSIX sh on Unix, cmd.exe on Windows` 改成「跑 Windows cmd.exe，用 `dir`/`type`/`del`/`findstr` 和 Windows 路径，`ls`/`cat`/`rm` 不可用」。
  - `subprocess.run(..., shell=True)` 增补 `executable=_shell_executable()`：只有 `%COMSPEC%` 的 basename 是 `cmd` 才用它，否则回退 PATH 上的 `cmd.exe`。这样别人把 COMSPEC 指到 PowerShell / Git-Bash，也不会偷偷改变「模型该写什么命令」这件事。
  - 新增 `_format_command()`：转录头改用 cmd 引号风格（整行双引号、内部引号翻倍），替换掉 POSIX 的 `shlex.quote`（原输出 `'dir /b'` 这种单引号在 cmd 语境下是错的）。
- **`loca/core/loop.py`** — 默认系统提示词写明「running on Windows + 路径是 Windows 路径 + shell 是 cmd.exe，用 dir/type/del/findstr 而不是 ls/cat/rm/grep」。这是让模型不拿 POSIX 命令撞墙的关键一步。
- **`loca/cli.py`** — 新增 `resolve_workspace()`：`^/[A-Za-z](/|$)` 形态的 `--workspace`（如 `/d/repo`）直接报错并给出 `D:\repo` 建议。`chat` 与 `rollback` 都走它。理由：`ntpath` 把这类路径当**盘符相对路径**，静默解析成 `D:\d\repo` 空目录 —— 不报错但结果全错。`--workspace` 的帮助文本也改为 Windows 路径口径。
- **`tests/test_bash.py`** — 删掉所有 `sys.platform == "win32"` 分支，测试直接按 cmd.exe 写（`rem` 替 `true`、`cd` 替 `pwd`）；新增 4 项：转录头双引号格式、`_format_command` 引号翻倍、`_shell_executable` 对 PowerShell COMSPEC 的免疫、Windows 绝对路径 `C:\Windows\System32` 仍被沙箱拒绝。抽出 `_python()` 帮手统一构造一行式命令。
- **`tests/test_cli.py`** — 新增 4 项 `resolve_workspace` 测试（接受 `tmp_path`、拒绝 `/d/repo` 且提示 `D:\repo`、拒绝裸 `/c`、放行 `dev/null` 这类普通相对名）。
- **文档**：`README.md` 中英各加「运行环境 / Requirements」小节（平台、Shell、路径、Python 四项约定 + 盘符相对路径的坑），快速开始的命令块从 bash 语法改成 cmd 语法；`docs/running-the-cli.md` 第五节补「`--workspace` 只能写 Windows 路径」+ FAQ 一行；`docs/sessions-and-rollback.md` 的 system 样例消息同步。
- **测试统计**：离线 `202` → **`210 passed, 1 skipped`**（新增 8 项），联网 `8 passed` 不变；合计 `218 passed, 1 skipped`。

> 当时留了一笔：`BashTool.name` 仍叫 `bash`，实际跑的是 cmd.exe。**2026-09-12 已改名**（`ShellTool` / `shell`，模块 `loca/tools/shell.py`），见下一条变更日志。

### 2026-09-11（第六次）— Week 4 完成：Session 持久化 + Checkpoint + 摘要压缩

**新增三个模块**

| 文件 | 职责 |
|---|---|
| `loca/observability/storage.py` | `SessionStore`：SQLite 存会话、transcript、检查点；`Message` ↔ 行 序列化 |
| `loca/observability/checkpoint.py` | `CheckpointManager`：工具执行前快照文件，`rollback()` 按 step 还原 |
| `loca/core/context.py` | `TokenCounter`（tiktoken 可选）+ `ContextManager`（超预算时摘要早期消息） |

**改动的既有文件**：`core/loop.py`（接两个 manager、推进会话级步数、发 `CHECKPOINT` / `CONTEXT_SUMMARIZED` 事件）、`core/events.py`（两个新事件类型）、`cli.py`（4 个新参数 + 3 个子命令路径 + 3 个 REPL 命令 + 每轮持久化）、`web/server.py`（事件映射抽成 `_serialize_event()` 并补两个新事件）、`web/index.html`（渲染新事件）、`observability/__init__.py`（导出公共 API）。

**过程中发现并修掉的真实问题**

1. **步数计数器重启归零** —— 手工两进程实测时发现：`ctx.step_index` 是进程内的，第二次启动又从 0 开始，于是第 2 步的检查点和第 0 步撞号，`rollback <step>` 的目标就有歧义。改成把计数器存进会话 metadata（`next_step`），启动时读回来。
2. **`web/server.py` 的事件映射是一长串 if/elif** —— 加事件只能往里塞分支，且只能靠端到端测试覆盖。抽成模块级 `_serialize_event()`，可直接单测。
3. **回滚报告会重复提及同一文件** —— 一个文件被改两次时，输出「restored a.py」紧跟「deleted a.py」，看的人会懵。新增 `RollbackReport.settled()`，按文件汇总**最终状态**。

**踩坑记录（都是测试/命令写法问题，非产品缺陷）**

- Windows 上 `write_text("x\n")` 会把 `\n` 写成 `\r\n`，测试断言必须比对 `read_bytes()`，否则快照字节数对不上。
- `pytest` 里 `cmd | head -N` 会让 Python 进程收到 SIGPIPE 而提前退出，那一轮的持久化不会执行 —— 排查时误以为是持久化 bug，其实是管道截断。

**验证方式（不只跑单测）**

- 起**两个独立进程**跑真实模型：进程 A 让它建 `hello.py`（内容 `print("v1")`），进程 B 用 `--session demo` 恢复，确认它看得到上一轮的对话与文件，并成功改成 `print("v2")`。
- `loca rollback demo 2` → 文件回到 `print("v1")`；`loca rollback demo 0` → 文件被**删除**（因为它本来就是这次会话新建的），与预期一致。
- `loca sessions` / `loca sessions show demo` 的输出逐项核对（标题自动取自首条用户消息、检查点清单带 step 号）。
- `pytest -m "not live"` → 210 passed, 1 skipped；`pytest -m live` → 8 passed；`ruff check .` → 全绿。

**新增文档**：`docs/sessions-and-rollback.md`（中文，8 节）—— 会话库在哪、怎么恢复、`rollback` 的三条规则与四项限制、摘要压缩怎么工作、FAQ、一页速查。

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

**推送**（用户提供远端 `https://github.com/Wang-Yi-666/loca`）：

- 远端建仓时勾了 README，已有一笔 `0ed776a Initial commit` + `014b7f7 Update README.md`。**没有用强推**。
- 把用户 README 里那句描述（"统一 DeepSeek / Anthropic / OpenAI 的 tool-use 协议，提供可观测的执行循环与错误恢复"）**原样并入**本仓库 README 开头，措辞保留。
- 用 cherry-pick 把我们的提交重放到远端之上，解决 README 的 add/add 冲突（保留我们的版本）。结果历史线性：
  ```
  b2549f3  feat: initial commit — loca, a coding agent harness built from scratch
  014b7f7  Update README.md     ← 用户原有
  0ed776a  Initial commit       ← GitHub 建仓时
  ```
- **关键验证**：变基前后 `git rev-parse HEAD^{tree}` 相同（`a036eaba…`），证明**一个字节都没丢也没多加**。
- 推送成功：`014b7f7..b2549f3 main -> main`（快进，无 `--force`）。本地 HEAD == 远端 `refs/heads/main`。
- 安全兜底：打了一个 tag `backup-pre-sync` 指向变基前的提交 `235b419`。

**踩到的坑（值得记）**：

1. **工具沙箱会静默拦掉 git 建 ref**。症状极隐蔽：`git update-ref refs/remotes/origin/main <sha>` 返回 `rc=0`，但文件根本没落盘；同理 `refs/heads/backup/…` 这类需要**新建父目录**的 ref 也建不上。表现是 `git status` 显示 `## main...origin/main [gone]`、备份分支"创建成功"却不存在。
   排查结论：同一 D 盘仓库、同一 git，**取消沙箱后**在 C: / D: / 新旧仓库、两套 git（PortableGit 2.55、GitHub Desktop 2.53）下建各类 ref **全部成功**。所以**不是机器或仓库的问题**，是沙箱副作用。
   绕过：手工按 loose-ref 格式写 `.git/refs/remotes/origin/main`（内容 ` <sha>\n`）与 `HEAD`（内容 `ref: refs/remotes/origin/main\n`），git 立刻认。
2. **PortableGit 的 stale lock**：`…\PortableGit\versions\1.2.0\etc\gitconfig.lock`（0 字节）残留，导致首次 push 报 `could not lock config file … gitconfig: File exists`。删掉后正常。
3. 首次 push 在禁用交互时失败（无缓存凭据）；**允许交互后一次成功** —— 凭据走 Git Credential Manager，用户无需手动输密码。

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
