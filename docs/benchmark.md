# 评测集（Benchmark）：怎么跑、报告怎么读、为什么可信

> 这份文档写给「想用 `loca bench` 得到一组能写进简历、也能被追问的数字」的人。
> 所有命令与输出都在真实机器上跑过；文中的跑分是 2026-09-18 用 DeepSeek 默认模型
> 在 36 个自带任务上跑出来的真实结果。

## 1. 为什么要自带评测集

一个 coding agent 最容易自欺的地方是：你手动试了几下，觉得「挺聪明的」。
但「挺聪明」不是数据。真正要回答的是三个问题：

1. **它到底能做完多少比例的活？**（pass@1）
2. **它做不完的时候，是卡在哪一步？**（失败分类）
3. **做成一件事要花多少代价？**（token / 步数）

这三件事只有用**固定任务集 + 固定判分口径**跑出来的数字才算数。
换一批题、换个判分口径，数字就不可比 —— 所以任务和判分方式都进了仓库。

`loca/eval/` 三个文件的分工：

| 文件 | 职责 |
|---|---|
| `tasks.py` | 一道任务长什么样、怎么加载、怎么判分 |
| `benchmark.py` | 并发跑、结果分类、聚合出 pass@1 / pass@k；外加任务集自检 |
| `report.py` | 把结果渲染成 Rich 表格或 JSON |

## 2. 一道任务长什么样

```
loca/eval/tasks/fix-off-by-one/
├── task.json        # 给模型看的题目 + 给判分器看的规则
├── workspace/       # 模型一开始拿到的文件（里面埋着 bug）
├── hidden/          # 判分文件，模型看不到
└── solution/        # 参考答案，只用来证明这题做得出来
```

`task.json` 的字段：

```json
{
  "id": "fix-off-by-one",
  "title": "count_up drops the last number",
  "difficulty": "simple",
  "prompt": "count_up(3) should return [1, 2, 3] but returns [1, 2]. Fix it.",
  "checks": { "kind": "pytest", "paths": ["test_count_up.py"] },
  "tags": ["bugfix", "off-by-one"],
  "timeout_s": 120,
  "max_steps": 20
}
```

只有 `id` / `title` / `difficulty` / `prompt` / `checks` 是必填的。
`difficulty` 只能是 `simple` / `medium` / `hard` 之一，它决定报告里的难度分解。

### 三种判分方式

| `kind` | 怎么判 | 额外字段 |
|---|---|---|
| `pytest` | 在沙箱里跑一个 pytest 套件，退出码为 0 就算过 | `paths`（要跑的文件）、`args` |
| `run` | 跑一个脚本，比 stdout 与退出码 | `file`、`args`、`stdin`、`expect_stdout`、`expect_exit` |
| `script` | 调任务自己 `checks.py` 里的 `verify(workspace)` | `entry`（默认 `checks.py`）、`func`（默认 `verify`） |

`script` 的 `verify` 可以返回 `bool`、`(bool, str)`、`dict` 或直接返回 `CheckResult`，
所以想写多细的判据都行 —— 但**判据必须看行为，不能看代码文本**（下一节）。

> `stdout` 比对会把 `\r\n` 归一成 `\n` 再比。模型写的脚本在 Windows 上按文本模式
> 打开 stdout 就会多出 `\r`，那是平台差异，不是答错。

## 3. 为什么这些数字是可信的

判分这件事，很容易做成「看起来很严格，其实一戳就漏」。这里做了三件事。

### 3.1 判分文件放在 `hidden/`，判分前才盖回沙箱

`hidden/` 里的东西**不会**出现在模型的工作区里，模型只看得到 `workspace/`。
但判分之前，`hidden/` 会被原样复制回沙箱，**覆盖**模型留下的同名文件。

这一条同时解决两个问题：

- 模型看不到测试断言，只能从 prompt 去推理「到底要什么」，而不是把断言拟合出来；
- 模型把测试文件改成 `def test_anything(): pass` 也没用 —— 判分前会被盖回去。

有个测试专门钉住这一点：让 agent 手写一个必然通过的 `test_it.py`，
结果仍然是 `wrong_answer`。

### 3.2 判分看行为，不看 diff

三种判分方式都不检查模型的源码长什么样，只检查**跑起来对不对**。

这是刻意的取舍：同一个需求有无数种写法，diff 判分等于要求模型「按我脑子里那份答案写」。
那测的是模型的猜测能力，不是它解决问题的能力。代价是任务作者要写得出判据 ——
但判据一旦写好，「另一种正确写法」也能通过。

### 3.3 任务集自己先体检一遍

`loca bench verify` 会逐题确认两件事：

| 检查 | 不通说明什么 |
|---|---|
| **起始工作区判不过**（`fails_on_seed`） | 这题不用做就能过 —— 它什么都没在测 |
| **参考答案判得过**（`passes_with_solution`） | 这题无解 —— 它报的每个失败都是噪音 |

36 道题全部通过这项自检：

```
$ loca bench verify
checking every task: seed must fail, reference solution must pass
task set integrity
┌────────────────────────────────┬────────┬───────────────┬─────────────────┐
│ task                           │ tier   │ fails on seed │ solution passes │
├────────────────────────────────┼────────┼───────────────┼─────────────────┤
│ fix-comparison-boundary        │ simple │ yes           │ yes             │
│ …                              │ …      │ yes           │ yes             │
│ impl-word-wrap                 │ hard   │ yes           │ yes             │
└────────────────────────────────┴────────┴───────────────┴─────────────────┘
all 36 task(s) check out
```

### 3.4 失败会分成七类，不混在一起

模型没做出来，和 harness 挂了、题坏了，是**完全不同的三件事**。混成一个
「失败率」就是把责任推给模型。所以结果按 `outcome` 分开记：

| outcome | 含义 | 责任方 |
|---|---|---|
| `passed` | 判分通过 | — |
| `wrong_answer` | 循环正常跑完，判分没过 | 模型 |
| `max_steps` | 撞到步数上限还没收工 | 模型（或步数上限太紧） |
| `provider_error` | 模型 API 报错 | 网络 / 服务商 |
| `timeout` | 撞到墙钟上限 | 模型太慢 / 上限太紧 |
| `crash` | harness 自己抛异常 | **我们的 bug** |
| `grader_error` | 判分器本身坏了 | **题目作者的 bug** |

`grader_error` 在报告里被单独摘出来报警，并明确写着「这是任务集的 bug，不是模型的失败」。
一条坏了判分器的题，永远不该出现在「模型不行」的统计里。

## 4. 怎么跑

```cmd
loca bench                     :: 列出任务（默认动作）
loca bench run                 :: 跑全部 36 题
loca bench verify              :: 任务集自检
```

常用参数：

| 参数 | 默认 | 作用 |
|---|---|---|
| `--difficulty simple` | 全部 | 只跑某一档（可重复） |
| `--task <id>` | 全部 | 只跑某一题（可重复） |
| `--limit N` | 0 = 全部 | 最多跑几题 |
| `--attempts N` | 1 | 每题跑几次（≥2 才能区分 pass@1 与 pass@k） |
| `--workers N` | 4 | 并发数 |
| `--max-steps N` | 20 | 单次尝试的步数上限 |
| `--timeout N` | 300 | 单次尝试的墙钟上限（秒） |
| `--workdir <dir>` | 临时目录 | 沙箱建在哪 |
| `--keep` | 关 | 跑完保留沙箱，方便肉眼查 |
| `--out <file>` | — | 把报告 JSON 写到文件 |
| `--provider` / `--model` | deepseek | 换 provider / 换模型 |
| `--compare a,b` | — | 依次跑多个 provider 并排对比 |
| `--json` / `--verbose` | — | JSON 输出 / 展开每题细节 |

第一次跑建议先小范围试水：

```cmd
loca bench run --difficulty simple --limit 3 --workers 2
```

输出是这样的（真实输出，只是截短）：

```
bench · provider deepseek · 3 task(s) × 1 attempt(s) · 2 worker(s)
3 attempt(s) queued
  ✓ fix-comparison-boundary   passed   4 step(s)   6031 tok   4.7s  (1/3)
  ✓ fix-dedupe-order          passed   5 step(s)   8287 tok   6.0s  (2/3)
  ✓ fix-dict-key-error        passed   5 step(s)   7956 tok   5.6s  (3/3)
```

每一行是一**次尝试**：结果、步数、token、耗时、进度。

### 沙箱与并发

每次尝试都有自己的沙箱目录（`<workdir>/<task_id>-a<attempt>`）、自己的 provider 实例、
自己的会话 id（`bench-<task_id>-a<attempt>`）。跑完默认把 `<workdir>` 整个删掉，
`--keep` 可以留下来翻查。

provider 必须是**每次调用现造一个**（`provider_factory`），因为 HTTP 客户端不保证
跨线程安全，而 agent 会话是长生命周期的。这一点在 `benchmark.py` 的模块文档里写了原因。

> **Windows 提示**：如果 `<workdir>` 放在项目目录里，某些 IDE 的「删除保护」会拦住
> 跑完后的清理、让整轮报一堆 `SystemExit`。放到 `%TEMP%` 下就没这个问题。

## 5. 报告怎么读

### 5.1 pass@1 和 pass@k 是两件事

| 指标 | 分母 | 回答的问题 |
|---|---|---|
| **pass@1** | 尝试次数 | 「随便跑一次，成功率多少？」 |
| **pass@k** | 任务数 | 「这题**存在**解吗？」 |

`--attempts 1` 时两者相等（每题只跑一次，任务解出与否 = 那次尝试过没过）。
`--attempts 5` 时它们会分开，而分开才有信息量：

- pass@1 低、pass@k 高 → 题**能做**，但模型不稳（要靠重试或投票）；
- 两个都低 → 题**做不了**，是能力问题，重试没用。

把这两种情况混成一个「成功率」，会让你误判该去优化采样还是该去换模型。

### 5.2 成本按「每个通过」算，不按「每次尝试」算

报告里的 `tokens/pass`、`steps/pass` 分母是**通过的尝试数**，不是总尝试数。

因为「失败得很便宜」不是效率高，只是失败。按尝试算会鼓励一个
「瞎答一通、秒挂」的策略拿好看的成本数字。

### 5.3 JSON 输出的形状

`--json` 或 `--out` 给出完整结构，主要字段：

```json
{
  "provider": "deepseek",
  "task_count": 36,
  "total_attempts": 36,
  "passed_attempts": 33,
  "pass_at_1": 0.9167,
  "solved_tasks": 33,
  "pass_at_k": 0.9167,
  "outcomes": { "passed": 33, "wrong_answer": 3 },
  "failures": { "wrong_answer": 3 },
  "by_difficulty": {
    "simple": { "tasks": 14, "passed": 13, "pass_rate": 0.9286,
                "tokens_per_pass": 8070.9, "steps_per_pass": 4.92 }
  },
  "cost": { "tokens_total": 399218.0, "tokens_per_pass": 11120.18,
            "tokens_per_failure": 10750.67, "steps_per_pass": 5.27 },
  "results": [ { "task_id": "…", "outcome": "passed", "steps": 4, "tokens": 5976,
                 "tool_calls": 3, "tool_errors": 0, "detail": "…" } ]
}
```

`results[].detail` 存的是判分器的原始输出（pytest 的失败摘要等），
所以「为什么没过」不用回去翻日志。渲染到终端时它会被 `rich.markup.escape` 过，
模型输出里带 `[` 的文本不会被当成样式标签吞掉。

## 6. 真实跑分

**2026-09-18 · DeepSeek 默认模型 · 36 题 · 每题 1 次 · 4 并发**

| 难度 | 题量 | 通过 | 通过率 | tokens/通过 | 步数/通过 |
|---|---:|---:|---:|---:|---:|
| simple | 14 | 13 | 92.9% | 8,071 | 4.9 |
| medium | 12 | 12 | 100% | 12,591 | 5.7 |
| hard | 10 | 8 | 80.0% | 17,901 | 7.1 |
| **合计** | **36** | **33** | **91.7%** | **11,120** | **5.3** |

- **pass@1 = 91.7%**（33/36），pass@k 同值（每题只跑一次）
- 整轮 **399,218 tokens**，墙钟 **67 秒**（4 并发；累计 256 秒）
- 成本随难度单调上升：简单题 8.1k tokens / 4.9 步，难题 17.9k tokens / 7.1 步
- 原始报告：[`benchmarks/deepseek-36.json`](benchmarks/deepseek-36.json)

### 有趣的地方：唯一没做对的简单题

三个失败里有两个是 hard（预期之内），但有一个是 **simple**：

| 任务 | 难度 | 失败原因 |
|---|---|---|
| `fix-recursion-base-case` | simple | 递归改对了，但 `test_negative_is_rejected` 没过 —— 负数入参没抛 `ValueError` |
| `impl-expression-evaluator` | hard | 16 条断言过了 15 条，只差 `1++2` 这种畸形输入没被拒 |
| `impl-word-wrap` | hard | 返回了字符串，而契约要求返回「行的列表」—— 11 条只过 2 条 |

三个失败**都不是算法没写出来**，而是同一类问题：
**prompt 里明确写了的边界条件与返回类型契约，模型没有逐条落实。**

这是评测集给出的最有价值的一条信息 —— 它跟「模型会不会写算法」无关，
跟「模型会不会按你说的规格交付」有关。而这恰恰是 coding agent 真正要解决的问题。
所以这类失败不该靠换更强的模型来掩盖，而应该在 harness 层面解决：
把验收标准显式化、让循环在收工前自己过一遍题面里的约束。

> 另外注意 `impl-word-wrap` 只花了 4 步就交卷了。它不是「做不出来」，是
> **没意识到自己没做对** —— 它没有可运行的反馈信号（判分器是隐藏的），
> 于是写完就以为完事了。

## 7. 加一道新题

1. 建目录 `loca/eval/tasks/<新 id>/`；
2. 写 `workspace/`（含缺陷）、`hidden/`（判分文件）、`task.json`；
3. 写 `solution/`（参考答案）——没有它，这题无法被证明有解；
4. 跑 `loca bench verify`，确认新题 `fails_on_seed` 且 `passes_with_solution`；
5. 跑 `loca bench run --task <新 id> --keep`，肉眼看一眼沙箱。

第 4 步不能跳。它就是「任务集的测试套件」，而且完全不需要 provider、不花 token。

## 8. 已知限制

- **超时是「协作式」的**：墙钟上限在流式事件之间检查，所以如果 provider 卡在
  HTTP 客户端内部，实际耗时由那个客户端自己的超时决定，可能超过 `--timeout`。
  这一点写在 `benchmark.py` 的模块文档里，而不是藏起来 ——
  「报告说 300 秒超时、实际挂了 320 秒」正是那种会悄悄让报告失效的细节。
- **`shell` 不可回滚**：检查点只管 `write_file` / `edit_file`。
  评测里模型用什么工具是自由的，所以「回滚到某一步」在评测语境下没有意义。
- **只支持 Windows**：和主项目一致，`shell` 工具跑的是 cmd.exe。
- **`loca bench verify` 是串行的**：36 题要跑 36 次 pytest，几十秒。它不进 `pytest`
  测试套件（那会把单测拖慢十倍），只在需要时手动跑。

## 9. FAQ

**Q：为什么不直接用 SWE-bench？**
A：SWE-bench 考的是「在真实大仓库里改一个已合并的 PR」，需要下载仓库、装依赖、
跑很久，而且它的判据是别人定的。这套自带任务集目的是**可控地**回答
「我的 harness 现在到底行不行」——题目小、判据自写、几十秒跑完，
适合每次改动都跑一遍。两者不冲突，SWE-bench 是下一步。

**Q：为什么不用 LLM 当裁判？**
A：LLM 裁判适合开放性任务（写作、主观评价）。写代码的对错有客观判据，
用 LLM 判只会引入噪声和额外成本。

**Q：`--attempts` 为什么默认 1？**
A：默认值要选「一次跑完、数字最直观」的。想区分 pass@1 和 pass@k 就显式传
`--attempts 5`，这个决定应该是有意识的。

**Q：跑一次要花多少钱？**
A：36 题约 40 万 token。DeepSeek 的价位下是几分钱级别，随便跑。
`--difficulty simple --limit 5` 可以再便宜一个量级，适合改完代码快速验证。
