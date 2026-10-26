# 跳绳开发路线索引

更新：2026-10-04。这里描述当前有效状态；旧的逐次开发说明完整保存在 [历史记录](before-route-index-jump-rope.md)。历史里有被后续版本替代的参数和入口，不作为当前运行指令。

## 先选入口

| 目的 | 入口 | 是否发送空格 |
|---|---|---|
| 当前已由用户确认普通场景可用的自动跳跃 | `run_jump_rope_local_motion.cmd` | 是，35ms实验短按 |
| 查看当前自动路线的识别和决策 | `run_jump_rope_local_motion_judgment.cmd` | 否 |
| 查看整绳 v2 自由曲线/连续性 | `run_jump_rope_whole_judgment.cmd` | 否 |
| 对照受限形状 v3 | `run_jump_rope_whole_shape_judgment.cmd` | 否 |
| 新固定轨迹＋阶段跟踪 | `run_jump_rope_phase_judgment.cmd` | 否 |
| 新增反向版本，显示有符号速度和方向 | `run_jump_rope_phase_reverse_judgment.cmd` | 否 |
| 新增三状态 v3，限制合法运动 | `run_jump_rope_phase_state_judgment.cmd` | 否 |
| 轨迹＋速度挡位 v4（落地分支） | `run_jump_rope_phase_gear_judgment.cmd` | 否 |
| 用现有录像验证新路线 | `run_jump_rope_phase_replay.cmd` | 否 |
| 重建固定轨迹素材 | `build_jump_rope_phase_atlas.cmd` | 否，离线 |
| 录制画面和人工空格 | `record_jump_rope.cmd` | 否，仅记录 |

可从 `run_jump_rope_routes.cmd` 菜单选择，按0启动反向v2、按S启动三状态v3、按G启动挡位v4。旧入口都保留；**`run_jump_rope.cmd` 无参数会发送实验空格**，不是推荐的纯观察入口。Python CLI 无参数仍只判断。不要同时运行两个实时路线；F12、Ctrl+C、失焦停止并释放输入。

## 路线和成熟度

| 路线 ID | 思路 | 当前结论 | 后续入口文档 |
|---|---|---|---|
| A / local_motion_v6 | 局部曲线、颜色/运动片段、方向与到脚预测 | 用户确认简单跳绳稳定；低空/技能仍需验证 | [局部自动](../routes/local-motion.md) |
| B / whole_curve_v2 | 两端先验＋自由参数曲线＋光流连续性 | 诊断；复杂背景会误认/失去跟踪 | [整绳直接拟合](../routes/whole-curves.md) |
| B2 / whole_shape_v3 | 少参数绳形＋灰度细条＋静止位置过滤 | 672/4010接受拟合，未整体超过v2，默认关闭 | [整绳直接拟合](../routes/whole-curves.md) |
| C / fixed_phase_v1 | 录像中的固定轨迹库，只跟踪阶段和速度 | 新独立实验；仅普通旋转模板，禁止输入 | [固定轨迹](../routes/fixed-phase.md) |
| C2 / fixed_phase_signed_v2 | 同一固定轨迹＋带符号速度＋连续多帧确认反转 | 独立只判断实验；C/v1仍保留 | [反向版本](../routes/fixed-phase-reverse.md) |
| C3 / fixed_phase_state_v3 | 正摇、反摇、有限低空路径与停滞恢复 | 独立只判断；C2/v2仍为基线 | [三状态约束](../routes/fixed-phase-state.md) |
| C4 / trajectory_gear_v4 | 固定轨迹播放、正值速度挡位、小幅校正与边界分支竞争 | 只判断；片段锁、遮挡重入已修，三周期独立采样，复杂曲线仍失配 | [轨迹与挡位](../routes/trajectory-gears.md) |
| L / imitation_trial | 人工输入时机特征学习 | 验证F1低，未接实时控制；原录制长按不适合35ms标定 | [保留实验](../routes/legacy.md) |
| R / baseline、joint_shape、tiny_local | 早期识别和对照方案 | 保留代码/入口，非当前推荐自动路线 | [保留实验](../routes/legacy.md) |

有效帧数是接受观测数，不是准确率/成功率。预测曲线存在也不等于有当前视觉支持。所有路线均未自动验证999计数或零生命损失，最终结果仍可能unknown；画面消失不当成功。

## 开发时从哪里读

1. 本索引，再读所选路线文档和参数文件。机器可读映射在 `domains/hololive_dreams/models/jump_rope_routes.json`。
2. 共用实时框架在 `src/modular_agent/realtime/`：采集、单调时间、最新帧、输入锁存、预览、录制、回放；固定轨迹数学组件独立在 `phase_tracking.py`。
3. 领域识别/控制在 `domains/hololive_dreams/models/`；稳定A路线当前仍由 `jump_rope.py` 中的TrajectoryMotionVision/Controller组合，不为目录整齐而挪动行为代码。
4. 数据与验证：原录像和时间戳在 `runtime/jump-rope/recordings/20261003-135733-386995/`；固定轨迹及生成配方在 `domains/hololive_dreams/data/jump_rope_phase/`；新路线输出隔离到 `runtime/jump-rope/phase/`。

修改一种路线时只启用它自己的标志/参数。先离线回放，再只判断预览，再考虑输入。新路线不覆盖旧路线或校准值；实机输入需要有明确危险阶段、离地延迟和落地状态证据，不能把一次采样录像的周期写成固定按键间隔。

## 留存与回退

没有删除识别器、控制器、录像或旧启动器；顶层默认full观察、高低牌和钓鱼接口保持。切回A只运行它的原入口即可，不需要撤销C的代码。B/v2、B2/v3对照文件各自保留；新回放不会覆盖它们。旧文章中已过期的80ms测试空格等说明只在历史中保留，现行短按为35ms。

2026-10-04 长时对照：C4保留单档，失败的多档/连接点/连续证据方案隔离保存；421测试通过，11个稀疏状态点吻合，几何仍未超过C3。见 [分析记录](../reports/c4-long-run-20261004.md)。

2026-10-05：G启用圆周落地分支接管，旧版对照入口为 `run_jump_rope_phase_gear_baseline_judgment.cmd`。左右摇多档未启用；见 [改进及限制](../reports/landing-branches-20261005.md)。

阶段原型入口：`run_jump_rope_stage_judgment.cmd`，五级各四行为，仍只判断，速度先验未全部校准、暂未超过G；见 [阶段模板说明](../routes/stage-templates.md)。


2026-10-05 逐帧审阅：新增低空进入边界/已播放周期修正与平滑模板独立入口run_jump_rope_gear_review_judgment.cmd、run_jump_rope_stage_review_judgment.cmd，均只判断。原G保留；阶段原型改善但未胜过G。逐帧网页runtime/jump-rope/frame-review/index.html，支持人工标注导出。详见docs/jump-rope/routes/frame-review.md。


2026-10-05 五处人工标注：1978仅标记加速、不作方向真值。独立只判断入口 `run_jump_rope_human_calibration_judgment.cmd`；逐帧页 `runtime/jump-rope/frame-review/human-calibration-clean-bank/index.html`。843/2279低空偏差改善，1978加速仍退步，不替换原G或A。详见 [校准报告](../reports/human-calibration-20261005.md)。


2026-10-05 三处标注跟进：独立入口 `run_jump_rope_clock_exit_judgment.cmd`，仍只判断；新逐帧页 `runtime/jump-rope/frame-review/clock-exit-reverse-cohort/index.html`。反摇退出多档竞争与重复帧证据窗口改善1115/2484附近；1869加速仍未修好，55秒位置退步，不替换原G。见 [分析与限制](../reports/clock-exit-20261005.md)。


2026-10-05 低空退出方向规则：从后往前才接反摇，从前往后才接正摇，且退出必与进入前反向。独立只判断入口 `run_jump_rope_directional_exit_judgment.cmd`；逐帧页 `runtime/jump-rope/frame-review/directional-exit/index.html`。902错误候选消除，959生成合法候选，1087确认反摇；加速1869仍未解决。见 [规则、接点与回放证据](../reports/directional-exit-20261005.md)。


2026-10-05 阶段速度库独立实验：模板改为“阶段 X → 正常 / 加速 / 减速”，正反摇分别保存时间曲线，未实测部分标待校准。入口 `run_jump_rope_stage_clock_library_judgment.cmd` 只判断；审阅页 `runtime/jump-rope/frame-review/stage-clock-library-review/index.html` 明确区分活动模板与候选。加速选择仍有错误，不替换 A/G。分析见 `docs/jump-rope/reports/stage-clock-library-20261005.md`。


2026-10-05 阶段二正常/加速反摇独立拟合：扣固定背景支持，正常.750、加速.910；新只判断入口 run_jump_rope_stage_clock_v2_judgment.cmd。仍实验，旧路线保留，见 docs/jump-rope/reports/stage-clock-v2-20261005.md。


2026-10-05 计数/速度阶段共存独立实验：run_jump_rope_stage_coexist_judgment.cmd只判断；计数升级只增候选，旧时钟继续，由连续证据接管。详见docs/jump-rope/reports/stage-coexist-20261005.md，原入口保留。


2026-10-05 连续证据圆周速度纠错独立试验：run_jump_rope_temporal_recovery_judgment.cmd只判断，保留候选时钟，接管清旧阶段；不改变低空规则。详见docs/jump-rope/reports/temporal-recovery-20261005.md。


2026-10-05 前后半圈速度切换独立入口run_jump_rope_half_cycle_judgment.cmd只判断；前半圈收紧、后半圈连续证据纠错，详见docs/jump-rope/reports/half-cycle-20261005.md。


2026-10-05 采集程序加扬声器回环音频：record_jump_rope.cmd默认5分钟，F12停止；保存audio.wav及audio-timestamps.jsonl，与画面/空格共用单调原点。先录10秒检查样本/峰值/错误；关闭其他声音。详见docs/jump-rope/routes/audio-recording.md。本轮不改分支或轨迹模板。
