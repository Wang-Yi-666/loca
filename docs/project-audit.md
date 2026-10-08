# loca 项目审查报告

> **审查基准**：`loca_roadmap.md`（6 周计划书，167 个已勾选项）
> **审查日期**：2026-09-18
> **审查范围**：`loca/`（31 个模块 / 7,840 行）、`tests/`（21 个文件 / 6,978 行）、
> `web/`、`scripts/`、`docs/`、`loca/eval/tasks/`（36 题 / 161 个夹具文件）、git 状态
> **审查方式**：静态阅读 + **动手复现**。每一条结论都在本机跑过；能复现的给命令，不能的给行号。

---

## 0. 一句话结论

**计划书里的六周目标全部真实达成，没有一个勾选项是空的。** 167 个勾选项里，
约 155 条在代码里逐条成立（92.7%）；12 条属于「声明成立、边界不成立」或「描述已过时」。
跑分数字 91.7% 可被归档证据完整复算。

但审查也发现 **3 个 P1 缺陷**，它们都不影响已归档的跑分，却会在真实使用中咬人 ——
而且三个都落在**边界**上（超时、环境变量回退、同一步多次改动），单测恰好都绕开了这些路径。

> **✅ 全部缺陷已于 2026-09-18 修复**：P1 3 项（A1–A3）、P2 12 项（B1–B12，含补充的 B9–B12）、
> P3 11 项（C1–C11），共 **26 项**，逐条修法与验证证据见 [§9 修复记录](#9-修复记录2026-09-18)。
> 修复后 `ruff check .` 全绿、离线测试 **426 passed**（原 397 passed + 1 skipped）、
> `loca bench verify` 36 题全部通过。本报告正文保留修复前的原始结论，便于对照。

> **诚实声明**：以下所有「复现」结论都是我本机实测的结果，不是推断。
> 复现脚本在 `.workbuddy/scratch/audit_*.py`，可直接重跑。

---

## 1. 审查方法与可复现证据

| 验证项 | 命令 | 结果（审查当时） |
|---|---|---|
| 静态检查 | `ruff check .` | `rc=0`，All checks passed |
| 离线测试 | `pytest -m "not live"` | **398 收集 → 397 passed, 1 skipped** |
| 联网测试 | `pytest -m "live"` | **8 passed**（真实 DeepSeek） |
| 合计 | — | **406 项**（397 + 1 + 8） |
| 任务集自检 | `loca bench verify` | **all 36 task(s) check out**（25.6 s） |
| 任务集列举 | `loca bench` | rc=0，列出 36 题（默认动作 = list） |
| CLI 面 | `loca --help` | 8 个文档化子命令全部存在，无缺失 |
| 跑分复算 | 读 `docs/benchmarks/deepseek-36.json` | pass@1 = 0.9167，33/36，与文档一致 |

> **修复后的同一组命令**（2026-09-18）：`ruff check .` 全绿 ·
> `pytest -m "not live"` → **426 passed, 0 skipped**（434 收集） ·
> `pytest -m "live"` → **8 passed** · 合计 **434 项** ·
> `loca bench verify` → **all 36 task(s) check out**（仍 36/36）。

跑分证据的**逐条复核**（这是本次审查最看重的一项）：

| 文档里的说法 | 归档 JSON 里的实际值 | 判定 |
|---|---|---|
| pass@1 = 91.7%（33/36） | `pass_at_1: 0.9167`，`passed_attempts: 33` | ✅ |
| simple 92.9% / 8,071 tok / 4.9 步 | `0.9286` / `8070.9` / `4.92` | ✅ |
| medium 100% / 12,591 tok / 5.7 步 | `1.0` / `12590.8` / `5.67` | ✅ |
| hard 80.0% / 17,901 tok / 7.1 步 | `0.8` / `17900.9` / `7.12` | ✅ |
| 整轮 399,218 tokens、墙钟 67 秒、累计 256 秒 | `399218.0` / `66.9` / `255.94` | ✅ |
| `impl-expression-evaluator` 16 条过 15 条，差 `1++2` | 判分详情：`1 failed, 15 passed`，失败用例正是 `test_malformed_input_is_rejected[1++2]` | ✅ |
| `impl-word-wrap` 11 条只过 2 条，4 步交卷 | `9 failed, 2 passed`（= 11），`steps: 4` | ✅ |
| `fix-recursion-base-case` 负数未抛 `ValueError` | 失败用例 `test_negative_is_rejected`，`DID NOT RAISE ValueError` | ✅ |

**结论：三名失败案例的归因叙述逐字对得上判分器的原始输出。** 这份跑分不是编的。

---

## 2. 逐周符合度（对照计划书）

| Week | 勾选项 | 逐条成立 | 部分/需更正 | 判定 |
|---|---:|---:|---:|---|
| 平台约定（Windows only） | — | 4 | 1 | ✅ 实质达成；`requires-python` 与文档不一致（见 C3） |
| Week 1 Provider 抽象 | 9 | 8 | 1 | ✅ 达成；1 条描述已被 Week 5 取代（见 C8） |
| Week 2 工具协议 | 24 | 21 | 3 | ✅ 达成；`shell` 两处边界缺陷（见 A1/A2）、`read_file` 无总量上限（B1） |
| Week 3 执行循环 + 恢复 | 20 | 20 | 0 | ✅ 完全成立 |
| Week 4 持久化 + 回滚 | 48 | 44 | 4 | ⚠️ 达成，但回滚有 P1 缺陷（A3） |
| Week 5 可观测性 + 多 Provider | 34 | 30 | 4 | ⚠️ 达成，但 4 条声明与实现不完全一致（B3/B4/B10/C4） |
| Week 6 Benchmark + 报告 | 32 | 30 | 2 | ✅ 达成；自检漏一种坏题（B7）、报告不记模型（B8） |
| **合计** | **167** | **≈155** | **12** | **92.7% 逐条成立** |

### 各周要点

**Week 1（9/9 勾选，8 条成立）**
公共类型、`LLMProvider` 抽象基类、DeepSeek 流式 + `reasoning_content` 分离、registry、
3 个真实 e2e —— 全部在代码里找得到。唯一问题是第 5 条
「OpenAIProvider / AnthropicProvider **stub**（缺 key 时抛 `NotImplementedError`）」
已经过时：全仓库（排除评测夹具）**已无任何 `NotImplementedError`**，
Week 5 把两者都改成了完整实现并抛 `ValueError`。历史日志可以保留，但清单里应加注（C8）。

**Week 2（24 条，21 条成立）**
四个工具、JSON Schema 校验、路径沙箱全部落到实处，且沙箱实现经得起实测
（`..`、相似前缀 `D:\Projects\loca_evil`、`\\?\` 前缀、junction 展开全部拒绝）。
`ToolRegistry` 这条名不副实：并没有这个类，而是模块级函数 `register` / `get` / `all_tools`，
其中 `get()` **零调用**（循环用 `self.tools` 线性查找），模块 docstring 还写着
"Week-1 placeholder"。
`shell` 的三重截断、超时、环境隔离都写了，但 **超时实际不生效**（A1）、
**回退 shell 不可用**（A2）、**超时路径绕过截断**（B5）。

**Week 3（20/20 成立）**
本模块是全文最扎实的一块。重试严格限制在「首个流式分片到达之前」、
`finish_reason=length` 自动续写、孤儿 tool 消息剔除、请求快照防污染 ——
逐条都能在 `core/recovery.py` 与 `core/loop.py` 里找到对应实现，且有 25 + 6 项测试钉住。

**Week 4（48 条，44 条成立）**
四张表（实际五张，Week 5 加了 `traces`）、级联删除、WAL、`next_step` 持久化、
`ensure_session` 恢复/新建、`save_transcript` 事务重写、检查点快照（文本/二进制/超限降级）、
`shell` 不可回滚如实上报 —— 全部成立。
但**回滚语义有 P1 缺陷**（A3）：同一步内多次改动同一文件时会还原成中间版本。
另有 `settled()` 截断含 `" ("` 的文件名（C5）、`read_bytes()` 未受保护（4.2 B6）、
「会话库可跨机器迁移」的卖点没有真正兑现（4.2 B7）。

**Week 5（34 条，30 条成立）**
trace 作为事件 sink、双写 SQLite + JSONL、`reporter` 双输出、四家 provider 分层
（OpenAI 兼容层 + Anthropic 纯函数翻译层）、`cache_read_input_tokens` 计入 prompt token、
SDK 懒导入并给出 `pip install "loca[anthropic]"` —— 全部成立且可测。
四处不一致：`reasoning_content` 声明要记录但**从未写入**（C4）；
「重试次数」实际统计的是「续写次数」（B10）；`finish_reason` 单元格漏了 `markup.escape`；
OpenAI 流式不请求 usage 导致 token 恒为 0（B3）。
最后一条与「三家 parity（含 usage）」的勾选直接冲突。

**Week 6（32 条，30 条成立）**
36 题全部通过自检、七类 outcome、pass@1 与 pass@k 分开、防作弊测试、真实跑分 ——
全部成立，且跑分证据可完整复算。
两处缺口：任务集自检**不检查「有没有参考答案」**，缺 solution 的题会被判为合格（B7）；
归档报告**不记录模型名**（`"model": null`），一个以「可复现」为卖点的证据文件
却无法自证用的是哪个模型（B8）。

---

## 3. 文档数字核对表

> 下表「文档里的数字」一列是**修复前**的原文；「实测」一列保留审查当时的复算结果；
> 最右列给出修复后文档采纳的口径。修复后的权威数字见 §9 末尾的「数字口径」小节。

| 文档里的数字（修复前） | 实测（审查当时） | 判定 |
|---|---|---|
| harness **7,840 行 / 31 个模块**（不含评测夹具） | 31 个 `.py` / 7,840 行（排除 `eval/tasks/` 树） | ✅ 精确（修复后 **8,380 行**，模块数仍 31） |
| 测试 **6,978 行 / 21 个测试文件 / 406 项** | 6,978 行 / 21 文件 / 397+1+8 = 406 | ✅ 精确（修复后 **7,520 行 / 434 项**） |
| README **447 行** | 447 行 | ✅ 精确（补齐 launch.json 表后 **450 行**） |
| **6 篇中文指南 1,650 行** | `docs/*.md` 去掉简历 = 6 篇 / 1,650 行 | ✅ 精确（修复未改动这 6 篇，仍 1,650 行） |
| **36 道任务** | 36 个题目目录，14/12/10 | ✅ 精确 |
| 评测集 **128 个文件 / 5,994 行** | 128 = 124 个夹具 `.py` + **4 个生成脚本**；5,994 = 2,510 + **3,484** | ⚠️ 口径问题，见 C1 —— 已改为 **161 文件 / 3,103 行** |
| Week 6 新增测试 **82 项**（51 + 31） | `test_eval_tasks` 51、`test_benchmark` 31 | ✅ 精确 |
| 离线 **397 passed, 1 skipped** | 397 / 1（skip 原因是 `no .bashrc on this system`） | ✅ 精确（修复后 **426 passed, 0 skipped** —— 那条跳过项被重写成真断言） |
| 联网 **8 项** | 8 passed | ✅ 精确（未变） |
| launch.json「配好一切」 | 文件里有 **9 个**配置，README 表只列了 **7 个** | ⚠️ 见 C2 —— README 已补齐 9 条 |

---

## 4. 缺陷清单

严重程度定义：
**P1** = 会造成错误结果或功能失效；**P2** = 声明成立但边界不成立，或造成数据/上下文损失；
**P3** = 文档漂移、死代码、一致性瑕疵。

### 4.1 P1（3 项）

#### A1. `shell` 的超时不是上限 —— 超时后进程树不会被杀

**位置**：`loca/tools/shell.py:157-175`

**复现**（timeout 声明 2 秒，实际跑了 8.09 秒）：

```
declared timeout=2s, actual wall clock=8.09s
工具自己的消息：'Command timed out after 2s (elapsed 8.1s). Partial output:'
```

**机理**：`shell=True` 下 `subprocess.run` 超时只终止 `cmd.exe` 这一个进程；
真正干活的孙进程（`python` / `pytest` / `npm`）仍在运行，且继承了 stdout 管道的写端，
于是 `communicate()` 必须一直等到**孙进程自己退出**才能收尾。

**为什么是问题**：agent 的循环是同步的，一条 `timeout=30` 的 `pytest`
能把整个会话挂住几分钟到几小时。`loca bench` 的「协作式墙钟超时」也拦不住它
（那套检查只在流式事件之间生效，而这里根本没有事件）。

**当前文档的覆盖程度**：`docs/benchmark.md` 第 8 节只承认了
「provider 卡在 HTTP 客户端内部」这一种超时不准，**没有提到 shell 这一种**。
修法：Windows 上用 `CREATE_NEW_PROCESS_GROUP` + `taskkill /F /T /PID`，或 Job Object 整树杀。

> **✅ 已修复**（`tools/shell.py`）：`execute()` 改走新的 `_run_command()` ——
> `Popen(CREATE_NEW_PROCESS_GROUP)` + 两个守护线程分别抽干 stdout/stderr，
> `wait(timeout)` 超时后 `_kill_process_tree(pid)`（`taskkill /F /T /PID`）再收尾。
> 复现脚本同一场景：**8.09s → 2.24s**，超时后无孙进程残留（PowerShell 按命令行匹配
> `time.sleep(30)` 计数为 0）。另补两条测试钉住「硬上限」与「超时输出也截断」。

#### A2. `_shell_executable()` 的回退值是相对路径 —— 在它本该生效的场景下 shell 工具 100% 失效

**位置**：`loca/tools/shell.py:71-82`

**复现**（把 `%COMSPEC%` 指向 PowerShell，模拟被 launcher 改过的环境）：

```
with COMSPEC=PowerShell, _shell_executable() -> 'cmd.exe'
running a command with it gives: FileNotFoundError: [WinError 2] 系统找不到指定的文件。
（正常环境返回值：C:\Windows\system32\cmd.exe）
```

**机理**：`Popen(..., shell=True, executable=X)` 把 `X` 作为 `CreateProcess` 的
**lpApplicationName** 传给系统。该参数是**相对路径**时，Windows 只在「当前目录」找，
**不搜索 PATH 也不搜索 System32**。

**为什么是问题**：这段代码存在的唯一目的就是「`%COMSPEC%` 被换成 PowerShell / Git-Bash
时不要改变模型该写什么命令」。而恰恰在那个场景下，它返回的裸 `"cmd.exe"` 无法执行 ——
每一次 shell 调用都会返回 `Failed to execute: [WinError 2]`，agent 完全丧失执行能力。

**测试为什么没抓住**：`tests/test_shell.py` 只断言这个函数**返回的字符串**是 `"cmd.exe"`，
从不真的拿它跑一条命令。那条测试的注释写着「对 PowerShell COMSPEC 免疫」，是空头支票。
修法：回退到 `%SystemRoot%\System32\cmd.exe` 的绝对路径并校验存在。

> **✅ 已修复**（`tools/shell.py`）：新增 `_system32_exe()`，`_shell_executable()` 现在
> 只返回**已验证存在的绝对路径**，找不到就 `RuntimeError`（而不是交出一个必然失败的相对路径）。
> 那条空头测试被替换成两条：`test_shell_executable_is_always_an_absolute_cmd`（真的检查
> 返回值是绝对路径且可执行）+ `test_hostile_comspec_still_runs_commands`（把 `%COMSPEC%`
> 指向 PowerShell 后**真的跑一条命令**并断言输出）。

#### A3. 回滚遇到「同一步内多次改动同一文件」会还原成中间版本

**位置**：`loca/observability/checkpoint.py:320-344`

**复现**：同一步（step 1）内三次 `write_file`（v1 → v2 → v3）后执行 `rollback(sid, 1)`：

```
after 3 writes at step 1, disk = 'v3'
rollback(sid, 1) -> exists=True content='v2'
report.settled() = {'f.txt': 'restored'}
report.restored=['f.txt', 'f.txt'] deleted=['f.txt'] skipped=[]
```

**应该是什么**：`rollback(sid, 1)` 的语义是「撤销 step 1 及其之后的全部改动」。
这个文件是在 step 1 里才被创建的，所以正确结果是**文件被删除**。实际留下 `v2`。

**机理**：`rows.sort(key=lambda r: r.step, reverse=True)` 只按 `step` 排序；
Python 的排序是稳定的，同一步内的元素保持 SQL `ORDER BY step, id` 的**最旧优先**顺序。
于是「最新的 pre-state 先应用、最早的 pre-state 最终胜出」变成了反向 ——
与函数 docstring 第 317-318 行明确承诺的语义**正好相反**。

**为什么触发频率不低**：一次模型回复里连续调两次 `write_file` / `edit_file` 是常见形态
（循环对每个 tool_call 都 `capture`，且传的是**同一个** `global_step`）。更糟的是崩溃场景：
`capture()` 在工具执行前落库，而 `next_step` 只在整轮结束后才写，进程若在轮中被杀，
重启会**复用同一个 step**，制造大量同 step 检查点。

**报告同时失真**：`restored=['f.txt','f.txt'] deleted=['f.txt']` —— 同一个文件被列出
三种互相矛盾的动作；`settled()` 把它收敛成 `restored`，而正确答案是 `deleted`。

**现有测试**：`tests/test_checkpoint.py` 只覆盖不同 step 的 0/1 场景，**同一步无覆盖**。

**修法**：排序键改成 `(step, id)` 的复合逆序，即 `rows.sort(key=lambda r: (r.step, r.id), reverse=True)`
——但 `CheckpointRow` 目前没有 `id` 字段，需要在 `list_checkpoints` 里把 `id` 带出来。

> **✅ 已修复**：`CheckpointRow` 增加 `id` 字段（`list_checkpoints` 从 `SELECT` 里带出），
> 排序键改成 `(step, id)` 复合逆序，并把这个「为什么」写进 `rollback()` 的 docstring。
> 同一步三次写 v1→v2→v3 后 `rollback(sid, 1)` 现在得到**文件被删除**（正确语义）。
> 另外两处顺手收口：`RollbackReport.skipped` 由 `list[str]` 改成 `skips: list[tuple[str, str]]`
> （路径与原因分开存，不再靠 `split(" (", 1)` 猜），`capture()` / `_snapshot()` 各自加了
> 兜底，让检查点机制真的做到「纯观察，绝不搞死这一轮」。新增 5 条测试。

### 4.2 P2（8 项）

> **2026-09-18 更新**：下表 8 项 + 补充的 4 条（B9–B12）**全部已修复**，逐条说明见 §9。

| # | 位置 | 问题 | 证据 |
|---|---|---|---|
| **B1** | `tools/filesystem.py:104-119` | `read_file` **没有总量上限**：只有「单行 4000 字符」，行数与文件大小不限。`shell` 有 30KB/500 行/2000 字符三重上限，`read_file` 一个都没有 | 实测一个 5,000 行的文件被整份返回：**290,202 字符**。agent 读日志会直接打爆上下文预算 |
| **B2** | `observability/checkpoint.py:288-304` | `_snapshot()` 里 `read_bytes()` 不在 `try` 内（`try` 只包住 `decode`）。`stat()` 与 `read_bytes()` 之间的 TOCTOU（文件被删/权限变化）会抛 `OSError`，而 `capture` → `_capture_checkpoint` → `run()` 全程无 try | 本该「纯观察、绝不搞死这一轮」的检查点机制反而会中断任务 |
| **B3** | `providers/openai_compat.py:136-148` | OpenAI 流式 payload **不含 `stream_options={"include_usage": True}`**（全文无 `stream_options`） | 流式下 OpenAI 不返回 usage → `DONE.total_tokens` 恒 0 → `loca report` 的 token 统计在 `--provider openai` 下全是 0。与 Week 5 勾选的「三家 parity（含 usage）」冲突；离线 parity 测试用假流补了 usage 帧，结构上测不出来 |
| **B4** | `providers/openai_compat.py:176,270` | `map_finish_reason(None)` 落到字典默认值 → **`FinishReason.ERROR`**。而除末帧外**每一帧**的 `finish_reason` 都是 `None` | 实测第一帧就返回 `ERROR`。`types.py:119-129` 明确写了「消费者靠 `finish_reason` 判断流结束」—— 任何按文档写的消费者会在第一帧就停。Anthropic 侧有 `if raw_reason` 保护（`anthropic.py:319-321`），说明作者知道这个坑，OpenAI 路径漏了。副作用：`tests/test_deepseek_stream.py` 里一条断言因此**恒不成立**，退化成空断言 |
| **B5** | `tools/shell.py:166-175` | 超时路径**完全绕过截断**（对比成功路径 `:180-181` 会 `_truncate`），且把 stdout/stderr **拼接**在一起 | 一条刷屏命令超时后可以把几十 MB 灌进上下文；与 Week 2 勾选的「stdout/stderr 分离」在这条路上直接矛盾 |
| **B6** | `tools/filesystem.py:278` | `edit_file` 用 `Path.write_text`（`newline=None` → 写入时翻译换行符），**把整个文件的 LF 改写成 CRLF** | 实测 `b'alpha\nbeta\ngamma\n'` → `b'alpha\r\nBETA\r\ngamma\r\n'`。后果：改一行 → git diff 变成全文件；返回给模型的 unified diff 是在内存字符串上算的，与实际落盘不符。`write_file` 用 `newline=""` 规避了，`edit_file` 漏了 |
| **B7** | `eval/benchmark.py:622-628` | 任务集自检**把「没有参考答案」判为合格**：`ok` 只要求 `passes_with_solution is not False`，缺 solution 时该字段是 `None` | 实测一个只有 `workspace/` + `hidden/`、没有 `solution/` 的题 → `has_solution=False` 但 `ok=True`。Week 6 勾选的「逐题确认『起始判不过 + 参考解判得过』」对这类题不成立 |
| **B8** | `eval/benchmark.py:161,272` + `cli.py` | 归档报告不记录模型名：`BenchmarkReport.model` 来自 `--model`（默认 `None`），`docs/benchmarks/deepseek-36.json` 里 `"model": null` | README 与简历都写「DeepSeek 默认模型」，但这份**证据文件本身不能证明**用的是哪个模型。对以「可复现」为卖点的报告是硬缺口 |

补充两条同类（不单列）：

- **B9 `recoveries` 计数了但不落盘** —— `TaskResult.recoveries` 从 `RECOVERY` 事件累加，
  `to_dict()` 不含该字段。实测 `recoveries=7` 时 `to_dict()` 里查无此键。
- **B10 trace 的「重试次数」语义是错的** —— `trace.py:418-420` 把 `EventType.RECOVERY`
  计成 `retries`，而 `RECOVERY` **只在输出被长度截断时**发出（`loop.py:270-273`）。
  provider 的瞬时失败重试发生在 `RetryingProvider` 内部，它提供了 `on_retry` 钩子
  但 loop 构造时没接（`loop.py:118-120`），`RetryingProvider.retry_count` 除测试外无人读。
  所以 `loca report` 里报的「重试次数」实际是「续写次数」。
- **B11 `sessions rm` 报的 checkpoint 数恒为 0** —— `cli.py:510-516` 先 `delete_session()`
  再 `list_checkpoints()`，级联已清空。实测 before=1 → after=0。同一条命令也不删 JSONL 镜像，
  `loca report` 之后仍能从磁盘兜底读到，与「trace(s) removed」的提示不一致。
- **B12 超时检查会覆盖成功完成** —— `benchmark.py:410-412` 的 deadline 检查排在
  `DONE` 分支**之前**，且 `break` 后不再处理事件。一个刚过 deadline 但已经跑完的尝试
  会被记成 `timeout`，且 `steps=0 / tokens=0`（成本被低估），判分器不再运行。

### 4.3 P3（11 项）

> **2026-09-18 更新**：C1–C11 **全部处理完毕**（其中 C9 的 `Usage.reasoning_tokens`
> 经复核判定**不是死代码**，保留并说明，见 §9）。

| # | 位置 | 问题 |
|---|---|---|
| **C1** | 简历 / README | **「评测集 128 个文件 / 5,994 行」的口径会误导**。实测：128 = 124 个夹具 `.py` + **4 个生成脚本**；5,994 = 2,510 + **3,484**。也就是说这个数字**排除了 36 个 `task.json`**（591 行，含题面 —— 恰恰是任务集最核心的部分），而**58% 是生成脚本的代码**。真实夹具规模是 **161 文件 / 3,103 行**。建议改成「36 题 / 161 个夹具文件 / 3,103 行（另有 4 个一次性生成脚本 3,484 行）」 |
| **C2** | `README.md` | launch.json 配置表**少了 2 个**：文件里共 9 个，README 只列了 7 个（缺 `loca chat --session (resume)`、`loca sessions (list)`） |
| **C3** | `pyproject.toml:236` | `requires-python = ">=3.11"`，而 README / roadmap / 简历都反复写「Python 3.13+」。代码确实只用到 3.11+ 的特性，所以是**文档更严、包声明更松**的矛盾 |
| **C4** | `observability/trace.py:202` | `StepTrace.reasoning` 是**声明了但从不写入**的死字段（赋值点 0 个），`loop.py` 也从不把 `delta_reasoning` 发成事件。而 roadmap:236 与 README:79 都写着「记录推理内容」 |
| **C5** | `observability/checkpoint.py:174` | `settled()` 对本来干净的路径做 `split(" (", 1)[0]`。实测 `docs/report (final).md` → `{'docs/report': 'restored'}`。那段 split 是多余的（`actions` 存的始终是干净的 `snapshot.path`） |
| **C6** | `eval/benchmark.py:494-499` | `run_benchmark` 的 docstring 说「跑崩了会保留 `workdir` 供排查」，实现是 `finally: if not keep: rmtree(...)` —— **永远删**。文档与实现不符 |
| **C7** | `tools/filesystem.py:4-5` | docstring 写「This stops the model from reading `C:\Users\nono\.ssh\id_rsa` even if it tries」，但 `shell.py:8-11` 明说 shell **故意不沙箱**。作为整项目安全声明它不成立（`type C:\Users\nono\.ssh\id_rsa` 一句就绕过）。另外把开发者本机用户名硬编码进了公开仓库的 docstring |
| **C8** | `loca_roadmap.md:47` | Week 1 第 5 条「OpenAIProvider / AnthropicProvider **stub**（抛 `NotImplementedError`）」已过时：全仓库（排除夹具）**已无 `NotImplementedError`**，Week 5 改成了完整实现 + `ValueError`。历史日志可保留，但应加注 |
| **C9** | 多处 | **死代码**：`SessionStore.delete_checkpoints`、`CheckpointManager.list_checkpoints`、`trace.iter_steps`（还在 `__all__` 里导出）、`tools/registry.get()`、`ChatRequest.stream`、`Usage.reasoning_tokens` —— 均无生产调用点 |
| **C10** | `observability/trace.py:526-535` | `_persist` 用 `except Exception: pass` **静默吞掉**数据库异常，连 `_log.warning` 都没有。observability 自己出问题却完全不可观测，用户会以为有轨迹其实没有 |
| **C11** | `scripts/debug_e2e.py` | 一个自述「One-off debug」的脚本留在 `scripts/` 里（README 的目录表只写了 `interactive_chat.py`），且它调真实 API。要么补进文档，要么移走 |

---

## 5. 计划书需要更正的地方

1. **Week 1 第 5 条**（`NotImplementedError` stub）—— 加注「Week 5 已被完整实现取代」。
2. **Week 2 的测试数「shell 13 项」** —— 现在是 18 项。
3. **Week 4 的「会话库可跨机器/盘符迁移」** —— 检查点存的是相对 POSIX 路径（这一点成立），
   但 `rollback` 不传 `--workspace` 时会用**录制时的绝对 workspace**（`checkpoint.py:338`），
   换台机器后会在新机器上凭空创建旧盘符目录树。这条卖点没有真正兑现，应加限制说明。
4. **Week 6 的「任务集自检」描述** —— 应补一句「缺参考答案的题目前不会被判为不合格」，
   或干脆修掉（B7）。
5. **整体进度表** 可以保持全绿 —— 六周目标确实都达成了。

---

## 6. 值得肯定的设计

审查不是只找毛病，以下这些是真做得好的地方：

1. **评测的信任基础是真的**。`hidden/` 判分文件对模型不可见、判分前覆盖回沙箱，
   有专门的测试钉住「模型改自己的测试文件无效」。**行为式判分**（跑 pytest / 比 stdout /
   调校验脚本）而不是 diff 判分，让「另一种正确写法」也能得分。
2. **任务集自检这个想法很对**。`loca bench verify` 不需要 provider、不花 token，
   却能挡住两种最隐蔽的坏题（起始就通过、参考解都过不了）。36/36 通过，
   25.6 秒跑完，可以当作常规维护的一部分。
3. **七类 outcome 分开记**，并把 `grader_error`（出题人的 bug）从「模型不行」里摘出来。
   这是很多自建 benchmark 都会糊掉的地方。
4. **SSE 流不被错误掐断**。不可恢复的 provider 异常转成 `error` 事件而不是抛出，
   传输层始终是良构的。
5. **重试的流式语义处理得很干净**。「只在首个分片到达前重试」用生成器表达，
   而不是硬套通用重试库 —— 这个取舍在 roadmap 里写了理由，代码也真的是这么写的。
6. **三个真实的跨进程 bug 是被手工跑出来的，不是单测发现的**（步数计数器重启归零、
   同一秒创建会话排序错乱、评测 runner 漏传 budget）。这说明作者知道单测的边界在哪。
7. **路径沙箱经得起实测**。`..`、相似前缀陷阱、`\\?\` 前缀、junction 展开全部拒绝，
   且返回的是**解析后**的路径（检查与操作同一个值，没有「检查 A 写 B」的经典漏洞）。
8. **Anthropic 的纯函数翻译层**做到了不发网络请求就能完整测试（33 项），
   这是协议适配层最该有的形态。

---

## 7. 建议的修复顺序

**第一梯队（会在真实使用中造成错误行为，建议尽快）**

1. **A3 回滚同步排序** —— 修法明确（复合排序键 + 把 `id` 带出来），风险低，收益高。
   顺手补一条同一步多次改动的测试。
2. **A1 shell 超时整树杀** —— Windows 上用 `taskkill /F /T /PID` 或 Job Object。
3. **A2 shell 回退路径** —— 一行改成绝对路径；**并把测试改成真的跑一条命令**
   （现在的测试只检查字符串，等于没测）。

**第二梯队（数据损失 / 声明不实，影响可信度）**

4. **B8 报告记录模型名** —— 重跑一次基准并把 `model` 落到 JSON。
   这是简历数字的**证据链**，优先级比看起来高。
5. **B6 `edit_file` 换行符** —— 改成 `open(..., newline="")`，与 `write_file` 对齐。
6. **B4 `finish_reason=None`** —— 改成只在末帧映射，其余保持 `None`。
   顺带修回那条退化成空断言的测试。
7. **B3 OpenAI `stream_options`** —— 补上（对 vLLM/Ollama 这类网关建议按 provider 开关）。
8. **B7 自检缺 solution** —— 把「没有参考答案」也算作不合格。
9. **B1 `read_file` 总量上限** —— 参照 `shell` 的三重上限。
10. **B2/B5** —— `read_bytes()` 包进 try；超时路径也走 `_truncate` 并分离两个流。

**第三梯队（文档一致性，可以合并成一次提交）**

11. C1 数字口径、C2 launch.json 表、C3 `requires-python`、C4 死字段、
    C5 `settled()`、C6 docstring、C7 沙箱措辞、C8 roadmap 加注、C9 死代码清理、
    C10 加日志、C11 脚本归位。

> **关于已归档的跑分**：本次发现的 P1/P2 都**不影响** `pass@1 = 91.7%` 这个数字 ——
> 那一轮用的是 DeepSeek，36 题全部在 67 秒墙钟内跑完（远未触碰超时），
> 也没有走 `rollback` 路径。所以简历上的数字可以继续用；但 B8（模型未记录）
> 会削弱它的「可复现」说服力，建议修完后重跑一次并重新归档。

---

## 8. 附录：审查脚本

全部在 `.workbuddy/scratch/`（gitignored，ruff 也会跳过），可重跑：

| 脚本 | 作用 |
|---|---|
| `audit_inventory.py` | 代码库盘点：模块/行数/docs/git 状态/密钥安全 |
| `audit_numbers.py` | 用多套口径复算文档里引用的每个数字，定位它来自哪种算法 |
| `audit_repro.py` | 第一轮复现：9 条关键结论（8 条 REPRO） |
| `audit_f6.py` | 专门复现「同一步回滚」问题（A3） |
| `audit_final.py` | ruff + 全量测试 + `bench verify` + CLI 面 + 数字核对（结果落 `%TEMP%`） |
| `audit_round2.py` | 第二轮复现：shlex / 截断 / 死字段 / settled / verify / to_dict |

> ⚠️ **跑测试时 basetemp 必须指到 `%TEMP%` 下的全新路径**。IDE 的 `safe-delete`
> 守卫会拦掉**项目目录内**的删除（按每轮累计删除数计数，超 50 就要求确认，
> 非交互时抛 `SystemExit: 1`），表现是「在项目目录里跑 pytest 会莫名其妙挂一大片测试」。
> 看起来像代码 bug，其实完全不是。

---

## 9. 修复记录（2026-09-18）

**范围**：本报告的全部 26 项缺陷（P1 3 + P2 12 + P3 11），一次性修完。
**唯一例外**：B8（归档报告不记录模型名）**只改代码路径、不重跑基准** ——
重跑一轮 36 题要花真钱，而 `model` 字段的修法与跑分数据本身无关；
`docs/benchmarks/deepseek-36.json` 里那个 `"model": null` **仍然是 null**，
这一点在 9.5 单独说明。

### 9.1 P1（3 项）

| # | 改动文件 | 修法 | 验证 |
|---|---|---|---|
| A1 | `loca/tools/shell.py` | `execute()` 改走新的 `_run_command()`：`Popen(CREATE_NEW_PROCESS_GROUP)` + 两个守护线程分别抽干 stdout/stderr，`wait(timeout)` 超时后 `_kill_process_tree(pid)`（`taskkill /F /T /PID`）再收尾 | 复现脚本同一场景 **8.09s → 2.24s**；事后用 PowerShell `Get-CimInstance Win32_Process` 按命令行匹配 `time.sleep(30)`，残留 **0** |
| A2 | `loca/tools/shell.py` | 新增 `_system32_exe()`；`_shell_executable()` 只返回**已验证存在的绝对路径**（`%COMSPEC%` → `%SystemRoot%\System32\cmd.exe`），两者都不可用则 `RuntimeError` | 把 `%COMSPEC%` 指向 PowerShell 后**真的运行一条命令**并断言输出；另断言返回值是绝对路径且 `is_file()` |
| A3 | `storage.py` + `checkpoint.py` | `CheckpointRow` 补 `id` 字段并带出；`rollback()` 排序键改成 `(step, id)` 复合逆序，理由写进 docstring | 同一步 v1→v2→v3 后 `rollback(sid, 1)` → 文件**被删除**（原为留下 `v2`） |

顺带修掉 A3 报告层的同源问题：`RollbackReport.skipped` 由 `list[str]` 改成
`skips: list[tuple[str, str]]`（路径 / 原因分开存），`settled()` 不再靠
`split(" (", 1)` 猜；`capture()` 与 `_snapshot()` 各自补了兜底（C5 / B2）。

### 9.2 P2（12 项）

| # | 改动文件 | 修法 | 验证 |
|---|---|---|---|
| B1 | `tools/filesystem.py` | `read_file` 加 `_MAX_LINES = 2000` + `_MAX_BYTES = 100_000`，截断提示给出 `start_line=N` 续读办法 | 两条新测试：行数上限、以及「每行都合法但总量超限」 |
| B2 | `observability/checkpoint.py` | `_snapshot()` 的 `read_bytes()` 包进 try（TOCTOU → `UNAVAILABLE`）；`capture()` 落库失败不再抛 | 两条新测试：文件在 `stat` 与 `read` 之间消失、store 拒写 |
| B3 | `providers/openai_compat.py` | 流式 payload 补 `stream_options={"include_usage": True}`，并加 `LOCA_*_STREAM_USAGE` 开关（默认开） | 三条新测试：流式请求带该字段 / 关掉后不带 / 非流式永不带 |
| B4 | `providers/openai_compat.py` | `parse_stream_chunk` 只在 `finish_reason` 为真时映射，否则保持 `None` | 新测试断言首帧 `None`、usage 帧能到消费者 |
| B5 | `tools/shell.py` | 超时路径也走 `_truncate`；stdout / stderr **分开**渲染（不再拼接） | 新测试：超时且刷屏时输出被截断 |
| B6 | `tools/filesystem.py` | `edit_file` 按原文件探测换行符并用 `newline=...` 写回；查找时两边都归一到 LF | 三条新测试：保留 LF / 保留 CRLF / 用 LF 串匹配 CRLF 文件 |
| B7 | `eval/benchmark.py` | `TaskIntegrity.ok` 现在要求 `passes_with_solution is True`（不再接受 `None`） | 重写原测试为「缺 `solution/` 必须判不合格」 |
| B8 | `providers/base.py` + `core/recovery.py` + `eval/benchmark.py` | 新增 `resolved_model` 属性（重试包装类透传）；`run_benchmark` 在 `model is None` 时探测并记录，探测失败只 `_log.warning` | 三条新测试：记录默认模型 / 显式 `--model` 优先 / 探测失败不中断 |
| B9 | `eval/benchmark.py` | 计数拆成 `retries` + `continuations`，并写入 `to_dict()` | 新测试断言两个计数都落盘 |
| B10 | `core/loop.py` + `core/recovery.py` + `trace.py` + `reporter.py` + `cli.py` + `web/` | ① `RetryingProvider` 的 `on_retry` 钩子接进循环，发 `RECOVERY reason="provider_retry"`；② trace / reporter 把「续写」与「重试」分开累计（`continuations` / `retries`）；③ `_derive_finish` 优先级：error > recovered > continued > tool_use > stop | 两条新测试：重试被吸收时事件流里可见 / 重试耗尽时先报事件再报 ERROR |
| B11 | `loca/cli.py` | `sessions rm` **先数后删**（原来先删再数，恒为 0）；并显式删除 JSONL 镜像（`_remove_trace_mirror()`） | 两条新测试：报告的数量真是删掉的数量 / 镜像文件也没了 |
| B12 | `eval/benchmark.py` | deadline 检查从 `DONE` 分支**之前**挪到**之后** | 新测试「刚过 deadline 但已跑完的尝试必须判分而不是记 timeout」；**并把修法临时改回去确认该测试会失败**，再改回 |

### 9.3 P3（11 项）

| # | 改动 | 说明 |
|---|---|---|
| C1 | 文档 | 评测集口径统一为 **36 题 / 161 个夹具文件 / 3,103 行**（另有 4 个一次性生成脚本 3,484 行）。复核后确认 README 与简历里其实已经没有那个旧数字，剩下的是本报告的问题描述（保留） |
| C2 | `README.md`（中英） | launch.json 配置表补齐 `loca chat --session (resume)` / `loca sessions (list)`，9 条与文件一致 |
| C3 | `pyproject.toml` | `requires-python` 由 `>=3.11` 改成 `>=3.13`，并写明理由（没人测过的下限就是没人守的承诺） |
| C4 | `core/loop.py` · `core/events.py` · `trace.py` · `web/` | 循环把 `delta_reasoning` 发成 `TEXT_DELTA` 的独立通道；trace 累积进 `StepTrace.reasoning` 且不污染 `text`；Web GUI 渲染成「thinking」 |
| C5 | `checkpoint.py` · `cli.py` | 见 9.1 末尾（`skips` 二元组） |
| C6 | `eval/benchmark.py` | `run_benchmark` docstring 改口：sandbox 在 `finally` 里总是被删，「保留供排查」的说法不成立 |
| C7 | `tools/filesystem.py` | 沙箱声明收窄为「文件工具的路径沙箱」，并明说 shell 不在此列；删掉硬编码的 `C:\Users\nono\...` |
| C8 | `loca_roadmap.md` | Week 1 第 5 条的 `NotImplementedError` stub 加「已过时」批注（历史保留，不代表当前代码） |
| C9 | `storage.py` · `checkpoint.py` · `trace.py` · `tools/registry.py` · `providers/types.py` | 删除无调用点的 `SessionStore.delete_checkpoints`、`CheckpointManager.list_checkpoints`、`trace.iter_steps`（连 `__all__`）、`tools/registry.get()`、`ChatRequest.stream`（连 2 处生产写入 + 4 处测试写入）。**`Usage.reasoning_tokens` 经复核判定不是死代码**：它在 `openai_compat.py` 被真实赋值，只是还没上浮到报告层，删掉等于丢弃 provider 已给出的数据 —— 保留并记录在此 |
| C10 | `observability/trace.py` | `_persist` 的两个 sink 各自 `_log.warning`，告警点明「哪一路丢了哪一步」；不再静默 `pass` |
| C11 | `scripts/` → `.workbuddy/scratch/` | 自述 one-off 的 `debug_e2e.py` 移出仓库（gitignored + ruff 跳过），`scripts/` 只剩 README 里写过的 `interactive_chat.py` |

### 9.4 回归验证

| 项 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check .` | 全绿 |
| 离线测试 | `pytest -m "not live"` | **426 passed, 0 skipped**（修复前 397 passed + 1 skipped） |
| 联网测试 | `pytest -m "live"` | **8 passed**（真实 DeepSeek 调用；改完后重跑过一次，全过） |
| 任务集自检 | `loca bench verify` | **all 36 task(s) check out** |
| 兼容性 | 新旧会话库 / 旧 JSONL | `CheckpointRow.id` 是 SELECT 新增列，`StepTrace` 新字段走 `to_dict` / `from_dict` 默认值，**旧数据照读** |

修复过程新增 **28 项**测试，逐条对应上表的验证列。原来那唯一一条条件跳过
（`no .bashrc on this system`）被重写成「在 `tmp_path` 之外造一个真实存在的文件」
—— 跳过项归零，而不是把断言删掉。

### 9.5 没做的事（明确声明）

1. **没有重跑基准**（B8 只改代码路径）。所以：
   - `docs/benchmarks/deepseek-36.json` 里 `"model": null` **仍然是 null**；
   - 简历上的 `pass@1 = 91.7%` 继续有效（三个 P1 都不在那一轮的路径上：
     36 题全在 67 秒墙钟内跑完、没触发 shell 超时、没走 `rollback`），
     但**这份证据文件仍然无法自证模型名**。要彻底闭环，需要重跑一轮并重新归档。
2. **没有用真实 API 跑基准**（但联网 e2e 那 8 项重跑过、全过）。
   基准的 36 题要花真钱，且 B8 的修法与跑分数据无关；
   改动涉及的 `openai_compat.py` 流式 payload 与 `loop.py` 事件发射，
   已由重跑的 8 项 live e2e + 19 项离线 parity 覆盖。
3. **`git` 未提交**。本次只改工作区。

### 9.6 数字口径（修复后，可复算）

| 项 | 数字 | 口径 |
|---|---|---|
| harness 源码 | **8,380 行 / 31 个模块** | `loca/**/*.py` 排除 `loca/eval/tasks/` |
| 测试 | **7,520 行 / 21 个文件 / 434 项** | `tests/**/*.py`；离线 426 + 联网 8 |
| README | **450 行** | 中英双语同一文件 |
| 6 篇中文指南 | **1,650 行** | `docs/*.md` 去掉简历 / 面试手册 / 本报告 |
| 评测集夹具 | **161 个文件 / 3,103 行** | `loca/eval/tasks/`，不含 `_generate/` 下 4 个脚本（3,484 行） |

复算脚本（`.workbuddy/scratch/`，gitignored）：`recount_all.py`（上面这张表）·
`count_tests.py`（三种分流的用例数）· `audit_c1_numbers.py`（评测集文件 / 行数分组）·
`run_full.py` / `run_files.py`（ruff + pytest + JUnit 汇总）。

---

*本报告由审查脚本生成的证据支撑，所有「复现」结论均在本机实测。*
*§9 的修复记录同样逐条实测，复算脚本在 `.workbuddy/scratch/`。*
