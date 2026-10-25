# 执行轨迹与报告机制（Trace 与 loca report）

> [!NOTE]
> 本文介绍 Loca 运行时底座的全链路执行轨迹（Trace）机制与 `loca report` 诊断命令。通过该机制，开发者可以精确复盘 Agent 的每一步模型推理、工具调用耗时、上下文状态迁移及 Token 资源开销。

---

## 一、会话与执行轨迹的设计定位

在 Loca 中，**会话（Session）** 与 **执行轨迹（Trace）** 承担着不同维度的系统职责：

| 比较维度 | 会话持久化（Session） | 执行轨迹（Trace） |
| :--- | :--- | :--- |
| **关注核心** | **对话交互内容**（说了什么） | **执行过程与资源开销**（做了什么、耗时与成本） |
| **记录粒度** | 完整的上下文消息流（`system` / `user` / `assistant` / `tool`） | 每个“模型步（Step）”的诊断元数据、提示词摘要、工具耗时与 Token 指标 |
| **存储介质** | SQLite 会话库（`sessions`、`messages` 表） | SQLite 关系存储（`traces` 表）+ 纯追加文本镜像（`.jsonl` 文件） |
| **查看命令** | `loca sessions show <session_id>` | `loca report [session_id]` |

### 分离存储的架构考量
会话记录包含工具执行返回的原始上下文（如多文件读取结果可能达到数十 KB），是驱动多轮对话重放（Replay）与上下文压缩的必要依据。而执行轨迹专注于运行时的可观测性与度量分析，通过提炼步骤摘要与性能指标，使得数据增长率较原始对话降低一个数量级。分离存储既避免了高频轨迹分析对会话核心表的性能干扰，又保障了全链路复盘的高效性。

---

## 二、轨迹数据模型与单步记录规范

在 Loca 架构中，一个“模型步（Step）”代表循环内的一次模型交互与后续工具执行闭环。每一步记录包含以下核心字段：

| 字段名称 | 类型 | 说明 |
| :--- | :--- | :--- |
| `step` | `int` | 会话内的单调递增步号（与状态回滚命令 `loca rollback` 保持一致）。 |
| `prompt_messages` | `int` | 本步输入给模型的上下文消息总条数。 |
| `prompt_chars` | `int` | 本步输入上下文的总字符数近似统计。 |
| `prompt_tail` | `str` | 本步输入上下文中最后一条消息的开头摘要（用于快速辨识模型所响应的直接输入）。 |
| `text` | `str` | 本步模型生成的正文内容。 |
| `reasoning` | `str` | 本步模型输出的思考链内容（针对支持深度推理的模型，如 DeepSeek R1）。 |
| `tool_calls` | `list` | 本步模型调用的工具列表，包含工具名称与具体参数。 |
| `tool_results` | `list` | 工具执行结果摘要、执行成功/失败状态（`is_error`）及各工具执行耗时。 |
| `prompt_tokens` | `int` | 本次模型调用计费的输入 Token 数。 |
| `completion_tokens` | `int` | 本次模型调用生成的输出 Token 数。 |
| `duration_ms` | `float` | 本步全流程总耗时（含模型往返时延与所有工具执行耗时）。 |
| `finish_reason` | `str` | 本步的结束状态分类（详见下文）。 |
| `error` | `str` | 若出现瞬时重试耗尽或致命故障，记录具体的错误信息。 |
| `retries` | `int` | 因首包异常或输出长度截断而自动触发的重试/续写次数。 |
| `context` | `str` | 本步触发的上下文压缩事件摘要（如滑动裁剪或语义摘要压缩）。 |
| `checkpoints` | `list` | 本步执行写操作前拍摄的文件快照路径列表。 |

### Prompt 存储策略：摘要与结尾片段
完整的 Prompt 已由会话库中的 `messages` 表完整持久化。为避免轨迹数据导致磁盘空间翻倍及跨表数据冗余，轨迹表仅记录 Prompt 的整体形态（条数、字符规模）与末尾片段（`prompt_tail`）。该策略既能提供清晰的定位上下文，又将存储开销降至最低。

同理，单次工具调用的返回内容在轨迹中默认保留 **前 800 字符预览** 并记录实际总长度。

### 结束原因（finish_reason）分类逻辑
底座执行循环仅在整轮对话结束时生成总体 `DONE` 事件。因此，轨迹中记录的中间步 `finish_reason` 是由事件收集器综合状态推导出的分类标识：
- `tool_use`：模型决定调用一个或多个工具；
- `recovered`：模型生成因长度超限截断后，系统成功完成自动无缝续写；
- `error`：模型调用异常或瞬时故障重试耗尽；
- `stop`：模型输出完毕且未调用新工具。

---

## 三、数据存储架构：SQLite 与 JSONL 双写冗余

Loca 采用 **关系型数据库 + 本地纯文本** 的双写冗余架构：

```
~/.loca/
├── sessions.db             # 主 SQLite 会话库（含 sessions, messages, traces 表）
└── traces/
    ├── <session_id>.jsonl  # 纯追加流式轨迹镜像
    └── ...
```

1. **SQLite 存储**：保存在会话数据库所在目录下的 `traces` 表中，与关联会话生命周期绑定（执行 `loca sessions rm <session_id>` 时联动清除）。
2. **JSONL 镜像**：保存在 `<db_dir>/traces/<session_id>.jsonl` 中，单步成行，支持标准命令行工具（如 `grep`、`jq`、`awk`）流式检索。

> [!TIP]
> **容灾保障**：若 SQLite 数据库被清理或迁移，只要本地 `.jsonl` 镜像文件存在，`loca report` 依然能够无缝读取并完整渲染报告，此时报表顶部的 `trace source` 字段将明确指示为 `jsonl`。

### 自定义存储路径
若需自定义轨迹文件的落地位置，可通过以下方式进行配置：
- 设置环境变量 `LOCA_TRACE_DIR` 指定专属目录：
  ```powershell
  $env:LOCA_TRACE_DIR = "D:\loca-traces"
  ```
- 通过 `--db` 参数指定会话库路径，轨迹目录将自动放置在会话库同级目录下的 `traces\` 中：
  ```powershell
  python -m loca.cli chat --session demo --db "D:\loca\sessions.db"
  # 轨迹文件将自动落入 D:\loca\traces\demo.jsonl
  ```

---

## 四、操作指南：生成与查看轨迹报告

### 1. 默认自动记录
只要启动 CLI 时未显式传入 `--no-save`，轨迹采集系统将默认处于激活状态。启动交互时控制台会输出采集指引：

```text
loca · provider deepseek · 5 tool(s) · workspace D:\Projects\loca\playground
session w5-demo (new) · db D:\Projects\loca\playground\sessions.db
tracing to D:\Projects\loca\playground\traces\w5-demo.jsonl
Type 'exit' to quit · /help for commands.
```

- 若需在单次会话中关闭轨迹采集，可传入参数：
  ```powershell
  loca chat --no-trace
  ```
- 在 REPL 交互过程中，可随时输入快捷指令查看当前已采集的步数：
  ```text
  you › /trace
  ```

### 2. 查看会话摘要报告
使用 `loca report` 命令可查看指定会话的格式化诊断报表：

```powershell
loca report w5-demo --db "D:\Projects\loca\playground\sessions.db"
```

典型报表示例：

```text
loca report · w5-demo
Create a file named hello.py containing a print of the exact text "hell…
workspace     D:\Projects\loca\playground
provider      deepseek
created       2026-10-25T09:27:17+00:00
updated       2026-10-25T09:27:18+00:00
messages      6
trace source  database

summary
  steps      2 model call(s) · 1,266 tokens/step average
  tokens     2,532 total (2,400 prompt · 132 completion)
  time       1.4s model · 90ms tools
  tools      2 call(s) · 0 error(s) (0%)

tools
tool        calls  errors  time   avg
bash            1       0  85ms  85ms
write_file      1       0   5ms   5ms

steps
step   time  tokens  tools              finish    note
   0  936ms   1,205  write_file, bash   tool_use
   1  567ms   1,327  —                  stop

files snapshotted (restorable with `loca rollback`)
  hello.py
```

> [!NOTE]
> 若执行 `loca report` 时不指定 `session_id`，系统会自动读取最近一次更新的会话记录。诊断提示信息通过 `stderr` 输出，避免污染重定向管道。

### 3. 查看步骤详情（--verbose）
若需深入分析模型在各步骤中的思考过程与工具调用参数，可添加 `-v` 或 `--verbose` 参数：

```powershell
loca report w5-demo --verbose
```

输出将展开展示每一步的上下文构成、模型生成的具体文本/思考、调用参数及返回预览：

```text
step 0 (936ms)
  prompt 2 message(s), 457 chars
  └─ [user] Create a file named hello.py containing a print of the exact text
"hello from loca", then run it with the bash tool and quote its output.
  reply  I'll create the file and run it.
  → write_file(path='hello.py', content='print("hello from loca")\n')
  → bash(command='python hello.py')
  ✓ write_file 84 chars · 5ms
     Successfully wrote 25 bytes to D:\Projects\loca\playground\hello.py (new file)
  ✓ bash 140 chars · 85ms
     <bash command="python hello.py" cwd=D:\Projects\loca\playground exit_code=0 ...>

step 1 (567ms)
  prompt 5 message(s), 713 chars
  └─ [tool] <bash command="python hello.py" ...> --- stdout --- hello from loca
  reply  Done. Created `hello.py` ... Output: ``` hello from loca ```
```

### 4. 导出结构化数据（--json）
针对自动化评测与 CI/CD 统计管道，可通过 `--json` 选项导出纯 JSON 格式：

```powershell
loca report w5-demo --json > report.json
```

导出的 JSON 数据结构规范如下：

```json
{
  "session": {
    "id": "w5-demo",
    "title": "Create a file named hello.py...",
    "workspace": "D:\\Projects\\loca\\playground",
    "provider": "deepseek",
    "model": "deepseek-chat",
    "messages": 6
  },
  "source": "database",
  "summary": {
    "steps": 2,
    "total_tokens": 2532,
    "tokens_per_step": 1266.0,
    "model_ms": 1413.0,
    "tool_ms": 90.0,
    "tool_calls": 2,
    "tool_errors": 0,
    "error_rate": 0.0,
    "failures": 0,
    "retries": 0,
    "compactions": 0,
    "trims": 0,
    "files": 1
  },
  "tools": [
    { "name": "bash", "calls": 1, "errors": 0, "error_rate": 0.0, "duration_ms": 85.0 },
    { "name": "write_file", "calls": 1, "errors": 0, "error_rate": 0.0, "duration_ms": 5.0 }
  ],
  "steps": [ ... ],
  "checkpoints": [ ... ]
}
```

### 5. 分页与数量限制（--limit）
对于长轮次的大型会话，可通过 `--limit` 限制展示的步骤数量（默认 `0` 表示完整展示）：

```powershell
loca report w5-demo --limit 5
```

---

## 五、核心度量指标解读

- **模型耗时与工具耗时（Model vs Tool Time）**：  
  在指标计算中，模型往返时延与工具执行耗时为**互斥统计**。步骤总耗时 `duration_ms` 减去本步包含的所有工具执行耗时后，才计为“模型推理耗时”，从而避免多工具调用时耗时被重复累计。
- **Token 规模累积机制**：  
  在多轮对话中，由于每一步均需要将完整的历史上下文回传给模型，Prompt Token 会随轮次递增。当接近配置的上下文上限时，系统将调度自适应摘要压缩，这一过程将在步骤备注中被明确标注。
- **工具错误率与自愈判断**：  
  错误率由工具返回 `is_error=True` 的调用占比决定。在 Coding Agent 运行中，模型常采用“探索-试错-修复”策略，因此孤立的工具报错并不等同于任务失败，关键应关注模型是否在后续步骤中基于错误反馈自我修复。
- **恢复标记（recovered）**：  
  当步骤结束原因为 `recovered` 时，表明模型生成因撞击输出 Token 阈值被阶段性截断，Loca 运行时已自动注入续写指令并完成了内容缝合。

---

## 六、使用限制与边界说明

- **Web GUI 模式不写入 Trace 报告**：  
  虽然 Web GUI 与 CLI 共享底层的 SQLite 会话数据库（`~/.loca/sessions.db`）以支持会话持久化与一键快照撤销，但目前 Web 服务端默认未挂载 `TraceCollector` 收集器。如需采集逐步运行指标并使用 `loca report`，请通过 CLI 交互模式运行。
- **临时体验模式（`--no-save`）不留痕**：  
  当启动 CLI 时传入 `--no-save` 参数，系统将在纯内存中运行，不写入数据库且不保留磁盘镜像，因此无法生成后续轨迹报告。
- **JSONL 的记录粒度为单步（Step）**：  
  JSONL 镜像文件以单次模型调用（Step）为行单位追加。在一轮用户对话中，若模型连续进行了 3 次工具调用尝试，JSONL 中将新增 3 行记录。
- **轨迹与系统诊断日志的分工**：  
  轨迹专注于业务逻辑、模型表现与耗时统计；若需排查底层网络连接超时、Uvicorn 协议错误等底层异常，应直接查阅控制台的 `stderr` 输出。

---

## 七、常见问题解答 (FAQ)

### Q：运行报告显示 `no trace recorded for this session`？
**原因与处理**：该会话可能使用了 `--no-trace` 或 `--no-save` 模式运行，或者创建于早期尚未集成 Trace 收集器的版本。重新启动一次标准 CLI 会话即可自动生成。

### Q：报告中显示 `trace source jsonl` 是什么意思？
**原因与处理**：这表明 SQLite 数据库中缺少该会话的轨迹记录，但系统在 `traces/` 目录下成功定位到了同名的 `.jsonl` 镜像文件并完成了数据重建。这属于正常容灾机制，数据未受损失。

### Q：生成的轨迹文件存放在哪？
**原因与处理**：默认存放在会话数据库同级目录下的 `traces\` 子目录中（默认路径为 `~/.loca/traces/`）。如需固定路径，可预先配置环境变量 `set LOCA_TRACE_DIR=...`。

### Q：使用 `--json` 导出时，前面出现非 JSON 提示文字？
**原因与处理**：若未显式指定 `session_id`，系统向 `stderr` 打印了默认选择最新会话的提示语。在自动化重定向时，使用标准管道过滤即可获得纯净 JSON：
```powershell
python -m loca.cli report --json 2>$null > report.json
```

### Q：报告中的快照文件（files）为空？
**原因与处理**：表明该会话各步骤中仅执行了只读操作（如 `read_file`）或 Shell 命令（`bash` / `powershell` 不拍摄全量工作区快照），未触发任何针对具体文件的原子快照保存。

### Q：会话被删除后，对应的 `.jsonl` 文件仍然存在？
**原因与处理**：这是符合预期的容灾策略。`loca sessions rm` 仅负责清理数据库记录，纯文本 `.jsonl` 镜像独立留档供事后排查，如需彻底清除可手动删除文件。

---

## 八、相关资源

- [会话持久化、检查点与快照回滚机制](sessions-and-rollback.md) — 了解 SQLite WAL 事务与原子快照原理
- [CLI 终端运行与交互指南](running-the-cli.md) — 掌握交互参数与 REPL 快捷指令
- [Web GUI 架构与排错指南](running-the-web-gui.md) — 了解浏览器单页应用的推流与会话边界
- [自动化行为评测基准指南](benchmark.md) — 了解 36 道实战任务集的评测与判分标准
