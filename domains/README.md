# Domains

公共引擎、模型/API 配置和通用感知程序保留在项目顶层。每个游戏、应用或垂直任务在 `domains/<domain>/` 中独立保存知识、Skill、视觉模板、小模型和数据。

使用 `python -m modular_agent domain-init --domain game_x` 创建领域。`_template/` 只作结构参考，不存放真实资源。
