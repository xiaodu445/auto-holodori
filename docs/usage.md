# 入口、模型与 Skill 使用说明

## 初始化知识库

```powershell
$env:PYTHONPATH = "src"
python -m modular_agent init
```

该命令只创建缺失的知识库、Skill 与 Prompt 模板，不会覆盖已有内容。

## 配置模型 API

复制 [model.example.json](../config/model.example.json) 为 `config/model.json`，填写模型和服务地址。`model.json` 不能包含 API Key。

```powershell
Copy-Item config\model.example.json config\model.json
$env:OPENAI_API_KEY = "在当前终端会话中设置的密钥"
python -m modular_agent run --goal "为每日任务制定下一步计划"
```

也可临时覆盖：

```powershell
python -m modular_agent run --goal "分析当前状态" --provider openai_responses --model "你的模型名" --base-url "https://你的服务地址/v1" --api-key-env "你的密钥环境变量名"
```

当前提供两种 provider：

- `mock`：不联网、不需要密钥，用于验证入口和输出格式。
- `openai_responses`：请求 `POST {base_url}/responses`。适用于 OpenAI Responses API；只有兼容该接口的服务才能使用。

模型调用采用 Responses API 的 `model`、`instructions`、`input` 字段；密钥使用环境变量，且默认 `store: false`。可参阅 OpenAI 官方 [Python SDK 与 API 指南](https://developers.openai.com/zh-Hans/api/docs/libraries) 和 [Responses 创建接口](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)。

## CLI 输出格式

所有入口输出均为一行 JSON，便于 UI、日志或后续进程消费。

`init`：

```json
{"created": ["knowledge/README.md", "skills/README.md"]}
```

`run`：

```json
{"config":{"provider":"mock","model":"mock-general-agent"},"output":"{...}"}
```

输出里的 `config` 不会包含 API Key。`output` 为模型返回的原始 JSON 文本；调用方必须用下面的 Agent Decision Schema 验证后才能执行。

## Skill 调用契约

Skill 必须在 `can_handle(state)` 返回真后才允许 `execute(state)`；所有成功结果都必须经 `verify(before, result, after)` 复核。`execute` 返回 `SkillResult`：

```json
{"outcome":"success|failure|unknown","data":{},"message":"面向经验沉淀的摘要"}
```

Skill manifest 的完整字段和 Agent 决策输出格式由 `docs/schemas/` 中的 JSON Schema 定义。新 Skill 的目录和验收要求见 [skills/README.md](../skills/README.md)。

## 当前识别扩展接口（2026-10-02）

识别模块保持原full兼容，新增独立OCR/UIA/CV/模板开关、桌面ROI、指定模板、单次缩放/阈值、find_text/find_templates/wait_for。详见 [识别接口说明](general-vision.md)。本地组件应通过这些接口减少无关计算，并保留未知状态与完整识别兜底；不缓存历史坐标，不同时控制键鼠。当前已实现启动与强欲之牌入口树，尚未实现下注/卡牌策略。
