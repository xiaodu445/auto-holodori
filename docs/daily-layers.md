# 日常任务与交互逻辑的分层

## 职责边界

通用层负责“怎样执行和确认一步”，游戏领域负责“看到了什么、下一步做什么”。配置仍在 `domains/hololive_dreams/daily_tasks_config.json`，与 `launch.json` 并列，可编排调用多个小游戏。

| 文件 | 职责 |
| --- | --- |
| `src/modular_agent/agent/interaction.py` | `InteractionPolicy`、`RetryBudget`、窗口检查、转换执行循环；接收调用方的状态、源页面、目标和完成判据 |
| `src/modular_agent/agent/ui_actions.py` | 输入前后取消检查、输入结果记录和错误处理、目标中心与窗口边界检查 |
| `src/modular_agent/domains/hololive_dreams/daily_tasks.py` | 游戏日常模板与配置校验、通知列表、派遣、礼物、轮盘、传送恢复，以及各流程的完成证据 |
| `src/modular_agent/domains/hololive_dreams/interaction.py` | 游戏场景策略注册、游戏状态映射、弹窗按钮允许范围和游戏适配入口 |
| `src/modular_agent/domains/hololive_dreams/states.py` | 具体游戏状态分类：自由场景、地图、加载、奖励、对话等 |
| `src/modular_agent/domains/hololive_dreams/daily_plan.py` | 游戏任务选择、依赖与计划 |
| `src/modular_agent/domains/hololive_dreams/claim_tasks.py` | 游戏成就、活动、任务通行证的页面与领取流程 |
| `src/modular_agent/domains/hololive_dreams/daily_journal.py` | 日常运行记录和奖励证据 |
| `src/modular_agent/local_models.py` | 连接CLI/顶层Agent、日常计划与游戏组件；持有运行资源并汇总结果 |

通用执行器不导入 Holodori 模板或状态分类器。领域适配通过 `state_of(report)` 提供五种执行控制状态：`READY`、`UNKNOWN`、`LOADING`、`OVERLAY`、`BLOCKED`。它们描述执行器应如何等待或停止，不代表游戏任务已完成；完成仍由领域传入的 `completed(report)` 及连续帧确认决定。

## 保留的行为

- 源页面与新鲜目标成立且控件可用时才允许预算内重试；输入成功不当作页面完成。
- 加载时等待；奖励/对话等覆盖层优先处理；错误或购买确认停止。出现覆盖层后不补发原动作。
- 实时和被动场景不采用菜单重试，非幂等操作保持最多一次。
- Alt修饰键、空白推进位置、模板阈值、奖励判断和各玩法规则仍由游戏层决定。
- 派遣链、礼物收尾等原有专用预算仍保留在领域流程中，没有为了抽象而改写为新的循环。
- 原 `modular_agent.agent.daily_tasks` 继续导出同一个 `DailyTasks` 类与常量；新代码使用领域路径。原领域 `interaction` 的公共导入也继续可用。

这次分层只调整实现归属与调用关系，未打磨现有任务完成判定，未调整日常配置、重试次数、等待时长或小游戏策略；已有独立发布 EXE 未重建。

## 2026-10-26 验证

新增9项通用执行/兼容测试，使用非游戏页面适配器与模拟输入，覆盖丢输入重试、加载、延迟弹层、置灰控件、取消、发现预算、输入失败、目标边界和旧导入。

相关日常与协议基线为133项，已有1项失败；拆分后更广范围共886项，879项通过，原有5项失败与2项报错保持相同（名单见 `maintenance/models-by-category-2026-10-26.md`），没有新增失败。新增通用测试加既有交互协议测试共31项全部通过。未操作真实游戏，不据此宣称任务可靠性或成功率提高。
