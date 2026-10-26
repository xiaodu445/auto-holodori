# 跳绳：阶段收尾

当前版本保留，暂不继续开发。阶段1–4使用整圈时间模板，阶段2减速暂未做；阶段5沿用旧路线。实时预览与35毫秒空格已接入。

日常只用三个根目录入口：

| 入口 | 用途 |
|---|---|
| run_jump_rope.cmd | 运行当前版本，实时预览并发送空格 |
| record_jump_rope.cmd | 录制画面、声音和人工输入 |
| open_jump_rope_frame_review.cmd | 查看当前5378帧检阅；加annotations参数打开原录像标注页 |

当前检阅：runtime/jump-rope/frame-review/stage2-phase-handoff-review/index.html。

2004帧错误跳变已修复，人工点误差251.67→5.60像素。阶段2真实加速确认仍偏慢，阶段3–4部分遮挡反馈尚未解决，不代表实机全程成功。

继续开发从[交接文档](HANDOFF.md)开始。标注操作见[标注说明](FRAME_REVIEW_ANNOTATION.md)，模板与原始标注见domains/hololive_dreams/data/jump_rope_template_library/README.md。

历史启动器及离线重建入口集中在tools/jump_rope/legacy_launchers。旧说明集中在history，具体试验记录在reports；根目录其它游戏入口未改。

本次整理详见[收尾整理报告](reports/final-cleanup-20261006.md)。历史重复图片删除被自动审批阻止，尚未释放对应空间。
