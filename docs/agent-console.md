# 顶层 Agent 与本地组件调用

2026-10-02：已连接真实游戏启动和强欲之牌入口，用户确认链式调用成功。游戏内策略不是训练模型，采用本地决策树；联网大模型仍负责目标理解和未知状态处理。

## 运行

start_agent.cmd 打开真实操作与日志窗口。CLI：设置 PYTHONPATH=src，运行 `.conda/python.exe -m modular_agent chat --domain hololive_dreams --live --log-window`。不带--live仅模拟；run --goal "..."为单次任务。

## 调用边界

先 observe 当前屏幕，不用历史窗口句柄。游戏不存在选择 use_skill/launch_game，Steam与本地启动树串行到自由主界面。当前观察存在、句柄、游戏运行状态由 current_observation 给出。

强欲之牌树需要 local_model_conditions.eligible=true：游戏前台且无遮挡，目标相关，画面是树支持的状态。大模型选择 use_skill/greed_cards_entry，交接前重新观察复核。未知、错误详情或时间条件未满足，不接管。成功完成进入类目标；游玩/获胜目标需要继续处理。本任务不反复调用同一入口树。

本地期间大模型不同时发送输入，人工引导可在观察边界中断；F12或stop后不再请求大模型。组件未知或失败将反馈原因供顶层重新规划。完整本地状态和模型决策记录在 runtime/memory/task_sessions。

## 交互

/guide 指示或任务中直接输入文字；/status；/stop；/logs on/off；/models；/model 配置名；/observe [full/icons]；/windows；/quit。命令名不区分大小写。Windows交互输入行在日志刷新后重绘，保留键入内容；浮动窗口只读。

## 识别与恢复

任务每次完整full识别，不因模板命中跳过OCR。控制台打印文字、图标位置、操作和简短结果；完整信息在报告和任务记录。cv_shape未确认时不能当作按钮；已知导航目标可用本次OCR文字位置。focus拒绝历史句柄，smallgame点击须有本次匹配依据。格式错误有限纠正，连续三次失败结束；API重试见 docs/models.md。

专项只读主动搜索接口可选OCR/UIA/CV/模板、指定ROI和目标，见 docs/general-vision.md。现有full调用不自动改变。模型不是直接看图，不能把知识外观描述当当前检测结果。

## 独立本地入口

run_game_startup.cmd / local-start --domain hololive_dreams --live 到自由主界面；run_greed_cards_entry.cmd / local-run --domain hololive_dreams --live 到High&Low，不下注。领域组件见 domains/hololive_dreams/models/README.md；顶层启动经验见 knowledge/global/hololive_dreams_startup.md。

按目录知识检索已接入：先列目录/标题，再按领域、目录或文件分页读取；历史日志默认排除。Skill只发当前领域调用元数据。详见 [知识与技能上下文说明](knowledge-routing.md)。
