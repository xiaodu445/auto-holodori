# 阶段5独立策略原型（2026-10-06）

用户认可阶段5之前的识别，确认阶段5是最高难度，只有固定三个速度档位，不再升级。已保存到领域规则。新增TerminalStageBank和jump_rope_terminal_stage_config.json；现有mainline-review及其默认入口保留。

## 实现边界

阶段5之前仍执行EvidenceRecoveryBank现有策略。计数/徽章确认最高阶段时只提出终局目标，当前技能的旧速度继续；真正接管阶段5速度后锁定终局，不再跨阶段搜索。这里固定的是减速、正常、加速三个候选角色，正摇、反摇、左右摇是独立合法模式；低空使用自身时间曲线。

锁定后按档位保留最新边界候选、一个历史时钟与必要的当前活动项，全部候选仍受有限容量与模式片段约束。速度提交保留其他档位时钟；已确认模式切换仍清理旧片段，避免旧方向回来。遮挡期间时钟继续推进；0.8秒记录窗口内只比较至少一方可见的同帧证据，双方完全遮挡不提供速度优势。明确支持要求局部可见、足够支撑点、视觉质量≥0.55和运动支持≥0.08；至少8个支持帧、均值≥0.55、对当前优势>0.025及对竞争档位差≥0.015。声音只缩短观察跨度0.30→0.18秒，不强制选档。

阶段5减速模板仍pending_calibration，遵守原uncalibrated_decelerate_diagnostic_only约束，只保留诊断候选，不将未标定值当作确认速度。正常1.4325和加速1.45相近，具体数值尚未重新标定。结构约束不能替代速度/正反摇曲线标定。

## 完整回放与限制

阶段5独立候选：runtime/jump-rope/frame-review/terminal-stage-review/index.html，7529帧一帧一图。实际接管为原始帧5357，92.448秒；这是视觉运行结果，代码没有按帧号或录像时间调度。前5358帧的整绳曲线、活动模板、控制判断与上一版mainline-review逐项完全相同。

| 帧 | 原策略模板/模式 | 独立候选模板/模式 | 候选本帧支持 |
|---|---|---|---|
| 5164 | stage_4/normal / rotation_reverse | stage_4/normal / rotation_reverse | False |
| 5231 | stage_4/accelerate / rotation_reverse | stage_4/accelerate / rotation_reverse | True |
| 5293 | stage_4/normal / rotation_reverse | stage_4/normal / rotation_reverse | False |
| 5357 | stage_5/accelerate / rotation_reverse | stage_5/accelerate / rotation_reverse | True |
| 5758 | stage_5/accelerate / rotation_reverse | stage_5/accelerate / rotation_reverse | False |
| 5829 | stage_5/low_swing / low_swing | stage_5/low_swing / low_swing | False |
| 5940 | stage_5/accelerate / rotation_forward | stage_5/low_swing / low_swing | True |
| 6500 | stage_5/accelerate / rotation_forward | stage_5/accelerate / rotation_forward | True |
| 7000 | stage_5/accelerate / rotation_forward | stage_5/accelerate / rotation_forward | True |
| 7528 | stage_5/accelerate / rotation_reverse | stage_5/normal / rotation_reverse | False |

后段尚未整体改善：5758仍选加速且无当前视觉支持；5829低空进入比原策略迟，5940仍低空而原策略已退出。此版是独立策略结构原型，不提升为默认主线，不宣称阶段5已修好。需要先标定三个实际圆周速度和正反摇时间曲线，再检查声画技能转换，不能仅靠保留候选/加长窗口。

## 验证与复现

全套539项unittest通过，包含10项新增终局策略测试：旧技能过渡、最高阶段锁定、全遮挡禁止切速、跨遮挡共同可见证据、竞争歧义拒绝、三个角色保留、未标定减速不接管、提交保存候选、重置等。日志runtime/jump-rope/terminal-stage-tests.log。

复现使用现有脚本：.conda/python.exe tools/jump_rope/replay_audio_review.py --settings domains/hololive_dreams/models/jump_rope/jump_rope_terminal_stage_config.json --output runtime/jump-rope/frame-review/terminal-stage-review。设置PYTHONPATH=src、PYTHONUTF8=1；可显式使用历史audio-events.json缓存。没有新增根目录cmd，没有实时输入。

下一步按用户认可范围，冻结阶段5之前策略，只针对阶段5标定与策略迭代；接管时的旧技能过渡需要保留，不把计数70当作强制速度切换时刻。
