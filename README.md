# Loca

一个轻量级的 coding agent harness：统一 DeepSeek / Anthropic / OpenAI 的 tool-use 协议，
提供可观测的执行循环与错误恢复。参考 pi-coding、opencode 与 DeepSeek 官方 harness 实现。

A lightweight coding agent harness that unifies the tool-use protocol across
DeepSeek / Anthropic / OpenAI, with an observable execution loop and error
recovery. Inspired by pi-coding, opencode, and the DeepSeek reference harness.

**语言 / Language：** [中文](#中文文档) · [English](#english)

---

# 中文文档

## 为什么再造一个 harness？

大多数 agent 项目只是把提示词贴到 LLM SDK 上就收工了。真正的 coding agent，95% 的复杂度都在 harness 这一层：

- 跨厂商统一的工具调用协议（DeepSeek / OpenAI / Anthropic）。
- 一个能在工具失败、模型输出跑偏时依然活下去的流式执行循环。
- 经过 JSON Schema 校验的工具调用，模型没法把 agent 弄崩。
- 可观测性：每一步都可追踪，方便事后调试和评测。

Loca 刻意把体量压小 —— 不用 LangChain，不用 LlamaIndex，没有隐藏框架。真正重要的每一行都在 `loca/` 里。

## 目录结构

```
loca/
├── cli.py        # `loca chat` / `sessions` / `rollback` / `report` / `serve` / `tools` / `providers`
├── providers/    # 厂商中立的 LLM 接口 + DeepSeek/OpenAI/Anthropic 实现
├── tools/        # 工具协议 + read_file/write_file/edit_file/shell + 注册表
├── core/         # 执行循环、事件、错误恢复、上下文压缩
├── observability/# 会话持久化（SQLite）+ 文件检查点与回滚 + 执行轨迹与报告
└── eval/         # Benchmark：自带 36 个任务的任务集 + 并发评测 + 报告渲染

web/              # FastAPI + SSE 服务端与单页聊天 UI
scripts/          # 薄启动器（interactive_chat.py → `loca chat`）
docs/             # 使用指南（CLI、Web GUI、会话与回滚、轨迹与报告、评测集）
tests/            # 离线单测 + 真实 DeepSeek e2e（无 key 自动跳过）
```

## 进度

本项目作为 agent 工程方向实习的作品集，按周推进。实时清单见
[`loca_roadmap.md`](loca_roadmap.md)。

- [x] Week 1 —— Provider 抽象层 + DeepSeek 流式
- [x] Week 2 —— 工具协议 + 文件系统 / shell（4 个工具）+ Web UI
- [x] Week 3 —— 执行循环 + 错误恢复 + 上下文预算
- [x] Week 4 —— Session 持久化 + Checkpoint + 摘要式上下文压缩
- [x] Week 5 —— 可观测性（Trace + Report）+ Anthropic/OpenAI 接入
- [x] Week 6 —— Benchmark（36 个自带任务）+ 真实跑分报告 + 技术博客

## 跑分（真实数据）

DeepSeek 默认模型、36 个自带任务、每题 1 次、4 并发 —— **pass@1 = 91.7%（33/36）**：

| 难度 | 题量 | 通过 | 通过率 | tokens/通过 | 步数/通过 |
|---|---:|---:|---:|---:|---:|
| simple | 14 | 13 | 92.9% | 8,071 | 4.9 |
| medium | 12 | 12 | 100% | 12,591 | 5.7 |
| hard | 10 | 8 | 80.0% | 17,901 | 7.1 |
| **合计** | **36** | **33** | **91.7%** | **11,120** | **5.3** |

整轮 399k tokens、墙钟 67 秒。原始报告在
[`docs/benchmarks/deepseek-36.json`](docs/benchmarks/deepseek-36.json)，跑法与三个失败案例的
归因见 [`docs/benchmark.md`](docs/benchmark.md)。

## 现在能跑什么

- **端到端的流式工具调用。** DeepSeek 流式吐出一个工具调用，循环用 JSON Schema 校验参数、执行、把结果塞回上下文，直到模型不再要工具。
- **四个工具** —— `read_file`、`write_file`、`edit_file`、`shell` —— 带路径沙箱、输出截断、超时控制，以及 `LOCA_*` 环境变量隔离。
- **错误恢复** —— 瞬时故障（限流 / 超时 / 5xx）走指数退避重试，且**只在第一个流式分片到达前重试**，用户已经看到的内容不会被重放；回复被输出长度截断时自动追加「继续」；上下文即将溢出前裁剪旧消息。
- **会话可以断点续聊** —— 每轮结束写进 SQLite（默认 `~/.loca/sessions.db`）。`loca chat --session <id>` 在新进程里接着上次聊；`loca sessions` 列出、查看、删除。
- **文件改动可回滚** —— `write_file` / `edit_file` 执行前先存快照，`loca rollback <session> <step>` 把工作区还原到任意一步之前；新建的文件会被删掉而不是清空。
- **上下文压缩** —— 预算耗尽时让模型把旧消息压成一段摘要（而不是直接丢弃），摘要会钉在窗口里；REPL 里可 `/compact` 手动触发。
- **每一步都可追踪** —— 每「模型步」记录 prompt 摘要、回复、推理内容、工具调用与结果、token、耗时、重试次数与检查点，双写 SQLite（`traces` 表）与 JSONL 镜像；`loca report <session>` 把它渲染成表格，`--verbose` 展开细节，`--json` 供脚本消费，`--no-trace` 可整轮关掉。
- **三家 provider 都可用** —— DeepSeek 与 OpenAI 共用一层 OpenAI 兼容实现（`providers/openai_compat.py`），Anthropic 走独立的协议翻译层（消息、工具、流式事件、缓存 token 都做了映射）；同一任务在三家上的工具调用与流式结果有一致性回归测试钉住。
- **失败不会打断流** —— 不可恢复的 provider 错误以 `error` 事件呈现，而不是掐断 SSE 连接。
- **自带评测集，能证明自己行不行** —— `loca bench run` 把 36 个任务（14 简单 / 12 中等 / 10 困难）并发跑一遍，每个任务跑的是**真实的执行循环和真实的工具**，评分也是**行为式**的（跑 pytest / 比 stdout / 调校验脚本），不看代码 diff。评分文件放在 `hidden/`：agent 看不到，判分前才盖回沙箱 —— 模型改自己的测试文件是没用的。输出 pass@1、pass@k、按难度的分解、失败归因和 token / 步数成本，支持 `--json`、`--compare` 多 provider 对比。
- **任务集自身也有测试** —— `loca bench verify` 逐题确认「起始工作区必须判不过、参考答案必须判得过」。一道题若初始就通过，它什么都没在测；一道题若参考答案都过不了，它报的每个失败都是噪音。
- **397 项离线测试**（另 1 项按条件跳过）+ 8 项真实 DeepSeek e2e 测试。

## 运行环境

**只支持 Windows。** 这不是「暂时没适配」，而是刻意的取舍：目标是本地 Windows
开发机上的单用户 agent，多平台分支只会引入没人跑的代码路径。

| 项目 | 约定 |
|---|---|
| 平台 | Windows 10 / 11 |
| Shell | **cmd.exe**（不是 PowerShell，也不是 Git Bash） |
| 路径 | Windows 路径，如 `D:\Projects\repo` |
| Python | 3.13+ |

所以 `shell` 工具跑的是 cmd.exe —— 用 `dir` / `type` / `del` / `findstr`，
而不是 `ls` / `cat` / `rm` / `grep`。默认系统提示词里已写明这一点，模型不会拿
POSIX 命令去撞南墙。

> `--workspace /d/repo` 这种 Git-Bash 写法会被**直接拒绝**并提示正确路径。因为
> `ntpath` 会把它当成**盘符相对路径**，悄悄解析成 `D:\d\repo` —— 一个空目录。
> 它是「不报错但结果全错」，排查起来最费劲，所以宁可挡在门口。

## 快速开始

在 cmd.exe 里：

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
pytest -v
```

最后一步之后把 `.env` 打开填上你的 DeepSeek key。没有 key 时联网 e2e 会自动跳过。

## 两个界面

真正能和 loca 对话的方式有两种。

### 1. CLI REPL —— `loca chat`

一个流式终端对话界面：你输入，agent 回答，需要时自己调用工具。工具调用、上下文裁剪、重试和错误都会就地打印出来。

```
$ loca chat --workspace D:\some\repo
loca · provider deepseek · 4 tool(s) · workspace D:\some\repo

you › 读一下 README.md，总结 status 那一节
assistant → read_file(path='README.md')
✓ read_file
assistant status 那一节说的是 ...
                        steps 1  ·  tokens 812  ·  finish stop
```

全部子命令：

| 命令 | 作用 |
|---|---|
| `loca chat` | 带四个工具的 agent REPL（默认落库） |
| `loca chat --no-tools` | 纯流式对话（不暴露工具） |
| `loca chat --workspace <dir>` | 把工具的沙箱切到别的目录 |
| `loca chat --session <id>` | 恢复某次会话，不存在则以该名字新建 |
| `loca chat --no-save` | 不写数据库、不做检查点 |
| `loca chat --no-trace` | 不记录逐步骤轨迹（默认会记录） |
| `loca sessions [list\|show\|rm] [id]` | 列出 / 查看 / 删除会话 |
| `loca rollback <session> <step>` | 把文件还原到第 `<step>` 步之前 |
| `loca report [id]` | 渲染某会话的执行轨迹（`--verbose` 展开、`--json` 输出 JSON） |
| `loca bench [list\|run\|verify]` | 列出任务 / 并发跑评测集 / 校验任务集是否有效（`--json`、`--compare` 多 provider 对比） |
| `loca serve` | 在 <http://127.0.0.1:8765> 起 Web GUI |
| `loca tools` | 列出已注册工具及其必填参数 |
| `loca providers` | 显示哪些 provider 已配好凭据 |

会话默认存在 `~/.loca/sessions.db`（用 `--db` 或 `$LOCA_DB` 改）。REPL 内还有 `/help`、`/compact`、`/session`、`/trace` 四个命令。

### 2. Web GUI —— `loca serve`

`web/` 下是 FastAPI + SSE 后端和一个单页聊天 UI（`web/index.html`，无构建步骤）。起服务后打开 <http://127.0.0.1:8765>，在浏览器里直接聊。流式文本、工具调用、工具结果和错误都会渲染成独立的气泡。

## 在 VS Code 里运行

`.vscode/launch.json` 已经配好一切 —— 打开 **运行和调试** 面板（`Ctrl+Shift+D`），从下拉框选一个配置，按 `F5`：

| 配置名 | 结果 |
|---|---|
| `loca chat (CLI REPL)` | 在集成终端跑交互式 CLI，工作目录 = 项目根 |
| `loca chat (sandboxed to playground/)` | 同样的 REPL，但沙箱到空的 `playground/`，方便随便造文件 |
| `loca chat --no-tools` | 只跑流式对话，用来隔离 provider 层问题 |
| `loca serve (Web GUI)` | 启动 uvicorn **并自动打开浏览器** <http://127.0.0.1:8765> |
| `loca tools / providers` | 打印工具清单与凭据状态 |
| `pytest (offline)` | 离线测试套件，联网 e2e 被排除（`-m "not live"`） |
| `pytest (all, hits real API)` | 全部测试，包含真实 DeepSeek 调用 |

Test Explorer 跑的是同一套测试。`python -m loca chat` 是 `loca chat` 的等价写法，所以在控制台脚本不在 `PATH` 上的时候，普通终端也能直接跑。`scripts/interactive_chat.py` 是个转发到 `loca chat` 的薄启动器。

> **第一次跑 Web GUI？** 从启动、验证、使用到关闭和排错（含端口被占用的处理），见
> [`docs/running-the-web-gui.md`](docs/running-the-web-gui.md) ——一份写给非科班同学的逐步说明，所有命令与输出均经过实测。

> **第一次跑 CLI？** 从哪启动、输出怎么看、工作目录（沙箱）是什么、`Ctrl+C` 的两种含义，见
> [`docs/running-the-cli.md`](docs/running-the-cli.md)。

> **会话怎么续、文件怎么回滚？** 会话库在哪、`sessions` / `rollback` 怎么用、检查点的三条规则和限制、摘要式上下文压缩，见
> [`docs/sessions-and-rollback.md`](docs/sessions-and-rollback.md)。

> **每一步到底发生了什么？** 会话和轨迹的区别、每个模型步记了哪些字段、轨迹双写在哪、`loca report` 的输出怎么读、token 与耗时怎么算，见
> [`docs/traces-and-reports.md`](docs/traces-and-reports.md)。

> **它到底行不行？** 任务长什么样、评分怎么保证公平（`hidden/` 与行为式判分）、`loca bench` 怎么用、
> 36 题的真实跑分与三个失败案例的归因，见 [`docs/benchmark.md`](docs/benchmark.md)。
> 想做评测这件事本身的复盘，见 [`docs/blog-benchmarking-a-coding-agent.md`](docs/blog-benchmarking-a-coding-agent.md)。

## 许可

MIT

---

# English

## Why another harness?

Most agent projects glue prompts onto an LLM SDK and stop there. Real coding
agents spend 95% of their complexity in the harness layer:

- A unified tool-use protocol across vendors (DeepSeek / OpenAI / Anthropic).
- A streaming execution loop that survives tool failures and bad model output.
- Schema-validated tool calls so the model can't break the agent.
- Observability: every step is traced for later debugging and eval.

Loca keeps the surface small on purpose — no LangChain, no LlamaIndex, no
hidden framework. Every line that matters lives in `loca/`.

## Layout

```
loca/
├── cli.py        # `loca chat` / `sessions` / `rollback` / `report` / `serve` / `tools` / `providers`
├── providers/    # Vendor-neutral LLM interface + DeepSeek/OpenAI/Anthropic impls
├── tools/        # Tool protocol + read_file/write_file/edit_file/shell + registry
├── core/         # Execution loop, events, error recovery, context compaction
├── observability/# Session persistence (SQLite) + checkpoints + step traces and reports
└── eval/         # Benchmark: a 36-task suite + concurrent runner + report rendering

web/              # FastAPI + SSE server and a single-page chat UI
scripts/          # Thin launchers (interactive_chat.py → `loca chat`)
docs/             # Guides (CLI, web GUI, sessions and rollback, traces and reports, benchmark)
tests/            # Offline unit tests + live DeepSeek e2e (auto-skipped w/o key)
```

## Status

This project is being built week-by-week as a portfolio piece for an
agent-engineering internship. The living checklist is
[`loca_roadmap.md`](loca_roadmap.md).

- [x] Week 1 — Provider abstraction + DeepSeek streaming
- [x] Week 2 — Tool protocol + filesystem / shell (4 tools) + web UI
- [x] Week 3 — Execution loop + error recovery + context budgeting
- [x] Week 4 — Session persistence + checkpoints + summarising compaction
- [x] Week 5 — Observability (traces + reports) + Anthropic/OpenAI wiring
- [x] Week 6 — Benchmark (36 shipped tasks) + a real run report + a technical write-up

## Benchmark (real numbers)

DeepSeek's default model, 36 shipped tasks, 1 attempt each, 4 workers —
**pass@1 = 91.7% (33/36)**:

| Tier | Tasks | Passed | Pass rate | Tokens/pass | Steps/pass |
|---|---:|---:|---:|---:|---:|
| simple | 14 | 13 | 92.9% | 8,071 | 4.9 |
| medium | 12 | 12 | 100% | 12,591 | 5.7 |
| hard | 10 | 8 | 80.0% | 17,901 | 7.1 |
| **total** | **36** | **33** | **91.7%** | **11,120** | **5.3** |

399k tokens and 67 seconds of wall clock for the whole run. The raw report is
[`docs/benchmarks/deepseek-36.json`](docs/benchmarks/deepseek-36.json); how to run
it and what the three failures were is in [`docs/benchmark.md`](docs/benchmark.md).

## What works today

- **Streaming tool use end-to-end.** DeepSeek streams a tool call, the loop
  validates the arguments against JSON Schema, executes it, feeds the result
  back, and continues until the model stops asking for tools.
- **Four tools** — `read_file`, `write_file`, `edit_file`, `shell` — with path
  sandboxing, output truncation, timeouts, and `LOCA_*` env isolation.
- **Error recovery** — exponential-backoff retries for transient provider
  failures (retrying only *before* the first streamed chunk, so nothing the
  user already saw gets replayed), automatic continuation when a reply is cut
  off by the output length limit, and context trimming before the window
  overflows.
- **Sessions survive a restart** — every turn is written to SQLite
  (`~/.loca/sessions.db` by default), so `loca chat --session <id>` picks the
  conversation back up in a fresh process. `loca sessions` lists, inspects and
  deletes them.
- **File edits are undoable** — `write_file` and `edit_file` snapshot their
  targets *before* running, and `loca rollback <session> <step>` restores the
  workspace to its state before any step. Files the agent created are deleted,
  not blanked.
- **Context compaction** — when the budget runs out the model folds the old
  turns into a summary instead of losing them, pinned into the window; `/compact`
  triggers it by hand. A real tokenizer is used when `tiktoken` is installed,
  with a documented heuristic otherwise.
- **Every step is traceable** — each model step records its prompt summary, reply,
  reasoning, tool calls and results, tokens, duration, retry count and
  checkpoints, written both to SQLite (a `traces` table) and a JSONL mirror.
  `loca report <session>` renders it, `--verbose` expands the detail, `--json`
  feeds scripts, and `--no-trace` turns the whole thing off.
- **All three providers work** — DeepSeek and OpenAI share one OpenAI-compatible
  implementation (`providers/openai_compat.py`); Anthropic has its own protocol
  translation layer (messages, tools, stream events and cached tokens are all
  mapped). Cross-provider parity tests pin the tool-calling and streaming
  behaviour to be the same on the same task.
- **Failures never break the stream** — unrecoverable provider errors surface
  as an `error` event instead of killing the SSE connection.
- **It ships a benchmark it can be judged by** — `loca bench run` executes 36
  tasks (14 simple / 12 medium / 10 hard) concurrently through the *real*
  execution loop and the *real* tools, and grades them *behaviourally* (run
  pytest, compare stdout, call a verifier) rather than by diffing source. Grader
  files live in `hidden/`: the agent never sees them, and they are copied back
  over the sandbox before grading, so editing your own tests buys nothing. The
  report gives pass@1, pass@k, a per-difficulty breakdown, failure attribution
  and token/step cost, with `--json` and a `--compare` mode for side-by-side
  provider runs.
- **The task set tests itself** — `loca bench verify` checks every task fails on
  its starting workspace and passes with its reference solution. A task that
  already passes measures nothing; a task whose own reference answer fails
  reports nothing but noise.
- **397 offline tests** (plus 1 conditionally skipped) and 8 live DeepSeek e2e
  tests.

## Requirements

**Windows only.** This is a deliberate trade-off, not a missing feature: loca
targets a single developer machine, and cross-platform branches would only add
code paths nobody runs.

| | |
|---|---|
| Platform | Windows 10 / 11 |
| Shell | **cmd.exe** (not PowerShell, not Git Bash) |
| Paths | Windows paths, e.g. `D:\Projects\repo` |
| Python | 3.13+ |

So the `shell` tool runs cmd.exe — `dir` / `type` / `del` / `findstr`, not
`ls` / `cat` / `rm` / `grep`. The default system prompt states this, so the
model doesn't burn a turn on POSIX commands.

> A Git-Bash-style `--workspace /d/repo` is **rejected outright** with the
> correct spelling. `ntpath` reads such a path as *drive-relative* and
> silently resolves it to `D:\d\repo` — an empty directory. It "succeeds"
> while pointing somewhere wrong, which is the most expensive kind of bug.

## Quick start

From cmd.exe:

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
pytest -v
```

Then open `.env` and fill in your DeepSeek key — without one, live e2e tests
skip themselves.

## The two interfaces

There are two ways to actually talk to loca.

### 1. CLI REPL — `loca chat`

A streaming terminal chat where you type and the agent answers, calling tools
as it needs them. Tool calls, context trims, retries and errors are all
printed inline.

```
$ loca chat --workspace D:\some\repo
loca · provider deepseek · 4 tool(s) · workspace D:\some\repo

you › read README.md and summarise the status section
assistant → read_file(path='README.md')
✓ read_file
assistant The status section says ...
                        steps 1  ·  tokens 812  ·  finish stop
```

Every command:

| Command | What it does |
|---|---|
| `loca chat` | Agent REPL with the four tools (persisted by default) |
| `loca chat --no-tools` | Plain streaming chat (no tool use) |
| `loca chat --workspace <dir>` | Sandbox the tools to a different directory |
| `loca chat --session <id>` | Resume that session, or start one with that id |
| `loca chat --no-save` | No session database, no checkpoints |
| `loca chat --no-trace` | Do not record per-step traces (on by default) |
| `loca sessions [list\|show\|rm] [id]` | List, inspect or delete sessions |
| `loca rollback <session> <step>` | Restore files to their state before step `<step>` |
| `loca report [id]` | Render a session's execution trace (`--verbose`, `--json`) |
| `loca bench [list\|run\|verify]` | List tasks / run the suite concurrently / verify the task set (`--json`, `--compare`) |
| `loca serve` | Web GUI on <http://127.0.0.1:8765> |
| `loca tools` | List the registered tools and their required args |
| `loca providers` | Show which providers have credentials |

Sessions default to `~/.loca/sessions.db` (override with `--db` or `$LOCA_DB`).
Inside the REPL there are also `/help`, `/compact`, `/session` and `/trace`.

### 2. Web GUI — `loca serve`

`web/` holds a FastAPI + SSE backend and a single-page chat UI
(`web/index.html`, no build step). Start the server, open
<http://127.0.0.1:8765>, and chat in the browser. Streaming text, tool calls,
tool results and errors all render as separate message bubbles.

## Running it from VS Code

`.vscode/launch.json` defines everything you need — open the **Run and Debug**
panel (`Ctrl+Shift+D`) and pick a configuration, then press `F5`:

| Configuration | Result |
|---|---|
| `loca chat (CLI REPL)` | Interactive CLI in the integrated terminal, workspace = project root |
| `loca chat (sandboxed to playground/)` | Same REPL, sandboxed to an empty `playground/` for throwaway file work |
| `loca chat --no-tools` | Streaming chat only, to isolate provider-level issues |
| `loca serve (Web GUI)` | Starts uvicorn **and opens the browser** at <http://127.0.0.1:8765> |
| `loca tools / providers` | Prints the tool list and credential status |
| `pytest (offline)` | Unit suite, live e2e deselected (`-m "not live"`) |
| `pytest (all, hits real API)` | Everything, including the live DeepSeek calls |

The Test Explorer also runs the same suite. `python -m loca chat` works as an
alias for `loca chat`, so you can run it from a plain terminal without the
console script being on `PATH`. `scripts/interactive_chat.py` is a thin
launcher that forwards to `loca chat`.

> **New to the web GUI?** A step-by-step walkthrough — starting it, verifying it,
> using it, shutting it down, and troubleshooting a port already in use — lives in
> [`docs/running-the-web-gui.md`](docs/running-the-web-gui.md) (Chinese). Every
> command and its output in that guide was verified on a real machine.

> **New to the CLI?** Where to launch it from, how to read its output, what the
> workspace sandbox means, and the two meanings of `Ctrl+C` are covered in
> [`docs/running-the-cli.md`](docs/running-the-cli.md) (Chinese).

> **Sessions and rollback?** Where the session database lives, how `sessions`
> and `rollback` behave, the three checkpoint rules and their limits, and how
> summarising compaction works: [`docs/sessions-and-rollback.md`](docs/sessions-and-rollback.md) (Chinese).

> **What actually happened at each step?** How a session differs from a trace,
> which fields each model step records, where traces are written, how to read
> `loca report`, and how tokens and durations are computed:
> [`docs/traces-and-reports.md`](docs/traces-and-reports.md) (Chinese).

> **Does it actually work?** What a task looks like, how grading stays honest
> (`hidden/` files and behavioural checks), how to drive `loca bench`, the real
> 36-task run and what the three failures were:
> [`docs/benchmark.md`](docs/benchmark.md) (Chinese). The write-up about building
> the benchmark itself is
> [`docs/blog-benchmarking-a-coding-agent.md`](docs/blog-benchmarking-a-coding-agent.md) (Chinese).

## License

MIT
