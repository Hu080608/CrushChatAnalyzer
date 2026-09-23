# 贡献指南

感谢你愿意为 Crush Chat Analyzer 做贡献。

## 开发环境

- Python 3.10+
- Windows（微信接入功能需要 Windows 微信 PC 版）
- 核心功能不需要第三方依赖，GUI 使用 tkinter，数据库使用 sqlite3

## 提交代码前

1. 运行测试：

```bash
python -m unittest discover -s tests -v
```

2. 确保没有提交以下内容：

- `config.json`
- `crush_chat.db`
- `logs/`
- `dist/`
- `__pycache__/`
- API Key、聊天记录等隐私数据

## 代码风格

- Python 缩进使用 4 个空格
- 文件编码使用 UTF-8
- 尽量保持 UI 文案为中文
- 新功能请补测试或说明无法自动测试的原因

## 提交 PR

1. Fork 本仓库
2. 新建分支：`feature/xxx` 或 `fix/xxx`
3. 提交前运行测试
4. 在 PR 中说明：
   - 改了什么
   - 为什么改
   - 如何测试

## 功能边界

- 不要提交鼓励骚扰、跟踪、操控或侵犯隐私的功能。
- 自动回复应默认安全、可关闭。
- 涉及微信自动化的功能要说明 wxauto / wechatauto 的兼容性风险。
