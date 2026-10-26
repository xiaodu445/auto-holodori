# 阶段收尾整理（2026-10-06）

用户接受当前版本，暂停开发。本轮未修改识别、决策或输入算法。

根目录跳绳入口8→3，保留run_jump_rope.cmd、record_jump_rope.cmd、open_jump_rope_frame_review.cmd。其它5个收进tools/jump_rope/legacy_launchers，修正相对定位与路线注册表，归档校验清单manifest-final-cleanup.json。旧菜单和离线重建仍可从历史目录调用。

README/HANDOFF重写为当前基线及未完成项，追加式旧文档保存到history/before-final-cleanup-*。原录像、人工标注、模板、当前检阅和历史报告保留。

计划删除30组历史回放frames图片目录，共173086张、16.37GiB；保留所有回放JSON和音频事件，以及当前页原始帧、旧录像共享原始帧和audio-prefix-confirm基线。清单见runtime/jump-rope/cleanup-delete-plan.json。自动审批以尚未确认具体范围、可能影响追溯为由拒绝永久删除。实际未删除这些图片，释放空间为0；清单等待用户明确确认。

当前入口及路线注册表目标静态检查通过，未启动游戏。历史页面若以后删除对应图片将无法直接显示叠加截图，但原录像和回放数据仍可重建。
