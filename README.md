# Crush Chat Analyzer · 聊天分析助手

- **版本**：v1.1.9
- **制作者**：胡胜杰
- **默认模型**：DeepSeek `deepseek-chat`
- **仓库**：https://github.com/Hu080608/CrushChatAnalyzer
- **许可证**：MIT

一个用于导入 / 接入微信聊天记录、分析对方情绪与表达、辅助 AI 回复和自动回复的 Windows 桌面小工具。

> AI 分析是概率推测，不是读心术。请把它当成沟通复盘工具，不要用于骚扰、操控、跟踪或侵犯隐私。

---

## 功能总览

### 聊天记录

- 导入微信导出的 `txt` / `csv` / `tsv` / `json` / `jsonl`
- 支持微信 PC 复制文本、WeChatMsg / PyWxDump 等工具导出格式
- 自动识别常见列名：`StrTime`、`NickName`、`StrContent`、`IsSender`、`CreateTime`
- 支持内置示例聊天数据
- 支持导出双方聊天记录：`txt` / `csv` / `json`
- 支持聊天记录关键词搜索：上一个 / 下一个、当前匹配高亮
- 支持“我是”身份选择：默认优先选择“我”，识别反了可手动切换
- 聊天记录页和 AI 分析页身份选择同步

### 微信接入

- exe 已内置兼容后端 `wechatauto`
- 不需要额外安装 Python 3.11
- 不需要额外安装 `wxauto`
- 支持本地数据库读取模式：读取聊天记录、刷新会话、自动回复轮询不反复弹窗
- 支持微信会话列表搜索
- 支持读取图片 / 语音 / 表情包 / 视频 / 文件 / 链接 / 位置等消息类型

### AI 分析

- 本地速览：不联网、不消耗 token
- DeepSeek 分析：对方情绪、对方态度、我的表达复盘、可调整话术、下一步建议、风险与边界
- 支持 Markdown 展示：标题、列表、粗体 / 斜体、代码块、引用、链接、表格
- 支持 Markdown 报告导出

### Token 与费用

- 显示本次调用 token / 估算费用
- 显示累计调用次数 / token / 费用
- 支持自定义价格：缓存命中输入、缓存未命中输入、输出、货币
- 实际扣费以 DeepSeek 官方账单为准

### 智能回复

- 生成 1~5 条不同风格回复，显示风格、理由、风险等级
- 可复制，也可直接发送到微信
- 发送目标支持搜索联系人
- 生成时参考聊天上下文、System persona、梗 / 游戏知识库

### 自动回复

- 支持指定微信联系人
- 支持演练模式：只生成不发送
- 支持自动回复风格：自然、温柔、幽默、高冷、热情、正式、俏皮
- 支持微信表情代码：`[旺柴]` `[呲牙]` `[OK]` `[合十]` `[尴尬]`
- 支持等待对方说完：对方连发多条消息会合并；生成回复期间对方又发消息会取消发送并合并到下一轮
- 支持轮询间隔、每分钟发送上限、跳过关键词

### 图片 / 语音识别（可选）

- 支持下载图片和语音
- 支持 OpenAI 兼容视觉接口 `/chat/completions`
- 支持 OpenAI 兼容语音转文字接口 `/audio/transcriptions`
- 可接入本地模型服务，实现免费识别
- 未配置时仅显示 `[图片]` / `[语音]` / `[动画表情]`

### 梗 / 游戏知识库

- 设置页可填写梗、游戏、网络用语、作品设定
- AI 分析、智能回复、自动回复都会参考
- 智能回复页和自动回复页都有“去设置知识库”入口

---

## 快速开始

### 方式一：直接使用 exe（推荐普通用户）

下载 Releases 中的：

```text
CrushChatAnalyzer_v1.1.9.exe
```

双击运行。不需要安装 Python，不需要额外配置运行环境。

### 方式二：源码运行

环境要求：

- Python 3.10+
- Windows 10 / 11（直接接入微信时需要）
- 核心程序不需要第三方 Python 包

启动：

```bash
python main.py
```

或者：

```bash
python -m crush_analyzer
```

Windows 下也可以双击 `启动.bat`。

### 方式三：源码安装微信自动化后端（可选）

```powershell
python -m pip install wechatauto-replica --no-deps
python -m pip install uiautomation pyperclip Pillow psutil colorama pywin32 cryptography
```

---

## 使用流程

1. 启动程序
2. 进入 **设置** 填写 DeepSeek API Key
3. 点击 **测试 API 连接**
4. 点击 **导入聊天记录**，或到 **微信接入** 页连接微信
5. 在 **聊天记录** 页确认“我是”
6. 进入 **AI 分析** 页开始分析
7. 进入 **智能回复** 页生成回复
8. 需要自动回复时，到 **微信接入 / 自动回复** 页

---

## 微信接入说明

### 读取聊天记录

优先使用本地数据库模式：不反复弹窗、不抢占前台、适合自动回复轮询。

### 发送消息

发送时使用 Win32 键盘 + 剪贴板：不需要 `winsdk`、不需要 OCR；会自动点击搜索框、打开会话、点击输入框；已修复“先单独发送联系人名字”的 bug。

### 微信版本兼容

不同微信版本可能行为不同。读取失败时可以改用文件导入，也可以点击 **诊断后端** 查看搜索路径和错误。

---

## 设置说明

### 1. 接口配置

填写 API Key、Base URL、模型、Temperature、Max tokens、超时。

默认：

```text
Base URL：https://api.deepseek.com
模型：deepseek-chat
```

### 2. 费用估算

填写模型单价，用于估算 token 费用。

### 3. 图片 / 语音识别

可选功能：媒体 Base URL、媒体 API Key、视觉模型、语音转文字模型、每次最多识别条数。

### 4. 分析上下文

- AI 上下文消息数：10 ~ 5000，默认 120
- AI 上下文字符数：1000 ~ 500000，默认 18000
- 微信导入最多消息数：10 ~ 200000，默认 5000
- System persona
- 梗 / 游戏知识库

### 5. 自动回复

- 等待对方说完（秒）：默认 6
- 轮询秒数
- 每分钟上限
- 跳过关键词
- 自动回复风格
- 微信表情代码开关
- 演练模式

---

## 项目结构

```text
CrushChatAnalyzer/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/ci.yml
├── assets/
│   ├── icon.ico
│   └── icon.png
├── crush_analyzer/
│   ├── analyzer.py
│   ├── auto_reply.py
│   ├── config.py
│   ├── deepseek.py
│   ├── importers.py
│   ├── media_ai.py
│   ├── models.py
│   ├── prompts.py
│   ├── sample_data.py
│   ├── storage.py
│   ├── wechat.py
│   └── ui/
│       ├── main_window.py
│       ├── dialogs.py
│       └── widgets.py
├── tests/
├── build_exe.py
├── main.py
├── 启动.bat
├── 打包成exe.bat
├── 使用说明.md
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
└── CHANGELOG.md
```

---

## 打包成 exe

```bash
python build_exe.py
```

或双击 `打包成exe.bat`。每次打包会自动递增 patch 版本号。

生成文件：

```text
dist/CrushChatAnalyzer_v<版本号>.exe
```

---

## 测试

```bash
python -m unittest discover -s tests -v
```

当前测试覆盖聊天导入、本地统计、SQLite 存储、DeepSeek 请求和错误处理、回复 JSON 解析、自动回复逻辑。

---

## GitHub 协作

- 提交 Bug：使用 `.github/ISSUE_TEMPLATE/bug_report.md`
- 提交功能建议：使用 `.github/ISSUE_TEMPLATE/feature_request.md`
- 提交 PR：参考 `.github/PULL_REQUEST_TEMPLATE.md`

提交前请确保不要包含：

```text
API Key
config.json
crush_chat.db
聊天记录导出
logs/
dist/
__pycache__/
```

---

## 隐私与免责声明

- 聊天记录保存在本地 SQLite
- API Key 保存在本机用户目录
- 调用 DeepSeek 时，聊天上下文会发送给模型服务商
- 请确认你有权处理相关聊天记录
- 不要公开他人隐私
- AI 分析结果仅供参考，不构成心理诊断或关系建议
- 请尊重对方边界，不要用于骚扰、操控或跟踪

---

## 许可证

MIT License，见 `LICENSE`。

---

## 致谢

- DeepSeek
- wechatauto / wxauto
- 所有提交 Issue、PR 和反馈的用户
