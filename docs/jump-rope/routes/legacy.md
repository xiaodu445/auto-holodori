# 留存的基础和示范学习路线

baseline：jump_rope_vision.py/ jump_rope_controller.py。run_jump_rope_judgment.cmd和run_jump_rope_preview_judgment.cmd只判断；run_jump_rope.cmd无参数、run_jump_rope_live.cmd及run_jump_rope_preview.cmd会发送实验空格。保留兼容，不作为目前推荐自动入口。

joint_shape：--shape-vision，run_jump_rope_shape_preview.cmd；早期联合形状/运动筛选方案。不能与local、whole、phase同时启用。

tiny_local：jump_rope_local_motion.py中的LocalMotionVision/Controller，小脚部ROI Hough路线；仍导出并测试，当前--local-motion实际使用TrajectoryMotionVision/Controller，不混淆两者。

人工时机学习：src/modular_agent/realtime/learn_jump_rope.py读取录制和vision-analysis.json，保存imitation-model.json（enabled=false），旧验证帧级F1约0.150，未接实时输入。79次示范按键平均约110ms，游戏长按改变滞空，因此不能用于35ms短按标定。保留数据和训练器以便未来重录短按、改善标签质量后继续。

录制：record_jump_rope.cmd，仅记录游戏客户区画面、单调时间戳及人工空格，不注入按键。视频nominal FPS与实际FPS不同，回放必须配timestamps.json。输入诊断run_jump_rope_test_space.cmd仅发一次35ms，不能证明识别或跳跃时机正确。

历史详细开发记录见../history/before-route-index-jump-rope.md；该文件包含已替代的入口/参数，先以上级路线索引为准。
