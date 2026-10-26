# 使用说明

根目录只保留日常运行入口，列表见 ../README.md。启动器从自身位置解析项目路径，使用本机 .conda 或 .vision 环境。

- 日常：run_daily_tasks.cmd；edit_daily_tasks_config.cmd 编辑 domains/hololive_dreams/daily_tasks_config.json。
- 跳绳：run_jump_rope.cmd；F8开始/暂停、F9重置、F12退出。
- 厨房：kitchen_control.cmd 为原控制窗口；kitchen_play.cmd 为命令行。回放按钮调用外部开发目录中的回放工具。
- 音游：run_rhythm.cmd 保留默认参数，run_rhythm_live.cmd 显式实际输入；多人循环为 run_multi_live.cmd，GUI 为 run_hololive_dreams_gui.cmd。
- 钓鱼、强欲之牌和游戏启动入口保留原用途与参数。

寻路仍在开发，请使用 ../Game_agent_dev/navigation_editor.cmd。建图、标注、采样、训练和诊断的原同名cmd都在开发目录，原录像、标注和地图也在那里。见 WORKSPACE_LAYOUT.md。

本次未调整算法、阈值、热键或完成判据。个人模型配置仍由 config/model.json、models.json 及原凭据机制管理，不进入 Git。新运行日志在 runtime，历史资料外移并非删除。
