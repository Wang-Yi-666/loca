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
├── cli.py        # `loca chat` / `serve` / `tools` / `providers`
├── providers/    # 厂商中立的 LLM 接口 + DeepSeek/OpenAI/Anthropic 实现
├── tools/        # 工具协议 + read_file/write_file/edit_file/bash + 注册表
├── core/         # 执行循环、事件、错误恢复、上下文预算
├── observability/# 追踪与 SQLite 存储                          （Week 5）
└── eval/         # Benchmark 评测框架                          （Week 6）

web/              # FastAPI + SSE 服务端与单页聊天 UI
scripts/          # 薄启动器（interactive_chat.py → `loca chat`）
docs/             # 使用指南（CLI 与 Web GUI 的逐步运行说明）
tests/            # 离线单测 + 真实 DeepSeek e2e（无 key 自动跳过）
```

## 进度

本项目作为 agent 工程方向实习的作品集，按周推进。实时清单见
[`loca_roadmap.md`](loca_roadmap.md)。

- [x] Week 1 —— Provider 抽象层 + DeepSeek 流式
- [x] Week 2 —— 工具协议 + 文件系统 / bash（4 个工具）+ Web UI
- [x] Week 3 —— 执行循环 + 错误恢复 + 上下文预算
- [ ] Week 4 —— Session 持久化 + Checkpoint
- [ ] Week 5 —— 可观测性 + Anthropic/OpenAI 接入
- [ ] Week 6 —— Benchmark + 报告

## 现在能跑什么

- **端到端的流式工具调用。** DeepSeek 流式吐出一个工具调用，循环用 JSON Schema 校验参数、执行、把结果塞回上下文，直到模型不再要工具。
- **四个工具** —— `read_file`、`write_file`、`edit_file`、`bash` —— 带路径沙箱、输出截断、超时控制，以及 `LOCA_*` 环境变量隔离。
- **错误恢复** —— 瞬时故障（限流 / 超时 / 5xx）走指数退避重试，且**只在第一个流式分片到达前重试**，用户已经看到的内容不会被重放；回复被输出长度截断时自动追加「继续」；上下文即将溢出前裁剪旧消息。
- **失败不会打断流** —— 不可恢复的 provider 错误以 `error` 事件呈现，而不是掐断 SSE 连接。
- **116 项离线测试** + 7 项真实 DeepSeek e2e 测试。

## 快速开始

```bash
python -m venv .venv
. .venv/Scripts/activate          # Windows
pip install -e ".[dev]"
cp .env.example .env              # 然后把你的 DeepSeek key 填进 .env
pytest -v                         # 没有 key 时联网 e2e 自动跳过
```

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
| `loca chat` | 带四个工具的 agent REPL |
| `loca chat --no-tools` | 纯流式对话（不暴露工具） |
| `loca chat --workspace <dir>` | 把工具的沙箱切到别的目录 |
| `loca serve` | 在 <http://127.0.0.1:8765> 起 Web GUI |
| `loca tools` | 列出已注册工具及其必填参数 |
| `loca providers` | 显示哪些 provider 已配好凭据 |

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
├── cli.py        # `loca chat` / `serve` / `tools` / `providers`
├── providers/    # Vendor-neutral LLM interface + DeepSeek/OpenAI/Anthropic impls
├── tools/        # Tool protocol + read_file/write_file/edit_file/bash + registry
├── core/         # Execution loop, events, error recovery, context budgeting
├── observability/# Traces and SQLite storage                  (Week 5)
└── eval/         # Benchmark harness                          (Week 6)

web/              # FastAPI + SSE server and a single-page chat UI
scripts/          # Thin launchers (interactive_chat.py → `loca chat`)
docs/             # Guides (step-by-step CLI and web GUI walkthroughs)
tests/            # Offline unit tests + live DeepSeek e2e (auto-skipped w/o key)
```

## Status

This project is being built week-by-week as a portfolio piece for an
agent-engineering internship. The living checklist is
[`loca_roadmap.md`](loca_roadmap.md).

- [x] Week 1 — Provider abstraction + DeepSeek streaming
- [x] Week 2 — Tool protocol + filesystem / bash (4 tools) + web UI
- [x] Week 3 — Execution loop + error recovery + context budgeting
- [ ] Week 4 — Session persistence + checkpoint
- [ ] Week 5 — Observability + Anthropic/OpenAI wiring
- [ ] Week 6 — Benchmark + report

## What works today

- **Streaming tool use end-to-end.** DeepSeek streams a tool call, the loop
  validates the arguments against JSON Schema, executes it, feeds the result
  back, and continues until the model stops asking for tools.
- **Four tools** — `read_file`, `write_file`, `edit_file`, `bash` — with path
  sandboxing, output truncation, timeouts, and `LOCA_*` env isolation.
- **Error recovery** — exponential-backoff retries for transient provider
  failures (retrying only *before* the first streamed chunk, so nothing the
  user already saw gets replayed), automatic continuation when a reply is cut
  off by the output length limit, and context trimming before the window
  overflows.
- **Failures never break the stream** — unrecoverable provider errors surface
  as an `error` event instead of killing the SSE connection.
- **116 offline tests** plus 7 live DeepSeek e2e tests.

## Quick start

```bash
python -m venv .venv
. .venv/Scripts/activate          # Windows
pip install -e ".[dev]"
cp .env.example .env              # then put your DeepSeek key in .env
pytest -v                         # live e2e auto-skips without a key
```

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
| `loca chat` | Agent REPL with the four tools |
| `loca chat --no-tools` | Plain streaming chat (no tool use) |
| `loca chat --workspace <dir>` | Sandbox the tools to a different directory |
| `loca serve` | Web GUI on <http://127.0.0.1:8765> |
| `loca tools` | List the registered tools and their required args |
| `loca providers` | Show which providers have credentials |

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

## License

MIT
