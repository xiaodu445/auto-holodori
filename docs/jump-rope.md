# 跳绳组件

当前说明已整理到 [开发路线索引](jump-rope/README.md)。从这里选择运行入口、查看路线状态和继续开发。

- [A：现有局部自动跳跃](jump-rope/routes/local-motion.md)
- [B / B2：整绳直接拟合与受限形状实验](jump-rope/routes/whole-curves.md)
- [C：固定轨迹＋阶段跟踪](jump-rope/routes/fixed-phase.md)
- [早期基础与人工示范学习](jump-rope/routes/legacy.md)
- [整理前的完整开发记录](jump-rope/history/before-route-index-jump-rope.md)

稳定入口和既有代码均保留，新路线通过独立标志、参数、轨迹素材及输出目录运行。run_jump_rope_local_motion.cmd是真实实验输入；新C路线只判断。F12/Ctrl+C停止，失焦和异常释放输入。没有自动验证999或零生命损失，不把画面消失判为成功。
