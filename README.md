# Holodori 游戏 Agent

本仓库是日常使用的运行本体。通用 Agent 负责理解、规划、感知和执行；具体游戏流程、模板和模型按领域分类。

开发工具、在研寻路、训练集、标注与原录像已放到相邻的 **Game_agent_dev**，不进入本仓库。完整位置见 [工作区说明](docs/WORKSPACE_LAYOUT.md)。

## 运行入口

| 用途 | 入口 |
| --- | --- |
| 顶层 Agent | start_agent.cmd |
| 启动游戏 | run_game_startup.cmd |
| 日常任务 | run_daily_tasks.cmd；edit_daily_tasks_config.cmd 编辑计划 |
| 强欲之牌 | run_greed_cards_entry.cmd、run_greed_cards_play.cmd |
| 钓鱼 | run_fishing.cmd、run_fishing_loop.cmd |
| 跳绳 | run_jump_rope.cmd；F8开始/暂停、F9重置、F12退出 |
| 厨房 | kitchen_control.cmd、kitchen_play.cmd |
| 音游 | run_rhythm.cmd、run_rhythm_live.cmd、run_multi_live.cmd |
| 多人演出 GUI | run_hololive_dreams_gui.cmd |

各入口保留各自原有的实际输入条件、参数和热键。此次整理没有改变游戏策略或增加控制权限。

## 结构

```text
src/modular_agent/                     通用引擎与运行组件
domains/hololive_dreams/
  launch.json                         启动配置
  capabilities.json                   模型可读的能力接口和参数规范
  daily_tasks_config.json             日常编排，可调用小游戏
  models/
    fishing/ | greed_cards/ | rhythm/
    jump_rope/game_jump_live.py        当前跳绳主程序
    kitchen/kitchen_play.py            厨房主程序
  knowledge/ | skills/ | data/ | vision_library/
gui/                                  运行控制窗口
entrypoints/                          多人演出运行入口
config/ | prompts/ | knowledge/ | skills/
docs/                                 当前使用和架构说明
```

主目录不再包含 tools、learning、tests、release、components 或寻路开发入口。src 保留运行实际需要的共用组件和兼容入口，外部开发目录保存完整源码、测试和历史资料。

文字任务的模型接口与多步骤执行，见 [能力接口与计划](docs/CAPABILITY_PLANS.md)。支持接口读取、参数校验、条件步骤、结果引用、预算、状态查询和取消；小游戏仍沿用各自的运行前置条件和验证边界。

## 环境和资产

通用依赖由 pyproject.toml 管理，例如 `python -m pip install -e ".[vision,recording,mcp]"`。本机通用环境为 .conda，跳绳/厨房视觉环境为 .vision。权重、TensorRT引擎、解释器和个人配置未上传 GitHub；新机器需要补齐所用模块的模型及依赖，换 GPU 应重新导出引擎。

当前模型和引擎在 domains/hololive_dreams/models/jump_rope 与 kitchen 内；所有原始实验、标注和录像仍在 Game_agent_dev，源码仓库不替代训练数据备份。

## 后续

钓鱼可使用但较粗糙；跳绳后续评估模型和GPU调度；厨房需继续补数据、训练与调整逻辑；日常状态和完成证据仍待打磨。此次分离不代表这些工作已经完成。原有7项未通过测试仍保留，未进行实机验证。

- [使用说明](docs/USER_GUIDE.md)
- [数据和开发工具位置](docs/WORKSPACE_LAYOUT.md)
- [本次验证](docs/WORKSPACE_VALIDATION.md)
- [通用执行与游戏流程分层](docs/daily-layers.md)
