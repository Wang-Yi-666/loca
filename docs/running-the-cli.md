# 运行 CLI：从哪启动、怎么用

> 目标：你能自己把 loca 的命令行界面跑起来、看懂它的输出、正常退出。
> 文中的命令和输出都在本机实测过。

---

## 一、CLI 和 Web GUI 该用哪个？

两个界面背后是同一套东西（同一个 agent 循环、同样四个工具），区别只在"你从哪跟它说话"。

| | **CLI（`loca chat`）** | **Web GUI（`loca serve`）** |
|---|---|---|
| 界面 | 终端里的文字对话 | 浏览器里的聊天页面 |
| 启动 | 按一次 F5，立刻就能聊 | 要等服务器起来、再开浏览器 |
| 看工具调用 | 直接打印在终端里，一行一条，清楚 | 渲染成卡片气泡，比较好看 |
| 适合 | 调试、快速试、想看清每一步 | 演示、截图、给别人看 |
| 关掉 | 终端里 `Ctrl+C` | 见 [Web GUI 指南](running-the-web-gui.md) |

简单说：**自己用、想搞清楚它在干嘛 → CLI；要展示 → GUI。**

---

## 二、启动方式 A：VS Code（推荐）

你以 VS Code 为基准，走这条最省事：

1. VS Code 打开项目文件夹 `D:\Projects\loca`
2. 按 **`Ctrl + Shift + D`** 打开左侧的 **运行和调试** 面板
3. 顶部下拉框里选 **`loca chat (CLI REPL)`**
4. 按 **`F5`**

集成终端会弹出来，显示：

```
loca · provider deepseek · 4 tool(s) · workspace D:\Projects\loca
Type 'exit' or Ctrl-C to quit.


you:
```

看到 `you:` 这个提示符，就可以开始打字了 —— 这就是它在等你说话。

### 这几行怎么读

| 输出 | 含义 |
|---|---|
| `loca` | 程序名 |
| `provider deepseek` | 当前用哪个大模型厂商（由 `.env` 里的配置决定） |
| `4 tool(s)` | 它有 4 个工具可用：读文件、写文件、改文件、跑命令 |
| `workspace D:\Projects\loca` | **它的"活动范围"** —— 工具只能在这个目录里操作，见第五节 |
| `Type 'exit' or Ctrl-C to quit.` | 怎么退出 |

> **看不到输出？** 可能是终端没获得焦点，或者 F5 选错了配置。点一下终端区域再试。
> 如果下拉框里根本没有 `loca chat (CLI REPL)` 这一项，说明调试器扩展没装好——VS Code 右下角通常会弹窗提示装推荐扩展，点"安装"即可。

---

## 三、启动方式 B：用终端

不想用调试面板，也可以直接在终端跑。

1. 在 VS Code 里按 **`` Ctrl + ` ``**（反引号，Esc 下面那个）打开集成终端
2. 敲这一行回车：

```
.venv\Scripts\python.exe -m loca.cli chat
```

### 为什么不直接敲 `loca chat`？

因为 `loca` 这个快捷方式（`loca.exe`）装在 `.venv\Scripts\` 里，**虚拟环境没激活时系统不知道去哪找**，会报"不是内部或外部命令"。

两个办法：

- **完整路径（上面那条）**：`-m loca.cli` 的意思是"把 loca 包里的 cli 模块当程序跑"。永远有效。
- **激活虚拟环境**：

  ```
  .venv\Scripts\activate
  loca chat
  ```

  激活成功后命令行前面会多出 `(.venv)`，用完敲 `deactivate` 退出。

---

## 四、怎么跟它对话

### 输入

在 `you:` 后面打字，**回车发送**。它会用流式方式一个字一个字回你。

### 工具调用长什么样

这是它和普通聊天机器人最大的区别：它会**自己动手**。

下面是一次真实对话（我把输入回显补在了 `you:` 后面，方便阅读）：

```
you: 用 read_file 读 README.md，告诉我第一行是什么
assistant → read_file(path='README.md', end_line=1)
✓ read_file
<file path=D:\Projects\loca\README.md total_lines=266 showing=1>
     0  # Loca
README.md 的第一行是：`# Loca`
steps 2  ·  tokens 2134  ·  finish stop  ·  prompt 1079 · completion 12
```

逐行读：

| 输出 | 含义 |
|---|---|
| `→ read_file(path='README.md', ...)` | 模型决定调用这个工具，括号里是它传的参数 |
| `✓ read_file` | 工具执行**成功**（失败会是红色的 `✗`） |
| `<file path=... total_lines=266 showing=1>` | 工具返回的内容开头（太长会被截断，只显示前几行） |
| `assistant ...` | 拿到结果后，模型接着说的人话 |
| `steps 2 · tokens 2134 · finish stop` | 这一轮的统计，见下 |

### 一轮结束的统计怎么读

| 字段 | 含义 |
|---|---|
| `steps 2` | 这一轮模型被调用了 2 次（第一次决定调工具，第二次总结结果） |
| `tokens 2134` | 这次对话一共消耗的 token 数（关系到 API 花多少钱） |
| `finish stop` | 结束原因。`stop` = 正常答完；`max_steps` = 步数到上限被截断 |
| `prompt 1079 · completion 12` | 拆开看：发给模型的 1079，模型生成的 12 |

### 退出

四种写法都行：

- 输入 `exit`
- 输入 `quit`
- 输入 `:q`
- 按 `Ctrl + C`（或 `Ctrl + D`）

→ 会看到 `bye`，程序结束。

### 一个重要细节：`Ctrl+C` 有两种含义

| 什么时候按 | 效果 |
|---|---|
| 它**正在回答**的时候按 | **只打断这一轮**，回到 `you:` 等你重新提问，程序不退出 |
| 它在 `you:` **等你输入**的时候按 | **退出程序** |

所以如果它答到一半答偏了，直接 `Ctrl+C` 打断，重新问就行，不用重开。

---

## 五、最关键的概念：工作目录（workspace）

这是最容易搞混、也最容易踩坑的地方。

**它的 4 个工具只能在你指定的那个目录里活动**，这就是"沙箱"。跑出这个范围的路径（比如 `../` 往上级目录翻）会被拒绝。

启动时打印的那一行就是在告诉你范围：

```
loca · provider deepseek · 4 tool(s) · workspace D:\Projects\loca
                                                ^^^^^^^^^^^^^^^^^^ 就是这个
```

### 两个配置，两个范围

VS Code 的下拉框里给了你两个选择：

| 配置名 | 工作目录 | 什么时候用 |
|---|---|---|
| **`loca chat (CLI REPL)`** | `D:\Projects\loca`（项目根） | 想让它读/改**这个项目**的代码时。和 Web GUI 的范围一致 |
| **`loca chat (sandboxed to playground/)`** | `D:\Projects\loca\playground`（空目录） | 想让它随便造文件、不怕搞乱项目时 |

### 这里有个真实的坑，我踩给你看

我一开始让 CLI 固定用 `playground\` 当工作目录，然后让它"在 playground 里创建 hello.py"，结果它写到了：

```
D:\Projects\loca\playground\playground\hello.py
                          ^^^^^^^^^^ 多套了一层
```

为什么？因为**模型不知道自己的工作目录叫 playground**，它按仓库的习惯去理解"playground 里"= 工作目录下再建一个 playground 子目录。它没做错，是目录名引起歧义。

所以现在改成了：

- **默认配置直接用项目根**，你说"读 README.md"就是项目里的 README.md，不会有歧义
- 沙箱模式仍然保留，但要注意：**在沙箱模式下说文件名就直接说 `hello.py`，别说 `playground/hello.py`**

---

## 六、常用参数

| 参数 | 默认值 | 作用 |
|---|---|---|
| `--workspace <目录>` | 当前目录 | 指定工具的活动范围 |
| `--no-tools` | 关 | 不暴露工具，纯聊天。用来隔离"是模型的问题还是工具的问题" |
| `--max-steps <N>` | `20` | 一轮最多调几次模型，防止它绕圈绕不停 |
| `--token-budget <N>` | `48000` | 上下文预算，超了就自动丢掉最早的对话 |
| `--system "<提示词>"` | 内置 | 换掉系统提示词，改它的行为风格 |
| `--provider <名字>` | `deepseek` | 换厂商（OpenAI / Anthropic 目前是占位实现，还没接） |

用法示例（终端里）：

```
.venv\Scripts\python.exe -m loca.cli chat --workspace D:\some\repo --max-steps 10
```

---

## 七、常见问题

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 敲 `loca chat` 报"不是内部或外部命令" | 虚拟环境没激活，PATH 找不到 | 用 `.venv\Scripts\python.exe -m loca.cli chat` |
| F5 之后终端里没有 `you:` | 选错配置，或终端没焦点 | 确认下拉框选的是 `loca chat (CLI REPL)`；点一下终端区域 |
| 下拉框里没有 loca 的配置 | 调试器扩展没装 | 装 VS Code 推荐的 `ms-python.python` 和 `ms-python.debugpy` |
| 打字没反应 / 打不进去 | 终端没获得键盘焦点 | 用鼠标点一下终端区域再打 |
| 它说"路径不在工作区内" | 路径沙箱拦截 | 正常行为。要么把文件放到工作目录里，要么用 `--workspace` 重新指定 |
| 每问一句都要重新自我介绍 | 正常，但多轮是保留上下文的 | `loop.last_transcript` 会回灌，所以它能记住这一局聊过什么。退出后不保存（持久化在 Week 4 做） |
| 输出里出现 `error: ...` | 调用模型失败或重试耗尽 | 看完整报错；常见是 key 无效或网络不通 |

---

## 八、一页速查

```bash
# 启动（VS Code：Ctrl+Shift+D → 选 loca chat (CLI REPL) → F5）
.venv\Scripts\python.exe -m loca.cli chat

# 指定工作目录
.venv\Scripts\python.exe -m loca.cli chat --workspace D:\some\repo

# 纯聊天（不调用工具）
.venv\Scripts\python.exe -m loca.cli chat --no-tools

# 退出：输入 exit / quit / :q，或按 Ctrl+C
# 它答到一半想打断：Ctrl+C（只打断这一轮，不退出）
```

拿到 `you:` 提示符就能开始对话了。
