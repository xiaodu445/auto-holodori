# 强欲之牌入口模块 1.1.0

结构已于1.2.0重组：实现位于src/modular_agent/domains/hololive_dreams，原路径为兼容入口。共享状态与运行记录规范见 [领域结构说明](hololive-domain-structure.md)。OCR触发已由两轮未知更新为持续未知满5秒，仍最多每5秒一次。

入口：domains/hololive_dreams/models/greed_cards/greed_cards_entry.py，load_greed_cards(root)加载；run(observe, computer, progress, timeout=300, transition_timeout=30, should_yield=...)运行。已有local-run和每日调度继续复用，无云模型，不下注。

成功：outcome=success、verified=true、module=greed_cards_entry、next_module=greed_cards_play，证据为实际High & Low页面，不自动调用下个模块。失败或未知保留当前位置并释放输入；调用方根据当前画面决定恢复步骤。

支持从自由场景、三张地图中可见的电玩切换入口、目标详情、传送、猜高低现场交互和明确Shiori对话接续。地图标题无需map1/map2同时命中；地图拖到左侧仍可选候选，但只有强欲之牌详情确认后才移动。错误详情Esc返回，不误传送。

明确识别游戏区及大厅标签时回大厅寻找time操纵杆模板；操纵杆详情移动，现场E，按当前选项切换为赌场区或不更改，返回地图。所有鼠标选择使用Alt，W保留0.3秒短按和原两次预算。

未知过渡按时间等待（默认30秒，整体300秒），不再两帧未知即退出。只在明确Shiori对话时E推进，交互后的普通HUD等待实际游戏，防止重新开对话。输入前检查窗口前台、最小化、遮挡及目标范围；停止/人工引导释放输入。

## 分阶段模板优先观察

入口调用（独立入口、每日串联、Agent交接）已使用EntryObserver：默认关闭OCR、UIA、形状按钮搜索，原尺寸模板匹配。地图阶段匹配地图标题、区域、详情和地图设施；传送/现场阶段匹配交互、对话、操纵杆选项和准备页；初始阶段查全部入口模板。通用HUD模板作为辅助，遮挡层优先。

新增15个专用模板从已归档截图裁剪，源和元数据在data/template_sources/in_game/entry；tools/build_entry_templates.py可重建并导入。语义文本source=template，坐标来自本次匹配，不缓存旧OCR位置。准备页须同时命中High & Low标识和押注开始按钮，不点击该按钮。

连续两轮模板无法支持决策时OCR复核，最多每5秒一次，UIA仍关闭。当前兜底为游戏窗口OCR，并非局部OCR。启动树及顶层交接前观察仍保留原策略；本次只优化入口循环。实际耗时需实机日志测量。

限制：地图只有配色/布局而无游戏区文字时，暂不能自动判区；新模板来自原尺寸参考截图，UI缩放/字体变化时可能转OCR。操纵杆time模板、动画及真实按键响应需实机确认。未知画面不会学习为可点击状态。当前不处理任意菜单/通知覆盖层。不得把参考图自匹配当泛化或实机成功。

验证：test_greed_cards_tree 8项、test_greed_entry_transitions 5项、test_local_model_handoff 7项通过（2026-10-17）。

追加验证：入口、过渡、观察器及入口/玩法交接共31项测试通过，包含参考截图匹配、OCR限频；Python编译检查通过。
