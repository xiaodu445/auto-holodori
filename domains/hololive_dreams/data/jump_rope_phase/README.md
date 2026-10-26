# 固定旋转轨迹素材

rotation_recipe.json可重复提取已有录像的一圈；rotation_v1.json保存26条参数阶段曲线、窗口归一化坐标、来源帧、训练支持比例、周期、时间戳摘要和闭合误差。verified=false，不是完整真值，也不代表所有技能共享精确投影曲线。

颜色/背景筛选仅用于已知蓝绳的离线建模，实时阶段匹配不按绳色筛选。原录像未移动，保留在runtime/jump-rope/recordings/20261003-135733-386995。生成脚本src/modular_agent/realtime/build_jump_rope_atlas.py；根目录build_jump_rope_phase_atlas.cmd。

新增不同路径应使用新配方和新文件，保留rotation_v1及其报告，不修改A/B路线素材。低空摇摆未提供路径，不能用本文件冒充。详细边界见docs/jump-rope/routes/fixed-phase.md。


2026-10-04新增swing_v1.json（有限0～1坐标、8个约束二次曲线样本，verified=false），生成配方swing_recipe.json、离线构建器build_jump_rope_swing.py。只供独立C3/v3，原rotation_v1.json及C2/v2不变。细节见docs/jump-rope/routes/fixed-phase-state.md。
