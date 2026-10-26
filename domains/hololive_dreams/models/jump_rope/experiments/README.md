# C4 独立离线试验

2026-10-04。此目录用于保留不同思路，不是新默认路线。正式C4仍加载上一级 `jump_rope_phase_gear.py` 和 `jump_rope_phase_gear_config.json`，没有导入本试验视觉工厂；A/C3保持原入口。

## 文件与输出

- `jump_rope_phase_gear_evidence.py`：独立视觉工厂，包含连续偏移、脊线、相对运动、阶段证据、校正能量及几何边缘位移开关；全部关闭时与基线同样识别。离线中性兼容性验证在 `runtime/jump-rope/phase-gear/experiments/neutral-compatibility.json`。
- `jump_rope_gear_cases.json`：各case的参数覆盖；基准参数引用已冻结的 `gear-v4-before-coherent-evidence` 快照。不是当前默认配置的动态副本。
- 共用纯数学试验模块：`src/modular_agent/realtime/curve_evidence.py`、`phase_evidence.py`、`endpoint_trajectory_bank.py`。Endpoint类为失败连接点试验，不由正式领域实现加载。
- 运行器 `validate_jump_rope_gear_experiments.py` 只离线回放；每个case输出到 `runtime/jump-rope/phase-gear/experiments/<case>/`，不覆盖正式report/replay/video。
- 后续运行保存实际完整参数和源码散列；comparison汇总全部目录、使用当前人工标签重新统计。早期一次性试验缺完整参数/源码散列，汇总字段会注明，不把它们当作完整复现结果。

## 主要路线

|实验|目的|结论|
|---|---|---|
|baseline|片段锁后的单低空档|保留快照|
|occlusion-rearm|播放一圈且有上半圈实际行程后解锁重入|有收益，正式C4已保留此保护|
|frozen-branches系列|不修正未确认模型；减慢/停用速率修正|有阶段明显恶化，关闭|
|多低空档、innovation系列|使用三个实测周期，惩罚阶段回正量|位置局部变好但状态更差，关闭|
|rateproof系列|从连续阶段估速度、增加速度先验|测量仍有模型偏置，未改善|
|endpoints系列|按方向限制低空入/出连接点，限制技能最短周期|漏掉首次技能，后续方向锁错，关闭|
|edge-motion系列|使用历史Canny边缘的真实位移替代亮度帧差|漏掉缓慢小运动或改变竞争，整体更差，关闭|

前三个实测低空周期2.399/2.005/1.710秒只证明录像中存在速度差异；默认启用全部档位会恶化。首段时序变换是否能适用于快档仍未确认。

## 运行

项目根目录设置 `PYTHONPATH=src`、`PYTHONUTF8=1`。例如：

```powershell
.conda\python.exe -m modular_agent.realtime.validate_jump_rope_gear_experiments --case baseline --case occlusion-rearm
```

每个case约4010帧，耗时不是实时性能。视觉耗时不含采集/预览/输入。此工具不请求游戏窗口、不发送空格。不要因为某张图误差降低就替换默认路线；应同时比较状态、接缝、遮挡及其他阶段。

完整分析见 [长时记录](../../../../../docs/jump-rope/reports/c4-long-run-20261004.md)；用户入口见 [C4说明](../../../../../docs/jump-rope/routes/trajectory-gears.md)。
