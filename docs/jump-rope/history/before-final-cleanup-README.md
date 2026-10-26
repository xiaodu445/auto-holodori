## 最新：阶段2换档相位跳变修复（2026-10-06）

默认检阅页：runtime/jump-rope/frame-review/stage2-phase-handoff-review/index.html（5378帧）。2004帧人工点误差251.67→5.60像素；具体候选独立确认，圆周换档大跳变需连续强证据，过期声音不再缩短确认。阶段3–4保留原确认规则。17项相关测试通过，未发送真实空格。

阶段2真实加速确认有所延迟，其他8帧反馈尚未解决；详见reports/stage2-phase-handoff-20261006.md。以下旧页面与测试数为历史记录，以本节为当前入口。

## 最新：绳子得分与可见段标注（2026-10-06）

默认检阅入口改为 runtime/jump-rope/frame-review/rope-score-annotation-review/index.html。每帧显示模型匹配分数和独立外观检查分数，可点选可见绳段、标记遮挡、隐藏预测、跳至低分/分数冲突帧并导出schema2反馈JSON。操作：FRAME_REVIEW_ANNOTATION.md；报告：reports/rope-appearance-score-annotation-20261006.md。

自动时间候选已重新提取：35个候选、254个原始观测帧。严格外观强制选择试验发生反摇漏检，因此默认仅用外观分数作对照，不拦截输入；不要将该试验宣称为全状态修复。615项全套测试通过，诊断接入后复验29项选择/输入测试。下文旧267帧与旧页为历史记录，原反馈及原标注保持独立。

## 当前主线：阶段1–4整圈模板（2026-10-06）

默认 run_jump_rope.cmd 已接入整圈时间模板、实时预览和35毫秒空格。35个候选覆盖20种状态；阶段2减速暂不做，阶段5沿用旧路线。611项测试通过。仍有切换延迟和未实测状态，未验证实机自动成功。

新录像逐帧检阅：runtime/jump-rope/frame-review/timed-recording-current/index.html（5378帧）；旧独立录像：runtime/jump-rope/frame-review/timed-mainline-current/index.html（5082帧）。报告：reports/stages-1-4-timed-mainline-20261006.md。下文为历史记录，若与本节冲突以本节和实际默认配置为准。原标注页保留，打开入口加 annotations 可访问。

新录像人工标注页：runtime/jump-rope/frame-review/recording-20261006-115004-094950/index.html（10245帧，I/O区间、阶段/技能/方向、可见绳点、导出JSON）。open_jump_rope_frame_review.cmd当前默认打开此页。

统一模板库已整理：domains/hololive_dreams/data/jump_rope_template_library/README.md。固定形态、阶段技能样本、生成数据、转换片段分别管理；原录像只保存一份，现有运行配置仍使用原文件。

用户确认（2026-10-06）：0–9圈只有固定正摇正常档，无反摇、加速、减速或低空技能。补录仅需阶段1正摇正常档；旧模板中其他阶段1分支是历史模型占位，不能作为游戏状态依据。详见RECORDING_CHECKLIST.md。

## 2026-10-06 最新：可见绳段微调与大幅纠错分开

主线采用jump_rope_visible_fit_config.json。可信画面的小偏差只做有上限的gentle修正；大偏差先积累独立窗口，再做recovery纠错。持续可信的观测速率优先于旧速度模板与音频；档位不明确时保留标签并记录gear_confirmed=false。30圈切换规则保留。590项测试通过，完整7529帧逐帧页面：runtime/jump-rope/frame-review/visible-priority-review/index.html。1405/2752低空、3244减速保持；3563标签与旧版不同，仍需复核，不能称全程已解决。详见reports/visible-priority-dual-path-20261006.md。

## 2026-10-06 最新：30圈直接换挡

主线在本地计数稳定确认达到30后直接切换阶段3速度模板，保留方向与技能，不等待阶段候选比较。577项测试通过；7529帧回放在2691帧读数30触发一次。最新逐帧页面：runtime/jump-rope/frame-review/count30-review/index.html。详见reports/count30-forced-shift-20261006.md。

# 跳绳当前开发入口

更新：2026-10-06。后续主线为 **轨迹模板库＋整绳位置估计＋三种合法模式切换＋音频辅助**。此前逐版路线索引移至 [历史索引](history/route-index-through-20261006.md)，不再把每个实验并列推荐。

## 常用入口

| 目的 | 根目录入口 | 输入 |
|---|---|---|
| 选择任务 | run_jump_rope_routes.cmd | 由菜单选项决定 |
| 打开主线逐帧审阅 | open_jump_rope_frame_review.cmd | 无 |
| 重新生成主线回放 | run_jump_rope_offline_review.cmd | 无，完整录像处理较慢 |
| 录制画面、声音和人工空格 | record_jump_rope.cmd | 只记录人工操作 |
| 旧实机回退，只判断 | run_jump_rope_local_motion_judgment.cmd | 无 |
| 旧实机回退，自动跳跃 | run_jump_rope_local_motion.cmd | 35ms空格 |
| 当前主线实测 | run_jump_rope.cmd | 音频＋模板判断，35ms空格 |
| 单次输入排查 | run_jump_rope_test_space.cmd | 单次空格 |

run_jump_rope.cmd 无参数现在启动当前音频主线并发送35ms实验空格；菜单第5项也指向它。请在游戏开始界面启动，程序准备好后自动切回游戏，再开始这一局；看见Go消失才允许跳跃。保持游戏声音开启、游戏在前台。停止键为F12/Ctrl+C，失焦停止并释放空格。时机仍待实机标定，不能保证零失误。命令参数 --mainline 可只判断； --mainline --experimental-live 才发送。旧自动回退入口保留。

## 当前基线与实验

历史离线对照基线：jump_rope_audio_prefix_config.json / audio-prefix-confirm，保持原输出。当前开发候选：jump_rope_guarded_commit_config.json / mainline-review；三个旧回归点保留，3563减速误切被阻止，3710选中阶段3加速。阶段5接管、5758及若干位置偏差仍未解决，不代表整段已准确。离线重建入口默认生成当前候选，可用--settings显式指定历史基线配置。长窗口、相位重建、计数识别是独立实验，不默认为改进版本。开发细节和准确交接信息见 [HANDOFF](HANDOFF.md)。

旧实验启动器统一在 tools/jump_rope/legacy_launchers/，已调整项目根路径；[归档清单](../../tools/jump_rope/legacy_launchers/manifest.json)记录原位置和校验值。旧识别器、配置、模板与测试保留原路径，避免破坏继承关系及复现实验。

## 数据与空间

人工标注、原录像、模板库是开发依据；逐帧图片和重复预测输出是派生产物。现有标注来源页面仍可打开，所以本轮没有删除它们。数据分类与空间统计见 [整理报告](reports/project-cleanup-20261006.md)。以后每个实验统一使用参数和独立输出目录，不增加一个根目录cmd。

本轮结果与限制见[速度提交保护报告](reports/guarded-speed-commits-20261006.md)。检阅页增加重点帧选择、下一速度提交和同帧窗口优势。

阶段5独立候选：jump_rope_terminal_stage_config.json / terminal-stage-review。用户确认最高难度只有三个固定速度档位；终局只比较固定档位与合法模式，不再搜索新阶段。当前主线保留，独立候选仍待速度标定，见[阶段5策略](reports/terminal-stage-strategy-20261006.md)。

本轮已接入空格，详见[实机输入报告](reports/mainline-input-20261006.md)。[短按逐帧检阅](../../runtime/jump-rope/frame-review/mainline-input-review/index.html)复用主线图片，7529帧，仅模拟请求，不代表真实自动游玩。

用户随后确认不需要落地识别：当前实时入口只按绳子时钟发送，角色遮挡不抑制输入；保留0.30秒防重复间隔。更新后的逐帧模拟为124次请求，非实机成功率。

run_jump_rope.cmd默认已开启实时预览，显示整绳可见点/预测曲线、模式速度、声音提示、空格请求与剩余时机；窗口不抢游戏焦点。

最新实测约定：用户要求暂按显示预测完全正确处理。当前输入只依据显示曲线所属时钟，不再因置信度、角色/落地、45ms耗时或80ms帧间隔抑制。按处理时间续推同一时钟；刚跨过起跳位置35ms以内允许本次短按，之后不补旧圈。前台/F12/窗口检查和35ms释放保留。详见[预测与输入对齐](reports/prediction-input-alignment-20261006.md)。

按显示预测的新版本已通过556项测试；最新7529帧检阅为132次模拟请求（替代前一版124次）。

[实时性能与GPU调查](reports/runtime-performance-gpu-investigation-20261006.md)已保存；按用户决定暂不实施加速，继续测试当前版本。

最新实测配置：jump_rope_acceleration_config.json，加速候选确认/保留/退出规则已接入；仅阶段1–4可靠加速声音窗口启用，低空和阶段5沿用原规则。572项测试通过，原录像回归保留，实机改善待复测。当前检阅页为acceleration-review/index.html，详见[加速证据策略](reports/acceleration-evidence-policy-20261006.md)。
