# 轨迹与报告（Trace 与 `loca report`）

> 本文写给**要搞清楚「这次 agent 到底干了什么」的人**。
> 所有命令和输出都在 Windows + cmd.exe 上实测过，不是示意。

---

## 一、先说清楚：会话和轨迹不是一回事

loca 里有两个东西，很容易混：

| | 会话（session） | 轨迹（trace） |
|---|---|---|
| 回答的问题 | **说了什么** | **做了什么、花了多少** |
| 存的是什么 | 完整的消息记录（system / user / assistant / tool） | 每一个「模型步」的摘要：prompt 长什么样、回了什么、调了哪些工具、用了多少 token、耗了多久 |
| 在哪 | `sessions` / `messages` 表 | `traces` 表 + 一个 `.jsonl` 文件 |
| 怎么看 | `loca sessions show <id>` | `loca report <id>` |

为什么要分开？因为它们**增长速度差一个数量级**。
消息记录里有完整的工具输出（可能几千字），是「重放对话」必需的；
而轨迹只留摘要，是「解释这次运行」必需的。
把两者混在一张表里，要么报告读不动，要么对话被截断。

---

## 二、每一步记了什么

一个「模型步」= 一次模型调用。它包含：

| 字段 | 含义 |
|---|---|
| `step` | **会话级**步号 —— 和 `loca rollback <session> <step>` 用的是同一个编号 |
| `prompt_messages` / `prompt_chars` | 这次请求发了几条消息、大约多少字符 |
| `prompt_tail` | 请求里**最后一条**消息的开头（模型当时在回应什么） |
| `text` / `reasoning` | 模型这次的正文 / 思考内容 |
| `tool_calls` / `tool_results` | 调了哪些工具、参数是什么、结果多长、成功还是失败、各用了多久 |
| `prompt_tokens` / `completion_tokens` | 这次调用的 token |
| `duration_ms` | 本步总耗时（含工具），`tool_results[].duration_ms` 是工具自己花的时间 |
| `finish_reason` | 这一步怎么结束的 |
| `error` / `retries` | 失败原因 / 遇到截断后重试了几次 |
| `context` | 本步发生的上下文压缩（裁剪或摘要）说明 |
| `checkpoints` | 本步之前被快照的文件路径 |

### 为什么 prompt 只存「摘要 + 尾巴」

完整的 prompt 就是「会话记录」本身，已经在 `messages` 表里躺着了。
再抄一份到轨迹里，等于让每次运行的磁盘占用翻倍，而且两份数据会随时间漂移。
所以轨迹存的是**形状**（多少条、多少字符）和**尾巴**（最后一条消息），
足够让人读懂这一步在干什么；要看全文就 `loca sessions show <id>`。

同理，工具结果只存**前 800 字符**和**真实长度**。

### `finish_reason` 是推导出来的

循环只在整轮结束时（`DONE` 事件）告诉你一个总体原因。
所以中间步的 `finish_reason` 是从事件流**分类**出来的：

- 出错 → `error`
- 遇到过截断重试 → `recovered`
- 这一步调了工具 → `tool_use`
- 其他 → `stop`

把它当作「这一步是怎么结束的」的分类，别当成厂商返回的原样字段。

---

## 三、跑到哪里去了

双写。这是**故意的冗余**：

1. **SQLite** —— `<会话数据库所在目录>\traces` 之外，`traces` 表里一行一步。
   和它描述的会话同生共死（`loca sessions rm` 会连带删掉）。
2. **JSONL** —— `<会话数据库所在目录>\traces\<会话 id>.jsonl`，一行一个 JSON。
   纯追加，任何工具都能 grep。

默认数据库是 `~\.loca\sessions.db`，所以默认轨迹文件是：

```
C:\Users\<你>\.loca\traces\<会话 id>.jsonl
```

为什么两套？因为「数据库被删了」是个真实场景 —— 而一条运行记录的价值，
往往在你事后想复盘的时候才体现出来。**只要 `.jsonl` 还在，
`loca report` 依然能把它渲染出来**（报告里的 `trace source` 会显示 `jsonl`）。

换目录：

```
set LOCA_TRACE_DIR=D:\loca-traces
```

或者直接用 `--db` —— 轨迹目录跟着数据库走：

```
python -m loca.cli chat --session demo --db "D:\loca sessions.db"
:: 轨迹会写进 D:\traces\demo.jsonl
```

---

## 四、怎么用

### 1. 正常聊天，自动记录

轨迹**默认就开着**（只要你没加 `--no-save`）。启动时会告诉你写到哪：

```
loca · provider deepseek · 4 tool(s) · workspace D:\Projects\loca\playground\week5
session w5-demo (new) · db playground\loca-w5.db
tracing to playground\traces\w5-demo.jsonl
Type 'exit' to quit · /help for commands.
```

关掉它：

```
loca chat --no-trace
```

REPL 里想知道记了多少步：

```
/trace
```

### 2. 看报告

```
loca report w5-demo --db "playground\loca-w5.db"
```

一次真实运行（DeepSeek 真的建文件、真的跑脚本）的输出：

```
loca report · w5-demo
Create a file named hello.py containing a print of the exact text "hell…
workspace     D:\Projects\loca\playground\week5
provider      deepseek
created       2026-09-12T09:27:17+00:00
updated       2026-09-12T09:27:18+00:00
messages      6
trace source  database

summary
  steps      2 model call(s) · 1,266 tokens/step average
  tokens     2,532 total (2,400 prompt · 132 completion)
  time       1.4s model · 90ms tools
  tools      2 call(s) · 0 error(s) (0%)

tools
tool        calls  errors  time   avg
shell           1       0  85ms  85ms
write_file      1       0   5ms   5ms

steps
step   time  tokens  tools              finish    note
   0  936ms   1,205  write_file, shell  tool_use
   1  567ms   1,327  —                  stop

files snapshotted (restorable with `loca rollback`)
  hello.py
```

**不带会话 id** 就报告最近一次会话（提示语走 stderr，不会污染管道）：

```
loca report
```

### 3. 加细节

```
loca report w5-demo --verbose
```

多出每一步的 prompt 尾巴、模型回复、工具参数与输出预览：

```
step 0 (936ms)
  prompt 2 message(s), 457 chars
  └─ [user] Create a file named hello.py containing a print of the exact text
"hello from loca", then run it with the shell tool and quote its output.
  reply  I'll create the file and run it.
  → write_file(path='hello.py', content='print("hello from loca")\n')
  → shell(command='python hello.py')
  ✓ write_file 84 chars · 5ms
     Successfully wrote 25 bytes to D:\Projects\loca\playground\week5\hello.py (new file)
  ✓ shell 140 chars · 85ms
     <shell command="python hello.py" cwd=D:\Projects\loca\playground\week5 exit_code=0 ...>

step 1 (567ms)
  prompt 5 message(s), 713 chars
  └─ [tool] <shell command="python hello.py" ...> --- stdout --- hello from loca
  reply  Done. Created `hello.py` ... Output: ``` hello from loca ```
```

注意 `prompt 2 message(s)` → `prompt 5 message(s)`：
第 0 步模型看到的是「系统提示 + 你的话」，
第 1 步看到的是「系统提示 + 你的话 + 助手（含两个工具调用）+ 两条工具结果」。
**这就是 `prompt_messages` 的意义 —— 你能核对模型当时到底看到了什么。**

### 4. 喂给脚本

```
loca report w5-demo --json > report.json
```

输出是纯 JSON（诊断信息走 stderr，所以可以直接接 `jq`），结构是：

```json
{
  "session":   { "id", "title", "workspace", "provider", "model", "messages" },
  "source":    "database" | "jsonl" | "none",
  "summary":   { "steps", "total_tokens", "tokens_per_step", "model_ms",
                 "tool_ms", "tool_calls", "tool_errors", "error_rate",
                 "failures", "retries", "compactions", "trims", "files" },
  "tools":     [ { "name", "calls", "errors", "error_rate", "duration_ms" } ],
  "steps":     [ …每一步的完整记录… ],
  "checkpoints": [ … ]
}
```

### 5. 只列前几步

```
loca report w5-demo --limit 5
```

`--limit 0`（默认）表示全列。

---

## 五、数字怎么读

**`time 1.4s model · 90ms tools`**
模型时间和工具时间是**互斥**的：`duration_ms` 含工具耗时，
报告里先减掉工具时间再算「模型时间」，否则每个工具会被算两遍。

**`tokens 2,532 total (2,400 prompt · 132 completion)`**
prompt 是大头是正常的 —— 每多一步，整个历史都要重发一次。
这个数字涨得比你想的快，就是上下文压缩存在的理由。

**`tools 2 call(s) · 0 error(s) (0%)`**
错误率 = 工具返回 `is_error` 的比例。这个数字高不代表 agent 差 ——
模型很多时候是**故意**先试错再纠正的，重点看它有没有恢复。

**`finish` 列的 `recovered`**
意思是这一步被输出长度限制截断了，loca 自动让模型接着写。
正常现象，不是故障。

---

## 六、限制，说实话

- **Web GUI 没有轨迹。** `loca serve` 是无状态的（没有会话库），
  所以它不写 trace。要看轨迹请用 CLI。
- **`loca chat --no-save` 不落盘。** 没有数据库就没有会话行，
  轨迹只能留在内存里。想留档就别加 `--no-save`。
- **一行 JSONL 是一步，不是一轮。** 一轮里模型调了 3 次，就是 3 行。
- **轨迹不替代日志。** 它记的是「发生了什么」，
  内部异常栈还是看 stderr。

---

## 七、常见问题

| 现象 | 原因 / 怎么办 |
|---|---|
| `no trace recorded for this session` | 这个会话是在 Week 5 之前跑的，或者用了 `--no-trace` / `--no-save`。重新跑一次就有了 |
| `trace source  jsonl` | 数据库里没有轨迹行，报告是从 `.jsonl` 镜像读的。说明数据库被换过或清过 —— 数据没丢 |
| 轨迹文件找不着 | 它跟数据库同目录下的 `traces\`。用 `--db` 指定过数据库的话，去那个目录找；或者 `set LOCA_TRACE_DIR=` 固定一个位置 |
| `--json` 输出前面多了一行字 | 那是 stderr 的提示（没给会话 id）。重定向 `2>nul` 就干净了 |
| 报告里 files 是空的 | 这一轮只调了 `shell`（不追踪），或者只做了读操作 |
| 会话删了但 `.jsonl` 还在 | 正常。JSONL 是独立文件，不会被 `loca sessions rm` 删掉；想清理自己删文件即可 |

---

## 八、相关文档

- 会话、回滚与检查点：[`sessions-and-rollback.md`](sessions-and-rollback.md)
- CLI 从哪启动、怎么用：[`running-the-cli.md`](running-the-cli.md)
- Web GUI：[`running-the-web-gui.md`](running-the-web-gui.md)
