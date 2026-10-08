# 会话、检查点与回滚

> 写给第一次用 loca 的人。所有命令和输出都在真机上跑过，可以直接照抄。
>
> 相关文档：[CLI 运行指南](running-the-cli.md) · [Web GUI 运行指南](running-the-web-gui.md)

---

## 一、这一页解决什么问题

Week 4 之前，`loca chat` 的记忆只活在内存里：**关掉窗口，一切归零**。它还有一个隐患 —— 模型可以随意改你的文件，改坏了没有任何退路。

Week 4 补上两件事：

| 能力 | 一句话解释 |
|---|---|
| **会话（session）** | 每轮对话都写进一个 SQLite 数据库。明天打开电脑，`--session <id>` 就能接着上次聊。 |
| **检查点（checkpoint）** | 每个「要改文件的工具」执行**之前**，先把文件原样存一份。改坏了，`rollback` 一键还原。 |

还有一个顺带升级：**上下文装满时不再直接丢历史，而是先让模型把它压缩成摘要**（详见第六节）。

---

## 二、会话存在哪里

默认路径：

```
C:\Users\<你的用户名>\.loca\sessions.db
```

启动 `loca chat` 时它会打印出来，例如：

```
session 20260911-113509-a1b2c3 (new) · db C:\Users\nono\.loca\sessions.db
```

**为什么放在用户目录，而不是项目里？** 因为一个数据库可以存所有项目的会话，每条会话都记了自己的 `workspace`，不会串。而且不会污染你的 git 仓库。

想换个位置，两种办法：

- 命令行加 `--db D:\somewhere\sessions.db`
- 或者设环境变量 `LOCA_DB`（优先级更高，测试和 CI 用它）

> **不想留痕？** 加 `--no-save`：不写数据库，也不做检查点。功能和 Week 3 完全一样。

这个文件是标准 SQLite，用任何 SQLite 客户端（比如 VS Code 的 SQLite 插件）都能直接打开看。

---

## 三、一次会话的生命周期

```
第一次运行                                第二天
─────────────────────────────            ─────────────────────────────
loca chat --session demo                 loca chat --session demo
   ↓ 不存在 → 新建 "demo"                    ↓ 已存在 → 载入历史消息
你和它聊了 3 轮                            你说「接着上次那件事」
   ↓ 每轮结束都写库                          ↓ 模型看得到上次的全部对话
退出（exit / Ctrl+C）
   ↓ 数据留在 sessions.db，不会丢
```

启动时会明确告诉你这次是**新建**还是**恢复**，不会有「我以为接上了，其实没接上」这种事：

```
session demo (new) · db ...
session demo (resumed, 5 message(s)) · db ...
```

**每轮结束存的是什么？** 是「模型实际看到的那整份对话」，不是原始日志。所以如果中途发生过上下文压缩，库里存的也是压缩后的版本 —— 保证你第二天恢复时，和模型看到的一致。

---

## 四、三个会话命令

```bash
loca chat --session demo           # 恢复会话 demo，不存在则以这个名字新建
loca chat --session demo --no-save # 不落库的一次性对话
loca sessions                      # 列出最近的会话
loca sessions show demo            # 看某次会话的完整对话 + 检查点
loca sessions rm demo              # 删除（消息和检查点一起删）
```

`loca sessions` 长这样：

```
session                  updated (UTC)        msgs  title
demo                     2026-09-11T11:35:11     7  Create hello.py containing exactly: print("v1")
20260910-201233-9f8e1d   2026-09-10T12:12:44    42  fix the failing parser test
```

标题是**自动取的第一条用户消息**（太长会截断）。想改？目前直接改库或者删了重来。

`loca sessions show demo` 会打印每条消息的角色和内容，末尾附上检查点清单 —— 那个清单就是**回滚时要填的 step 号**：

```
messages  7 · 3 model step(s) so far
------------------------------------------------------------------------
[  0] system    You are loca, a coding assistant running on Windows. ...
[  1] user      Create hello.py containing exactly: print("v1")
[  2] assistant  → write_file()
[  3] tool      Successfully wrote 12 bytes to ... (tool result)
------------------------------------------------------------------------
checkpoints (rollback target → files snapshotted before that step):
  step   0  write_file  2026-09-11T11:35:10
  step   2  edit_file   2026-09-11T11:35:18
```

---

## 五、回滚：把文件改回去

### 命令长什么样

```bash
loca rollback <会话id> <step>
```

**语义一句话**：把工作区还原成「第 `<step>` 步**执行之前**的样子」——也就是撤销第 `step` 步**以及它之后的所有改动**。

`<step>` 填 `0` 就是「撤销这次会话的全部文件改动」。

### 真实例子

下面是一次真机运行（模型自己动手改的文件）：

```bash
# 第一轮：让模型建文件（过程省略）
$ loca chat --session demo --workspace C:/tmp/ws
→ write_file(path='hello.py', content='print("v1")')
⛁ checkpoint @ step 0 · hello.py          ← 先存快照，再动手

$ cat ws/hello.py
print("v1")

# 第二轮（新开一个进程！）：让它改成 v2
$ loca chat --session demo --workspace C:/tmp/ws
session demo (resumed, 5 message(s)) · db ...
→ edit_file(path='hello.py', find='print("v1")', replace='print("v2")')
⛁ checkpoint @ step 2 · hello.py

$ cat ws/hello.py
print("v2")

# 撤销第 2 步那次编辑
$ loca rollback demo 2
restored hello.py

1 checkpoint(s) applied · 1 file(s) affected

$ cat ws/hello.py
print("v1")                                ← 回来了

# 撤到底：hello.py 本来就是这次会话新建的，所以应该消失
$ loca rollback demo 0
deleted  hello.py (did not exist before that step)

2 checkpoint(s) applied · 1 file(s) affected

$ ls ws/hello.py
ls: cannot access: No such file or directory  ← 对，本来就没有它
```

### 三条容易踩的规则

**1. 新建的文件会被「删掉」，不是「清空」。**
「之前不存在」和「之前是空文件」是两件事，loca 分得很清。上面例子最后一步就是这个行为。

**2. 多个检查点会按「从新到旧」依次应用。**
所以同一个文件被改了两次时，回滚到最早那步，得到的是**最早那份内容**。如果只应用目标那一步，后面几次的改动反而会残留 —— 那就不叫回滚了。

**3. 报告按「最终结果」汇总，而不是流水账。**
上面 `rollback demo 0` 内部其实做了两件事（先还原成 `v1`，再删掉），但只告诉你最后落在哪个状态：

```
deleted  hello.py (did not exist before that step)
```

### 明确做不到的事

| 限制 | 原因 |
|---|---|
| **`shell` 造成的改动回滚不了** | shell 能碰任何东西，为每条命令快照整个工作区不现实。命令输出里会提醒你这一点。 |
| **超过 2 MB 的文件只记名字，不存内容** | 不想让会话数据库变成垃圾场。这类文件在报告里会标 `skipped`。 |
| **默认只认 `write_file` / `edit_file`** | 这两个是「改文件」的工具。要加别的，在 `CheckpointManager(tracked=...)` 里注册 `{工具名: (参数名,)}` 即可。 |
| **不会动工作区以外的东西** | 快照和还原都走同一套沙箱检查，`../` 越界一律拒绝。 |

### 不想离开 REPL？敲 `/rollback`

以前撤销要"退出会话 → `loca sessions show` 找到 step → 再 `loca rollback`"，中间隔着两个进程。REPL 里现在直接可用：

```
you › /rollback          # 撤销最近一次文件改动（= 最后那个检查点）
you › /rollback 2        # 撤销第 2 步及其之后的全部改动
```

不带参数时它取**最后一个检查点**的 step —— 因为对操作的人而言「撤销」天然就是「撤销刚才那一下」。输出和 `loca rollback` 一字不差（两处共用同一个渲染函数，不会各写一套）。

### 在 Web GUI 里也一样

浏览器页面里，每个检查点都会在对话中留下一行，后面直接跟着一个撤销按钮：

```
⛁ checkpoint @ step 3 · notes.txt   [ ↩ undo from step 3 ]
```

点它 → 确认 → 调 `POST /api/rollback`，语义与 `loca rollback demo 3` 完全相同。区别只有两点：

- **工作区可能中途换过。** 网页允许每轮改工作区，所以回滚**不会**用"你当前指着的目录"，而是用**每个检查点自己记录的那个工作区** —— 否则两个目录里同名的文件会被写串。CLI 一个会话只认一个工作区，不存在这个问题。
- **对话不会跟着回退。** 磁盘上的文件还原了，聊天记录里那几句"我已经改好了"还在。以文件为准。

顶栏会显示这次对话的 `session <id>`。刷新页面会**新开一个会话**（旧会话和它的检查点仍在库里），所以想接着撤销旧会话，就把那个 id 复制到终端：

```bash
loca sessions show 20260926-131621-a1b2c3    # 看检查点清单
loca rollback 20260926-131621-a1b2c3 3       # 和点按钮等价
```

> Web 端和 CLI 用的是**同一个** `~/.loca/sessions.db`，所以两边可以互相接手 —— 这正是把会话落盘、而不是只在内存里维护一份历史的意义。

---

## 六、上下文压缩（顺带升级）

模型一次能看的字数（上下文窗口）是有限的。聊久了必然装不下，Week 3 的做法是**把最老的消息丢掉** —— 安全，但 agent 会忘掉自己刚才干了什么。

Week 4 换成：**先让模型把老消息压成一段摘要**，再扔掉原文。

```
超过预算时：
  [system] + 20 条老消息 + 最近 6 条
        ↓  让模型写一段「之前做了什么」的摘要
  [system] + 【对话摘要】+ 最近 6 条        ← 信息还在，token 少了很多
```

你会看到这样一行：

```
context compacted: 11 old message(s) → summary (~120 tokens), now ~890/2000
```

三个相关开关：

| 参数 | 默认 | 作用 |
|---|---|---|
| `--token-budget N` | 48000 | 上下文预算。填 `0` 完全关闭上下文管理 |
| `--no-summarize` | 关（即默认会摘要） | 退回「直接丢」的老行为 |
| `--keep-recent N` | 6 | 最近的 N 条消息永远原样保留 |

**任何时候想手动压缩**，在 REPL 里敲：

```
you › /compact
compacted: earlier turns folded into a summary
```

另外 `/help` 看命令、`/session` 看当前会话 id 和消息数、`/rollback` 撤销文件改动。

> **一个细节**：摘要被存成一条 `user` 消息（带 `[Earlier conversation summary]` 标记），不是 `system` 消息。因为回灌历史时会滤掉 `system`（防止系统提示词重复插入），存成 `system` 的话摘要会在恢复会话时消失。

---

## 七、常见问题

**Q：`rollback` 说 `no checkpoints at step N or later`，什么意思？**
那个 step 范围内没有检查点。多半是：这步只跑了 `shell`，或者只调了 `read_file` 这种不改文件的工具。用 `loca sessions show <id>` 看真实的检查点清单。

**Q：聊了好几轮，一个 `⛁ checkpoint` 都没看到？**
说明这几轮里没有**写文件**的工具调用 —— 只有 `write_file` / `edit_file` 会产生快照，`read_file` / `shell` 都不会（`shell` 改了文件也不记，这正是它撤不回来的原因）。另一个可能是 CLI 加了 `--no-save`：那时既不落库也不做检查点，是刻意的一次性模式。

**Q：`rollback` 输出里有 `skipped`？**
三种可能：文件超过 2 MB（没存内容）、快照指向工作区外、或者没有权限写入。原因都写在括号里。

**Q：换个地方打开同一个会话，回滚会写到哪？**
默认写回**会话记录里的工作区**（库里有 `workspace` 字段）。想在别处还原（比如把工作区挪了位置），显式指定：`loca rollback demo 2 --workspace D:\new\path`。

**Q：会话数据库会不会把 API key 存进去？**
不会。只存对话消息、元数据和文件快照。key 始终只在 `.env` 里。

**Q：能删掉所有会话吗？**
`loca sessions` 看 id，逐个 `loca sessions rm <id>`。想全清就直接删那个 `.db` 文件（连同 `-wal` / `-shm` 两个同名的临时文件）。

**Q：会上传我的代码吗？**
快照和消息都只存在本机那个数据库文件里，不会发到任何地方。发出去的只有对话内容本身（本来就发给 DeepSeek 的那些）。

---

## 八、一页速查

```bash
# 会话
loca chat --session demo              # 恢复或新建
loca chat --no-save                   # 不留痕
loca sessions                         # 列出
loca sessions show demo               # 详情（含检查点清单）
loca sessions rm demo                 # 删除

# 回滚
loca rollback demo 2                  # 撤销第 2 步及其之后
loca rollback demo 0                  # 撤销这次会话的所有文件改动

# REPL 内
/help                                 # 帮助
/compact                              # 手动压缩上下文
/rollback                             # 撤销最近一次文件改动
/rollback <step>                      # 撤销第 step 步及其之后
/session                              # 当前会话信息
exit                                  # 退出（也可 quit / :q / Ctrl-C）

# Web GUI 里
#   对话里 ⛁ 那行后面的 ↩ undo        # 等价于 loca rollback <session> <step>
#   顶栏 session <id> 可复制到终端接手

# 常用参数
--db <path>         会话数据库位置（默认 ~/.loca/sessions.db）
--token-budget N    上下文预算，0 = 关闭
--no-summarize      改为直接丢弃旧消息
--keep-recent N     压缩时原样保留最近 N 条
```

**文件在哪**

```
~/.loca/sessions.db              会话库（sessions / messages / checkpoints 三张表）
loca/observability/storage.py    持久化实现
loca/observability/checkpoint.py 快照与回滚实现
loca/core/context.py             token 计数与摘要压缩
```
