# Crush Chat Analyzer

- **版本**：自动迭代（以程序窗口标题为准）
- **制作者**：胡胜杰
- **默认模型**：DeepSeek `deepseek-chat`

一个分析你和 Crush / 对象聊天的小工具，默认使用 **DeepSeek**。

界面使用 Python 标准库 `tkinter/ttk`，聊天记录存在本地 SQLite，API Key 只保存在本机用户目录。
除了 AI 分析，也提供不联网的本地速览、回复建议、微信聊天导入和自动回复。

更详细的图文步骤见：`使用说明.md`。

> AI 分析是概率推测，不是读心术。请把它当成复盘工具，不要用它骚扰、试探或操控对方。

---

## 功能

- **图形化桌面界面**：会话列表、聊天记录、AI 分析、智能回复、微信接入、设置。
- **默认 DeepSeek**：兼容 OpenAI 格式，支持 `deepseek-chat`，也可以改成其他兼容接口。
- **Token 和费用显示**：每次调用后显示本次 token / 估算费用，并累计总 tokens / 总费用。
- **Markdown 展示**：AI 分析报告支持标题、列表、粗体、代码块、引用、链接和简单表格。
- **详细使用说明**：程序内置“使用说明”，项目根目录也提供 `使用说明.md`。
- **内置微信自动化后端**：已打包 `wechatauto` 兼容后端，也支持 `wxauto`；无需安装 Python 3.11。
- **导入微信聊天数据**
  - 微信 PC 端复制出来的 txt 文本；
  - WeChatMsg / PyWxDump 等工具导出的 txt / csv / json / jsonl；
  - 常见列名自动适配：`StrTime, NickName, StrContent, IsSender, CreateTime` 等。
- **微信接入（可选）**
  - exe 已内置 `wechatauto` 兼容后端，可直接尝试读取微信会话、导入聊天记录、发送消息；
  - 同时兼容原版 `wxauto`，如果你自己安装了 `wxauto`，会优先使用 `wxauto`；
  - 后端不可用时，聊天导入和分析功能仍然可用。
- **AI 分析**
  - 对方可能的情绪底色、情绪变化；
  - 对方对关系的兴趣、投入、回避信号；
  - 我的表达复盘：追问过多、情绪索取、话题自嗨、没接住情绪等；
  - 可执行的具体话术和下一步建议。
- **智能回复**
  - 生成 3~5 条不同风格的回复建议，附“为什么这么说”和风险等级；
  - 可一键复制，也可发送到已连接的微信。
- **自动回复**
  - 后台轮询指定微信联系人；
  - 调用 DeepSeek 生成自然回复；
  - 默认 **演练模式**：只生成、不发送；
  - 支持跳过关键词、每分钟限速、自己/对方身份识别。
- **本地速览**
  - 不依赖 API：消息量、谁先开口、回复间隔、平均长度、表情/问句数量、简单情绪词统计。

---

## 快速开始（0 基础开箱即用）

### 1. 环境要求

- Python 3.10+
- Windows / macOS / Linux
- 核心程序 **不需要安装任何第三方 Python 包**
  - GUI：`tkinter`（Python 自带）
  - 数据库：`sqlite3`（Python 自带）
  - 网络：`urllib` / `ssl`（Python 自带）
- 如果要直接接入微信：
  - Windows 微信 PC 版
  - 不需要额外安装 `wxauto`，exe 已内置 `wechatauto` 兼容后端

### 2. 最简单启动方式（Windows）

1. 安装 Python 3.10+：
   - 下载：https://www.python.org/downloads/
   - 安装时务必勾选 **Add Python to PATH**
2. 双击项目根目录：

```text
启动.bat
```

3. 按照界面提示操作即可。

如果双击后提示没有 Python，`启动.bat` 会自动打开 Python 官网下载页。

### 3. 只发一个 exe（推荐分发方式）

执行一次：

```text
打包成exe.bat
```

会生成单文件 exe：

```text
dist/CrushChatAnalyzer_v<版本号>.exe
```

分发时只需要发送这一个 exe：

- 不需要发送整个项目文件夹；
- 不需要发送 `examples`、文档或 Python 源码；
- exe 已内置示例聊天数据；
- 用户第一次打开就能导入示例；
- 核心分析、导入、Markdown 展示、Token/费用统计都能直接用。

> 直接连接微信需要目标电脑安装并登录微信 PC 版；exe 已内置 `wechatauto` 兼容后端，无需再装 Python 3.11 或 wxauto。

### 4. 命令行启动

```bash
python main.py
```

或者：

```bash
python -m crush_analyzer
```

核心程序只使用 Python 标准库，不需要执行任何 `pip install`。

### 3. 配置 DeepSeek

打开程序后进入 **设置**：

- **API Key**：填写你的 DeepSeek API Key，例如 `sk-...`；
- **Base URL**：默认 `https://api.deepseek.com`；
- **模型**：默认 `deepseek-chat`；
- 点击 **测试 API 连接**。

也可以使用环境变量，环境变量优先级更高：

```bash
set DEEPSEEK_API_KEY=sk-xxxx
```

配置文件默认位于：

- Windows：`%APPDATA%\CrushChatAnalyzer\config.json`
- macOS / Linux：`~/.config/crush_chat_analyzer/config.json`

聊天数据库位于同一目录下的 `crush_chat.db`。

### 4. 使用流程

1. 点击 **导入聊天记录**，选择导出的 txt / csv / json 文件；第一次打开软件会提供内置示例；
2. 如果软件认错了“我/对方”，在 **聊天记录** 页右上角选择 **我是：**；
3. 进入 **AI 分析** 页，选择分析重点，点击 **DeepSeek 分析**；
4. 想回复时进入 **智能回复** 页，填写你想要的效果，点击 **生成回复建议**；
5. 如果需要自动回复，进入 **微信接入 / 自动回复** 页，连接微信并选择联系人。

---

## 支持的导入格式

### 纯文本 txt

支持以下常见行格式：

```text
张三 2023-10-01 12:00:00
你好呀，今天怎么样？

李四 2023-10-01 12:01:00
刚看到，嘿嘿
```

也支持时间在前的形式：

```text
2023-10-01 20:00:00 小王
晚安

小王: 明天有空吗
```

### CSV / TSV

自动适配常见列名：

| 含义 | 常见列名 |
| --- | --- |
| 发送人 | `NickName`, `Sender`, `sender`, `from`, `Remark`, `Talker` |
| 内容 | `StrContent`, `Content`, `Msg`, `message`, `text` |
| 时间 | `StrTime`, `CreateTime`, `time`, `timestamp`, `date` |
| 是否我 | `IsSender`, `is_self`, `fromMe`, `direction` |

示例：

```csv
StrTime,NickName,StrContent,IsSender
2023-10-01 12:00:00,张三,你好,0
2023-10-01 12:01:00,李四,你也好,1
```

### JSON / JSONL

支持 `{"messages": [...]}`、`[...]`、`{"chat": [...]}`、`{"data": [...]}` 等结构。

```json
{
  "messages": [
    {"sender": "小王", "content": "在干嘛", "time": "2023-10-01 20:00:00", "is_self": true},
    {"sender": "小李", "content": "刚下班，你呢", "time": "2023-10-01 20:05:00", "is_self": false}
  ]
}
```

---

## 微信接入与自动回复

### 微信自动化后端

最终 exe 已经内置：

```text
wechatauto（wechatauto-replica 1.2.3）
```

所以正常情况下不需要再安装 `wxauto`，也不需要 Python 3.11。

读取聊天记录时，软件会优先使用**本地数据库读取模式**：

- 不会反复弹出 / 激活微信窗口；
- 导入聊天、自动回复轮询都通过数据库读取；
- 只有真正发送消息时才调用 GUI。

要求：

- Windows；
- 微信 PC 版已登录；
- 微信窗口不要最小化；
- 如果微信版本或系统升级导致后端不兼容，可以改用文件导入，或自行安装 `wxauto`。

### 手动导入微信聊天

1. 打开微信 PC 版，进入你想分析的聊天；
2. 在软件中点击 **连接微信**；
3. 点击 **刷新微信会话**；
4. 在列表中选择联系人；
5. 点击 **读取并导入到左侧**。

读取失败时，可以改用 WeChatMsg / PyWxDump 等工具导出带列名的 CSV / JSON 后再导入。

### 自动回复

1. 在 **设置** 中填写 **我的微信昵称**；
2. 在 **微信接入** 页连接微信并刷新会话；
3. 选中联系人，点击 **设为自动回复对象**；
4. 保持 **演练模式** 打勾，点击 **开始自动回复**；
5. 观察日志中的 AI 回复，确认语气和边界合适后，再取消演练模式。

安全限制：

- 默认只生成不发送；
- 命中“转账、验证码、链接、文件”等关键词时跳过回复；
- 限制每分钟发送次数；
- 无法可靠识别“我是谁”时，不建议关闭演练模式。

---

## 项目结构

```text
CrushChatAnalyzer/
├── 启动.bat                    # 源码版一键启动（Windows）
├── 打包成exe.bat               # 一键打包单文件 exe
├── 使用说明.md                 # 详细使用说明
├── README.md                   # 项目说明
├── main.py                     # 源码版启动入口
├── build_exe.py                # 自动迭代版本 + PyInstaller 打包
├── dist/
│   └── CrushChatAnalyzer_v<版本号>.exe   # 最终单文件 exe
├── crush_analyzer/
│   ├── __main__.py             # python -m crush_analyzer
│   ├── analyzer.py             # 本地统计和启发式速览
│   ├── auto_reply.py           # 自动回复后台服务
│   ├── config.py               # 配置读写
│   ├── deepseek.py             # DeepSeek / OpenAI 兼容客户端
│   ├── importers.py            # txt/csv/json 导入器
│   ├── models.py               # 数据模型
│   ├── prompts.py              # 提示词和 JSON 解析
│   ├── sample_data.py          # 内置示例聊天数据
│   ├── storage.py              # SQLite 持久化
│   ├── version.py              # 版本号
│   ├── versioning.py           # 版本自动迭代
│   ├── wechat.py               # 微信自动化适配层
│   └── ui/
│       ├── main_window.py      # 主窗口
│       ├── dialogs.py          # 对话框
│       └── widgets.py          # 聊天展示、Markdown 渲染等控件
└── tests/                      # unittest 测试
```

---

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖：

- txt / csv / json 导入；
- 本地统计与本地报告；
- SQLite 会话存储；
- DeepSeek 客户端请求和错误处理（使用假请求对象，不访问网络）；
- 模型 JSON 输出解析。

---

## 打包成 exe（可选）

方式一：双击

```text
打包成exe.bat
```

方式二：命令行

```bash
pip install pyinstaller
python build_exe.py
```

生成文件在：

```text
dist/CrushChatAnalyzer_v<版本号>.exe
```

每次执行打包脚本会自动把 patch 版本号 +1，不需要手动改版本。
打包为 **单文件 exe**，方便直接发给用户。
打包脚本会自动收集 `wechatauto`、`uiautomation`、`pywin32` 等微信自动化依赖；如果已安装 `wxauto`，也会一起收集。

---

## 隐私与边界

- 聊天记录保存在本地 `crush_chat.db`，不会主动上传到任何服务器；
- 调用 DeepSeek 时，选中的聊天上下文会发送给模型服务商，请自行确认对方隐私和你的授权；
- API Key 保存在本地配置文件中，请勿把电脑或配置文件分享给他人；
- AI 可能误判情绪、关系和潜台词，请结合真实沟通判断；
- 不鼓励查岗、跟踪、操控、PUA、骚扰或未经同意的自动化回复；
- 对方明确拒绝时，最好的工具是尊重和停止推进。

---

## 常见问题

**Q：导入后所有消息都显示成对方，怎么办？**

在 **聊天记录** 页右上角把 **我是：** 切换成你的昵称，软件会重新标记。

**Q：微信连接失败？**

- 先确认微信 PC 版已登录、窗口未最小化；
- 点击软件里的 **诊断 wxauto**，查看后端名称和错误；
- 最终 exe 已内置 `wechatauto` 1.2.3，不需要再手动安装 wxauto；
- 不同微信版本兼容性不同，也可以先用文件导入。

**Q：pip 提示 `Could not find a version ... (from versions: none)` 怎么办？**

原版 `wxauto` 对 Python 3.13 支持不好，所以会出现这个问题。

当前项目的最终 exe **已经内置了兼容后端 `wechatauto` 1.2.3**，所以：

- 不需要安装 Python 3.11；
- 不需要安装 wxauto；
- 直接双击 `dist/CrushChatAnalyzer_v<版本号>.exe` 即可尝试连接微信。

如果你一定要使用源码版，也可以安装兼容后端：

```powershell
python -m pip install wechatauto-replica --no-deps
python -m pip install uiautomation pyperclip Pillow psutil colorama pywin32 cryptography
python main.py
```

**Q：没有 API Key 能用吗？**

可以。导入、聊天查看、本地速览、自动回复的演练模式中的统计部分可用。
AI 分析和 AI 回复建议需要 API Key。

**Q：自动回复会不会回复到我自己？**

如果未填写 **我的微信昵称**，身份识别可能错误。因此默认开启演练模式，并强烈建议先填写昵称。

**Q：DeepSeek 之外还能接什么？**

任何 OpenAI 兼容接口都可以：把 Base URL 改成以 `/v1` 结尾的地址，并填写对应模型名。

---

## 开源与协作

- 许可证：MIT，见 `LICENSE`
- 贡献指南：`CONTRIBUTING.md`
- 行为准则：`CODE_OF_CONDUCT.md`
- 安全政策：`SECURITY.md`
- 更新日志：`CHANGELOG.md`
- CI：`.github/workflows/ci.yml`

### 提交 Issue / PR

- Bug 报告请使用 `.github/ISSUE_TEMPLATE/bug_report.md`
- 功能建议请使用 `.github/ISSUE_TEMPLATE/feature_request.md`
- Pull Request 请参考 `.github/PULL_REQUEST_TEMPLATE.md`

提交前请不要包含：

```text
API Key
crush_chat.db
config.json
聊天记录导出
logs/
dist/
__pycache__/
```

## 致谢

- DeepSeek：默认分析模型
- wechatauto / wxauto：微信自动化后端
- 所有提交 Issue 和 PR 的贡献者
