# 跳绳阶段交接（2026-10-06）

用户接受stage2-phase-handoff-review这一版，暂停跳绳开发，保留当前代码与配置。

## 当前基线

- 默认启动：run_jump_rope.cmd；配置domains/hololive_dreams/models/jump_rope/jump_rope_timed_playback_config.json。
- 主实现：src/modular_agent/realtime/timed_cycle_vision.py、timed_rope_playback.py。
- 35个时间候选覆盖20种状态，阶段1仅正摇正常；阶段2减速暂不做；阶段5旧路线。
- 以显示预测驱动空格，不增加落地识别门槛。小偏差微调，大偏差独立确认后纠错。
- 阶段2具体候选独立确认，累计相位漂移重置确认；大弧线跳变需连续强证据，过期声音不再缩短确认。阶段3–4保留原规则。

## 证据与未完成项

最新检阅runtime/jump-rope/frame-review/stage2-phase-handoff-review/index.html，5378帧，replay SHA256 c4deb508086b5e3bb3b07eac4c592296ac3ae6ced759c6f13187bca7a7eda6f8。2004帧误差251.67→5.60像素；最终17项相关测试通过，页面交互验证通过；此次未发送真实空格。

阶段2真实加速确认偏慢：2078–2201标注区间前39帧仍正常档，匹配率68.5%。3558、4315、4563及5148–5157的其他8帧反馈未修复。严格规则扩展全阶段曾导致后段退化，未采用。不要把同录像评估当成独立泛化或实机通关。

原录像runtime/jump-rope/recordings/全部保留；人工标注和模板在domains/hololive_dreams/data/jump_rope_template_library/。当前页依赖recording-20261006-115004-094950/exact-frames；旧录像页依赖timed-mainline-current/raw-frames，不能随便删。历史回放JSON、声音事件、原始配置和报告仍保留。

## 整理状态

根目录只保留运行、录制、检阅三个跳绳入口，另5个入口归档；旧README/HANDOFF快照在history/before-final-cleanup-*。30组历史重复帧目录约16.37GiB待删除，具体清单runtime/jump-rope/cleanup-delete-plan.json；自动审批已拒绝永久删除，用户确认该清单前不能执行。不要将本次收尾记为已释放空间。

进一步细节：reports/stage2-phase-handoff-20261006.md、reports/playback-feedback-nine-frames-20261006.md、reports/final-cleanup-20261006.md。

恢复开发请求可直接写：读取docs/jump-rope/HANDOFF.md，保留当前接受基线，先优化阶段2真实加速确认延迟，再处理剩余遮挡反馈，生成逐帧检阅，未经要求不要重写全阶段规则。
