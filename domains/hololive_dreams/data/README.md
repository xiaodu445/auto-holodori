# Domain Data

本地训练与评估数据。只保存经授权并脱敏的数据；大文件默认不加入版本控制。

## 跳绳素材

jump_rope_samples保留截图、姿势参考和稀疏核对点。新增jump_rope_phase保存普通旋转轨迹及可重复生成配方，来自已有录像一个周期，verified=false；见[固定轨迹说明](../../../docs/jump-rope/routes/fixed-phase.md)。原录像/时间戳/人工空格不搬动，在runtime/jump-rope/recordings下。
