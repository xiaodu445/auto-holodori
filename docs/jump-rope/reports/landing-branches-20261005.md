# 落地分支改进（2026-10-05）

用户实机反馈：遮挡期间突然加速时，小幅回正无法追赶。目标改为在预测落地时并行播放各个合法速度，使用随后图像选择，而非把所有变化挤进一个速度估计。

## 根因和实现

旧prune按模式/档位合并新旧候选；同档的新落地分支可能当场被旧高分轨迹删除。choose即使选中快档，仍将阶段限制回旧阶段附近，最多0.008周期，使遮挡中应积累的阶段差被抹掉。

新 LandingTrajectoryBank 以落地批次隔离候选，补齐当前名义档，每个速度从同一边界开始，按跨越时刻计算余下帧时间。未确认圆周分支冻结校正，活动轨迹按旧方式小幅回正。证据比较使用相同时间帧的窗口平均；单帧高分不足以接管。接管采用分支已播放阶段。一次确认清除本批和更早分支，下一次换档必须经过新落地。

总数24、候选寿命0.9秒；只能已确认状态生成后继，低空进入方向冻结、退出相反一次、失焦/F12释放输入保护均保留。此策略无法在完全遮挡中确定真实变化，只保留可能性并等待视觉支持。

## 对照与限制

- 旧基线：1289/4010接受观测，8次切换，11/11稀疏状态点；32/55秒几何31.26/37.16px。
- 新正式默认：1345/4010接受观测，8次切换，16次圆周分支接管；32/55秒6.98/0.81px。14/20秒6.14/5.67px。10/11状态点，75.5秒迟入低空，75.567秒才进入。
- 不清除旧落地分支时，先切快档再被旧慢档拉回，发生反复换档；加入一次性确认后改善。
- 全状态独立分支和三个低空档实验严重恶化，不启用。加强视觉门槛也损失真实候选，未采纳。

当前只启用圆周换档的独立分支，左右摇状态后继仍用原规则。这是可用的阶段性改进，未证明实机技能段零失误。低空档选择、遮挡超过候选寿命、假背景连续支持仍是限制。允许确认分支纠偏意味着曲线可出现较大的接管位移；它不是每帧任意加大校正。

431测试通过。约10.90ms平均、13.91ms P95仅CV；未计采集/预览。无非正时钟、档位越界、整圈直接翻转或错误低空退出；2126纯播放帧与时间推进一致。

## 文件和复现

- 纯数学新分支：src/modular_agent/realtime/landing_trajectory_bank.py。原 TrajectoryBank 保留，只增加可覆盖的阶段兼容判断。
- 领域工厂：domains/hololive_dreams/models/jump_rope/jump_rope_phase_gear.py，按 landing_branches 选择。
- 当前/基线参数分别为 jump_rope_phase_gear_config.json 与 jump_rope_phase_gear_baseline_config.json。
- 修改前快照：docs/jump-rope/history/gear-v4-before-landing-branches/。
- 新版G入口不变；旧版对照 run_jump_rope_phase_gear_baseline_judgment.cmd。全部仅判断，不发空格。
- 试验输出 runtime/jump-rope/landing-branches/<case>/。早期试验只保存源码散列，后续运行复制源码到各case的sources目录。参数加载冻结的本轮前基线，不受当前默认配置变化影响。
- 正式report/replay/annotated/constraint-report/final-manifest在 runtime/jump-rope/phase-gear/。

设置PYTHONPATH=src、PYTHONUTF8=1：

```text
.conda\python.exe -m modular_agent.realtime.validate_jump_rope_landing_branches --case baseline --case rotation-once
.conda\python.exe -m modular_agent.realtime.validate_jump_rope_phase --gear
.conda\python.exe -m modular_agent.realtime.validate_jump_rope_gear_constraints
```

实验runner参数名single/all-once代表全状态分支，rotation-once代表圆周换档分支；历史试验对应各自保存的parameters与源码版本，不能拿今天的实现等同于所有历史输出。
