# loca —— 简历项目描述（STAR 版）

> 本文件是「可直接抄进简历 / 面试自我介绍」的成品，不是技术指南。
> 同一份素材给了四种长度和语言：按版面自行取用。
>
> 最后更新：2026-09-23（新增 §六 对标章节）

---

## 零、先看这张数字表（所有版本的事实来源）

| 项目 | 数字 |
|---|---|
| Harness 源码规模 | **8,380 行 / 31 个模块**（`loca/`，不含评测夹具） |
| 评测集规模 | **36 道任务 / 161 个夹具文件 / 3,103 行**（`loca/eval/tasks/`，含题面 `task.json` 与夹具数据文件；另不含 `_generate/` 下 4 个一次性生成脚本） |
| 测试规模 | **7,520 行 / 21 个测试文件 / 434 项测试** |
| 测试结果 | 离线 **426 通过（0 跳过）**；真实 API e2e 8 项通过；`ruff` 全绿 |
| 评测结果 | **36 题 pass@1 = 91.7%（33/36）**，DeepSeek 默认模型，1 次/题、4 并发 |
| 已实现厂商 | **3 家**：DeepSeek（默认）/ OpenAI / Anthropic |
| 已实现工具 | **4 个**：`read_file` / `write_file` / `edit_file` / `shell` |
| 界面 | **2 个**：CLI REPL + FastAPI/SSE Web GUI |
| 文档 | 中英双语 README（450 行）+ 6 篇中文指南（1,650 行） |
| 自审与修复 | **26 项缺陷（P1 3 / P2 12 / P3 11）全部修复并验证** |
| 周期 | 6 周路线图，**6 周全部完成** |
| 仓库 | github.com/Wang-Yi-666/loca |

> ⚠️ **两点提醒**
> 1. 上面的数字会随代码变化，抄进简历前请重跑一次统计（见文末「维护方式」）。
> 2. **代码主体已提交并推送到 GitHub**（2026-09-18，`main` = `f0571af`，按 observability → providers → eval → cli → docs 分 5 批提交）。仓库现在能看到完整实现、评测集与跑分归档。
>    **但审查后的 26 项缺陷修复还在本地工作区、尚未提交** —— 本文档里的 `8,380 行 / 7,520 行 / 434 项` 是**修复后**的实测数字，与远端当前状态相差这批改动。

### 技术栈（简历上单独一行写）

**语言**：Python 3.13（包声明 `>=3.13`）　**界面**：CLI（argparse + Rich）+ Web GUI（FastAPI + SSE）
**存储**：SQLite（WAL 模式，`sqlite3` 标准库）　**测试**：pytest（离线/联网分流，`-m live`）+ ruff
**协议接入**：OpenAI 官方 SDK（DeepSeek / OpenAI 共用 `OpenAICompatibleProvider`）、Anthropic SDK（懒导入）
**校验与配置**：jsonschema（工具入参校验）、pydantic、python-dotenv
**刻意不用**：LangChain / LlamaIndex 等任何 agent 框架（执行循环、重试、上下文预算全部自研）

---

## 一、精简版（约 170 字｜适合版面紧张时只留一条）

**loca —— 从零自研的 Coding Agent Harness**（个人项目 · Python 3.13）

为看清 agent 的真实工程问题，不依赖 LangChain 等任何框架，从零实现一个 coding agent：统一 DeepSeek / OpenAI / Anthropic 三家的 tool-use 协议；自研流式执行循环，把重试严格限制在「首个流式分片到达之前」，已输出的内容绝不重放；实现 SQLite 会话持久化、按步文件回滚，以及按「模型步」记录的执行轨迹与报告。并自建 **36 道任务的评测集**——判分文件对模型隐藏、按行为而非 diff 判分、任务集先自证有解——真实跑出 **pass@1 = 91.7%**。成果：**8,380 行 harness 源码 / 7,520 行测试 / 434 项测试全绿**。

---

## 二、标准版（约 680 字｜推荐，STAR 结构完整）

**loca —— 从零自研的 Coding Agent Harness**
个人项目 ｜ Python 3.13 · FastAPI · SQLite ｜ github.com/Wang-Yi-666/loca

**背景（S）**
想真正入门 agent 工程，但常见做法是「提示词 + LLM SDK」再套一层 LangChain 之类的框架——执行循环、错误恢复、上下文预算这些真正困难的部分全被框架藏了起来，学不到东西。同时，DeepSeek / OpenAI / Anthropic 三家的 tool-use 协议各不相同，流式场景下的工具调用分片与失败重试，市面上也没有现成的可观测手段。更麻烦的是：**「agent 好不好用」几乎全靠手动试，没有一个可复现的数字。**

**任务（T）**
不借助任何 agent 框架，从零实现一个可当作本地开发搭子使用的 coding agent harness，要同时解决四件事：跨厂商统一的工具调用协议、在工具失败与模型输出跑偏时依然能存活的流式执行循环、一套能事后逐步复盘的可观测性，以及**一套能回答「它到底行不行」的自带评测集**。

**行动（A）**
1. **多厂商协议分层** —— 抽出 OpenAI 兼容层供 DeepSeek / OpenAI 复用；Anthropic 单独实现纯函数翻译层，把消息结构、工具 schema、流式事件、缓存 token 逐一映射，做到**不发网络请求就能完整测试**。
2. **可靠的执行循环** —— 指数退避重试严格限制在「首个流式分片到达之前」，已经输出给用户的内容绝不重放；回复被长度上限截断时自动追加续写指令；上下文接近预算上限时，让模型把旧消息压成摘要而不是直接丢弃。
3. **状态与回滚** —— SQLite（WAL 模式）持久化会话与消息，支持跨进程断点续聊；文件类工具执行前自动快照，可按步回滚，新建的文件回滚时**删除而非清空**。
4. **可观测性** —— 轨迹记录器以「事件 sink」方式挂载在循环的事件流上，**不改动循环核心**；按「每模型步」记录 prompt、工具调用、token、耗时与重试次数，双写 SQLite 与 JSONL 镜像，并提供报告命令输出总览表或 JSON 两种形态。
5. **自带评测集**（36 道题：14 简单 / 12 中等 / 10 困难）—— 每次尝试走**真实的执行循环和真实的工具**，只替换「题目从哪来」和「谁来判分」；判分文件放在 `hidden/`，模型看不到、判分前才覆盖回沙箱（改自己的测试文件没有任何用）；判分**只看行为不看 diff**（跑 pytest / 比 stdout / 调校验脚本），所以「另一种正确写法」也能拿分；线程池并发，输出 pass@1、pass@k、按难度分解、七类失败归因与 token / 步数成本。另加 `loca bench verify` 任务集自检：逐题确认「起始工作区必须判不过、参考答案必须判得过」——不需要 provider、不花 token。

**结果（R）**
harness 源码 8,380 行配测试 7,520 行，共 **434 项测试**（离线 426 项全过、0 跳过，另 8 项真实 API 端到端），静态检查全绿。评测集 36 道题全部通过自检，真实跑分 **pass@1 = 91.7%（33/36）**，按难度 simple 92.9% / medium 100% / hard 80.0%，平均 11,120 tokens、5.3 步完成一道题，整轮 67 秒。真实跑通「模型自主写文件并执行」「两个独立进程断点续聊」等端到端场景。项目完成后对全仓库做了系统自审并写成报告（**26 项缺陷，含 3 个 P1**），**逐条复现、逐条修复并验证**：包括 **`shell` 超时杀不掉孙进程**（实测声明 2 秒实跑 8.09 秒 → 修后 2.24 秒且无残留进程）、**`%COMSPEC%` 被替换时 shell 回退路径 100% 失效**、**同一步多次改动回滚还原成中间版本**；也覆盖**步数计数器跨重启归零**、**同一秒创建的会话排序错乱**、**评测 runner 漏传上下文预算**等真实缺陷。

---

## 三、English Version（~230 words）

**loca — a Coding Agent Harness Built From Scratch**
Personal project | Python 3.13 · FastAPI · SQLite | github.com/Wang-Yi-666/loca

**Situation** Most agent projects glue a prompt onto an LLM SDK and stop there; the genuinely hard parts — the execution loop, failure recovery, context budgeting — stay buried inside a framework. On top of that, DeepSeek, OpenAI and Anthropic each speak a different tool-use protocol, streaming tool calls have no out-of-the-box way to be inspected afterwards, and "is this agent any good?" is usually answered by trying a few prompts by hand rather than by a reproducible number.

**Task** Build a coding agent harness usable as a local dev sidekick, without any agent framework, solving four problems at once: a unified multi-vendor tool-use protocol, a streaming loop that survives tool failures and bad model output, observability good enough to reconstruct any step afterwards, and a benchmark that can answer "does it actually work?".

**Action** (1) Layered the providers — a shared OpenAI-compatible layer for DeepSeek/OpenAI, and a separate pure-function translation layer for Anthropic, fully testable without any network call. (2) Made retries strictly pre-first-chunk so nothing the user already saw is replayed; auto-continued truncated replies; summarised old turns instead of dropping them. (3) Persisted sessions in SQLite with WAL, plus pre-execution file snapshots for step-wise rollback. (4) Attached the trace recorder as an event sink, writing per-model-step traces to both SQLite and JSONL. (5) Shipped a 36-task benchmark driven through the real loop and the real tools, with grader files hidden from the agent and restored before grading, behavioural (not diff-based) grading, and a self-check that every task must fail on its starting state and pass with its reference solution.

**Result** 8,380 lines of harness source against 7,520 lines of tests; **434 tests** (426 offline passing with nothing skipped, 8 live end-to-end) with a clean linter. The benchmark scores **pass@1 = 91.7% (33/36)** — 92.9% simple, 100% medium, 80.0% hard — at 11,120 tokens and 5.3 steps per pass. After shipping, I audited the whole repository, wrote up **26 defects (including 3 P1)**, and fixed and verified every one of them.

---

## 四、面试口述版（约 80 秒，可直接背）

> 我做了一个叫 loca 的项目，是一个从零写的 coding agent harness，没用 LangChain 这类框架。
>
> 动机是我发现大部分 agent 项目就是「提示词加 SDK 调用」，真正难的东西全在框架里，看不到。所以我把最难的那层自己写了一遍。
>
> 具体做了五块。第一块是多厂商协议，DeepSeek 和 OpenAI 共用一个兼容层，Anthropic 的差异太大，我单独写了一层纯函数的协议翻译，好处是不用发请求就能测。第二块是执行循环，重试有个硬约束：只允许在第一个流式分片到达之前重试，因为用户已经看到的内容不能重放。第三块是状态，会话存 SQLite，文件改动前会快照，可以按步回滚。第四块是可观测性，我按「每一个模型步」记录轨迹，双写数据库和 JSONL，还能出一条报告。
>
> 第五块是我最想讲的：**我自己造了一套 36 道题的评测集**。因为「我觉得它挺好用」不是数据。判分文件我对模型隐藏，判分前才盖回沙箱，所以它改自己的测试文件没用；判分也只看行为不看代码 diff，另一种正确写法也能过。另外有个自检，确保每道题起始判不过、参考答案判得过——不然题目本身就是坏的。
>
> 真实跑出来是 **pass@1 91.7%**，33 道过。但更有意思的是那三个失败：**没有一个是因为算法写不出来**，全都是题面里写明了、模型没有逐条落实的边界条件和返回类型契约。其中一个还是简单题。所以它给我的不是一个分数，是「下一步该在 harness 层做什么」。
>
> 规模上 harness 源码八千三百多行、测试七千五百多行，四百多项测试全绿、零跳过。
>
> 让我印象最深的几个 bug：步数计数器重启会归零，导致回滚的目标编号有歧义；同一秒建的会话排序会乱，让「最近会话」指到错的那条；还有一个是评测 runner 漏传了一个必填参数，导致「带会话落库跑评测」这条路必然崩溃——这三个都是靠手工跑真实流程才发现的，单测覆盖不到。

---

## 五、被追问时的弹药（高频问题 → 回答要点）

**Q：为什么不用 LangChain？**
因为在学 agent 工程，框架会把执行循环、重试、上下文管理都封装掉。我刻意把体量压小——不用 LangChain、不用 LlamaIndex，真正重要的每一行都在我自己的 `loca/` 目录里，出了 bug 我能一直追到底。

**Q：重试有什么难的？**
难点在流式。普通请求失败重试就行；但流式已经开始吐字之后重试，用户会看到重复内容，工具调用还可能被重复执行。所以我把重试严格限制在「首个分片到达之前」，这是用生成器表达最直接的语义，市面上的通用重试库反而不好干净地表达。

**Q：上下文超了怎么办？**
不是直接丢旧消息，而是让模型把旧轮次压成一段摘要。有个细节坑：摘要必须用 user 角色承载，因为存成 system 消息会在回灌历史时被过滤掉。摘要会钉在窗口里，只对最近的消息做裁剪。

**Q：为什么要自己造评测集？现成的 benchmark 不能用吗？**
现成的大 benchmark（比如 SWE-bench）考的是「在真实大仓库里改一个已合并的 PR」，要下仓库、装依赖、跑很久，而且判据是别人定的。我需要的是一个**可控地**回答「我的 harness 现在到底行不行」的东西：题目小、判据自己写、几十秒跑完，这样每改一次代码都跑得起。两者不冲突，大 benchmark 是下一步。另外我不想只报一个总分，我想知道**它每次是被什么卡住的**，所以失败分了七类。

**Q：91.7% 这个数字怎么保证不是自欺？**
三个机制。第一，判分文件放在 `hidden/`，模型看不到断言，判分前才覆盖回沙箱——它把测试改成 `pass` 也没用，有测试专门钉这条性质。第二，判分只看行为不看 diff，所以测的是「能不能解决问题」，不是「能不能猜到我心里那份答案」。第三，有个自检命令逐题确认「起始工作区必须判不过、参考答案必须判得过」——起始就能过的题等于没测，参考解都过不了的题报的全是噪音。36 题全部通过。

**Q：那三个失败说明什么？**
说明的比分数本身更有用。三个失败——一个简单题、两个困难题——**没有一个是算法写不出来**。全都是同一件事：题面里明确写了的边界条件和返回类型契约，模型没有逐条落实。比如有一道要求返回「行的列表」，它返回了字符串，11 条断言只过 2 条，而且只花了 4 步就交卷了——它不是做不出来，是**没意识到自己没做对**，因为判分器是隐藏的，它没有可运行的反馈信号。这说明问题出在 harness 层：验收标准没有被显式摆到循环面前，循环收工前也没有自己核对一遍。这个结论比「换个更强的模型」有价值得多。

**Q：为什么只支持 Windows？**
刻意的取舍，不是没做适配。目标是本地 Windows 开发机上的单用户 agent，多平台分支只会引入没人跑的代码路径。所以 `shell` 工具固定走 cmd.exe，模型被明确告知用 `dir` / `type` / `del` 而不是 `ls` / `cat` / `rm`。顺带一提，评测的沙箱目录我也建议放 `%TEMP%` 下——某些 IDE 的删除保护会拦住跑完后的清理。

**Q：回滚能撤销所有改动吗？**
不能，这点我写在报告和文档里了。只有 `write_file` 和 `edit_file` 会做快照；`shell` 能碰任何东西，为每条命令快照整个工作区不现实——与其假装能撤销，不如如实说明。

**Q：怎么保证改了 A 没弄坏 B？**
四百多项测试，离线一套跑得快，联网 e2e 单独分流（`pytest -m live`）。另外跨厂商的一致性有专门的回归测试钉住：同一个任务在 DeepSeek、OpenAI、Anthropic 上产出的工具调用和流式结果必须一致。评测集那边也有个回归测试：**自带任务的起始状态不能等于参考答案**——防我自己手滑把答案写回工作区、让题目静默失效。

---

## 六、对标：和 pi（earendil-works/pi）比，这个项目在做什么

> 面试官问「你了解现在主流的 harness 吗」「你和开源项目比差在哪」时用这一节。
> 它的作用不是「我比别人强」——而是**证明我知道自己在整张版图里的位置**。
> 这一节只用来口述，**不要写进简历正文**（简历上出现别人的项目会显得心虚）。

### 6.1 两个项目的背景（各一句话）

| | **pi**（`earendil-works/pi`，MIT） | **loca**（本项目） |
|---|---|---|
| 谁做的 | Mario Zechner（libGDX 作者）与 Earendil Works，TypeScript 全栈 | 个人项目，agent 工程方向的实习作品集 |
| 出身动机 | **对抗工作流锁定** —— 主流 coding agent 把模型、工具、上下文、会话、权限、自定义指令全打包成一个产品；换模型或换部署方式，团队就得重学整套系统 | **对抗「看不透」** —— 常见 agent 项目止步于「提示词 + SDK」，执行循环、失败恢复、上下文预算这些真正困难的部分全被框架藏住了，学不到东西 |
| 一句话定位 | 「可搭积木的 Agent 底座」：核心足够小，能力全部外置为扩展。官网原话 *There are many agent harnesses, but this one is yours.* | 「一个能自证行不行的 agent 运行时」 |
| 设计哲学 | **垂直克制**：六个 No（不要 MCP / 子代理 / 权限弹窗 / 计划模式 / 内建待办 / 后台 bash），每一个 No 都同时给出外部替代品（扩展、tmux、容器、TODO.md） | **水平闭环**：每个能力都要能回答「它到底行不行」，所以自带评测集 + 任务集自检 + 可观测性 |
| 交付物 | npm 包 + 包生态（扩展 / Skill / 提示模板 / 主题可一键安装分享） | 一个完整仓库：源码 + 测试 + 评测集 + 跑分归档 |
| 怎么验证 | 文档即评测：用自己项目的文档生成任务、LLM judge 打分 | 36 题 benchmark：判分文件对模型隐藏、按行为判分、任务集先自证有解 |

### 6.2 一个值得主动讲出来的「独立收敛」

pi 的默认工具集是 `read` / `write` / `edit` / `bash` —— **四个，和 loca 完全同构**。而且两边都刻意**不提供搜索工具**，让模型自己在 shell 里用 `grep` / `find` 解决检索。两个项目互不相干，却收敛到同一个答案：**四个工具足够，多余的工具只会增加选择成本。**

第二个同构更值得说：**两边都拒绝把「权限弹窗」做进核心。** pi 在文档里明写「不内置限制文件系统 / 进程 / 网络 / 凭证访问的权限系统，默认以启动它的用户权限运行，需要更强边界请容器化」；loca 的做法是把 `shell` 的不可回滚、以及「它不是沙箱」写进文档。**都是把边界说清楚，而不是假装修了边界。**

### 6.3 我必须坦白的差距（这题一定要答得干脆，别防御）

| 差距 | 说明 |
|---|---|
| **没有扩展体系** | pi 的核心卖点是「核心极小 + 能力外扩」（扩展 / Skill / 提示模板 / 主题 / 包），loca 是一体式实现，没有插件面。这是定位差异，也是真实差距。 |
| **Provider 覆盖差一个数量级** | 3 家 vs 39 家。但**架构洞察是同一个**：pi 的 39 家不是 39 套实现，而是 3 套 wire protocol（Anthropic 走 `anthropic-messages`、OpenAI 走 `openai-responses`、xAI/Groq/OpenRouter 等大部分共用 `openai-completions`）+ 各家鉴权与路径适配 —— 这正好对应 loca 的 `openai_compat.py` 复用层 + Anthropic 独立纯函数层。**差的是覆盖量，不是架构理解。** |
| **会话形态更简单** | pi 是树状分叉（可跳回任意历史节点重新提问、多个分支共存）且支持会话中途切厂商模型；loca 是线性会话 + 跨重启持久化的 `global_step`。 |
| **只有 2 个入口** | pi 同一份 runtime 支持四种运行模式（交互式 TUI / print-JSON / RPC / SDK），loca 是 CLI + Web GUI。**可嵌入性**这一层我没做。 |

### 6.4 三个高频追问的标准答法

**Q：为什么不直接用现成的 harness（Claude Code / pi / Codex）？**

> 我用了，但也正因为用了才想自己写一遍。现成的 harness 把执行循环、重试、上下文管理都封在内部，我能调参数但看不到机制。loca 的价值不是功能比它们多（远远不如），是**每一行我都能追到底** —— 比如「重试为什么只能发生在第一个流式分片之前」这种约束，在框架里是一个我读不到的 `if`。另外我刻意做了它们都没着重强调的一件事：**自带一套能自证的评测集**，让我能回答「改了这行代码，它是变好了还是变坏了」。这不是功能，是**反馈回路**。

**Q：和 pi 比，你的项目差在哪？**

> 差在三处：没有扩展体系、provider 覆盖少一个数量级、没有多入口（TUI / RPC / SDK）。
> 但定位本来就不同：**pi 是给别人搭积木的底座，它的正确性由用户的扩展来定义；loca 是一台我要证明它行不行的机器，所以力气花在了评测和可观测性上。**
> 有意思的是，两边在「只给四个工具」「不做内置权限系统」上独立收敛到了同一个答案 —— 这至少说明我的取舍不是拍脑袋。

**Q：为什么不给 harness 做 RAG？**（完整版见 6.5）

> 因为 coding agent 检索的根本不是「语义相似」，是**精确匹配**。`grep`、文件名模式、符号跳转是精确命中，召回率和可解释性都高于 embedding。主流 coding agent（Claude Code / pi / Cursor）走的都是 **agentic search**：模型自己 `grep` / `find` / `read`，而不是预建向量索引。**我的 `shell` + `read_file` 已经在做这件事。** 而且 RAG 该放在工具层或应用层（pi 把它做成扩展、Claude Code 把它做成 MCP server），放进 core 是**把自己的边界画错了**。

### 6.5 为什么 loca 不做 RAG

**结论先给：coding agent harness 不该把 RAG 做进核心，loca 尤其不该做。** 三条理由：

1. **代码检索的根本不是语义相似，是精确匹配。** RAG 解决的是「知识不在模型里、而且没有精确关键词可查」的问题；而代码里 `grep` / 文件名模式 / 符号跳转是精确命中，**召回率和可解释性都高于 embedding**。所以主流 coding agent 走的都是 agentic search。loca 的 `shell` + `read_file` 已经在做这件事 —— 这也是 pi 连搜索工具都不给、直接让模型 `grep` 的原因。
2. **在 harness 这一层做它属于错层。** harness 的边界是「进程与工具」，知识检索属于工具层或应用层 —— pi 把它做成扩展（`pi-web-access`），Claude Code 把它做成 MCP server。放进 core 要额外背一整套成本：embedding 调用、索引刷新、以及「代码一改索引就过期」的一致性维护，而这些成本在 coding 场景里的收益是**负**的（精确匹配召回更高）。
3. **它回答不了我真正的问题。** 我那三个失败案例的归因是「模型没做对、但没意识到自己没做对」—— 这是**验收信号缺失**，不是知识缺失。加 RAG 一点都不会改善。

**什么时候才该做？** 数据是非结构化、语义模糊、没有精确关键词可用时：产品文档、客服工单、会议纪要、合同条款。或者代码库大到「根本不知道该用什么关键词搜」—— 那种情况也是 hybrid（先 BM25 召回、再 rerank），不是纯向量。

**唯一我会考虑放进 loca 的检索是「跨会话记忆检索」** —— 历史会话积累到上千条之后，用「上次那个超时 bug 是怎么修的」这种模糊意图去翻旧账，是有真实收益的。但那属于 **memory 层**的功能而不是 RAG 层，而且它应该挂在工具层，**不动 core**。

---

## 七、维护方式

投递前如果代码有更新，重新取一遍数字，别用旧数：

1. 测试数量与通过情况
   `pytest -m "not live" --junitxml=r.xml` → 读 `r.xml` 里 `tests` / `failures` / `errors` / `skipped`
   （直接看终端汇总行不可靠；`--collect-only -q` 的输出是「每文件一行计数」，不能按 `::` 过滤）
   想按文件拆分数，把 `r.xml` 按 `testcase` 的 `classname` 分组统计。
2. 源码 / 测试行数：`loca/`（**要排除 `loca/eval/tasks/`**，那是评测夹具不是 harness 代码）与 `tests/` 下 `.py` 文件总行数
3. 静态检查：`ruff check .`
4. 评测跑分：`loca bench run --workers 4 --out report.json --json`，取 `pass_at_1` / `by_difficulty` / `cost`

**投递前最后一步**：git 提交并推送，让仓库状态与简历描述的数字对得上。
当前工作区里还压着**审查后的 26 项修复**（未提交），先提交这批，仓库的
`8,380 行 / 7,520 行 / 434 项` 才与远端一致。建议按批拆开提交
（Week 4 / Windows-only / 改名 / Week 5 / Week 6 / 审查修复），读起来像一条真实的演进线。
