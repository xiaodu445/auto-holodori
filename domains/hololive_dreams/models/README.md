# 小游戏运行组件

| 分类 | 内容 |
| --- | --- |
| fishing/ | 钓鱼识别、控制、状态机和循环 |
| greed_cards/ | 强欲之牌入口及实际玩法 |
| rhythm/ | 音游引擎 rhythm_game.py 与配置 |
| jump_rope/ | 当前主程序 game_jump_live.py、game_jump_logic.py、循环模板及当前07模型；运行依赖和兼容路线保留 |
| kitchen/ | 主程序 kitchen_play.py、当前 best-box 权重与配套引擎；调用 src 内的识别、策略和会话组件 |

日常任务是游戏层编排，配置在上一级 daily_tasks_config.json，与 launch.json 并列。游戏层日常实现位于 src/modular_agent/domains/hololive_dreams/daily_tasks.py。

训练、标注、录像和历史实验在相邻 Game_agent_dev 中。主程序不从训练目录加载，也没有 components 层。当前模型大文件保留本地并被 Git 忽略。详见 ../../../docs/WORKSPACE_LAYOUT.md。
