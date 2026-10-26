## 最新：阶段2换档相位跳变修复（2026-10-06）

默认检阅页：runtime/jump-rope/frame-review/stage2-phase-handoff-review/index.html（5378帧）。2004帧人工点误差251.67→5.60像素；具体候选独立确认，圆周换档大跳变需连续强证据，过期声音不再缩短确认。阶段3–4保留原确认规则。17项相关测试通过，未发送真实空格。

阶段2真实加速确认有所延迟，其他8帧反馈尚未解决；详见reports/stage2-phase-handoff-20261006.md。以下旧页面与测试数为历史记录，以本节为当前入口。

## 最新：绳子得分与可见段标注（2026-10-06）

默认检阅入口改为 runtime/jump-rope/frame-review/rope-score-annotation-review/index.html。每帧显示模型匹配分数和独立外观检查分数，可点选可见绳段、标记遮挡、隐藏预测、跳至低分/分数冲突帧并导出schema2反馈JSON。操作：FRAME_REVIEW_ANNOTATION.md；报告：reports/rope-appearance-score-annotation-20261006.md。

自动时间候选已重新提取：35个候选、254个原始观测帧。严格外观强制选择试验发生反摇漏检，因此默认仅用外观分数作对照，不拦截输入；不要将该试验宣称为全状态修复。615项全套测试通过，诊断接入后复验29项选择/输入测试。下文旧267帧与旧页为历史记录，原反馈及原标注保持独立。

## 当前主线：阶段1–4整圈模板（2026-10-06）

默认 run_jump_rope.cmd 已接入整圈时间模板、实时预览和35毫秒空格。35个候选覆盖20种状态；阶段2减速暂不做，阶段5沿用旧路线。611项测试通过。仍有切换延迟和未实测状态，未验证实机自动成功。

新录像逐帧检阅：runtime/jump-rope/frame-review/timed-recording-current/index.html（5378帧）；旧独立录像：runtime/jump-rope/frame-review/timed-mainline-current/index.html（5082帧）。报告：reports/stages-1-4-timed-mainline-20261006.md。下文为历史记录，若与本节冲突以本节和实际默认配置为准。原标注页保留，打开入口加 annotations 可访问。

最新用户方向：整圈绳形模板按时间播放，比较候选、小偏差微调、大偏差恢复。离线原型已实现，第二圈内部15帧误差约10.74像素；目前未接入实时图像/空格。详见reports/timed-template-playback-20261006.md。

统一模板库已整理：domains/hololive_dreams/data/jump_rope_template_library/README.md。固定形态、阶段技能样本、生成数据、转换片段分别管理；原录像只保存一份，现有运行配置仍使用原文件。

用户确认（2026-10-06）：0–9圈只有固定正摇正常档，无反摇、加速、减速或低空技能。补录仅需阶段1正摇正常档；旧模板中其他阶段1分支是历史模型占位，不能作为游戏状态依据。详见RECORDING_CHECKLIST.md。

## 2026-10-06 最新：可见绳段微调与大幅纠错分开

主线采用jump_rope_visible_fit_config.json。可信画面的小偏差只做有上限的gentle修正；大偏差先积累独立窗口，再做recovery纠错。持续可信的观测速率优先于旧速度模板与音频；档位不明确时保留标签并记录gear_confirmed=false。30圈切换规则保留。590项测试通过，完整7529帧逐帧页面：runtime/jump-rope/frame-review/visible-priority-review/index.html。1405/2752低空、3244减速保持；3563标签与旧版不同，仍需复核，不能称全程已解决。详见reports/visible-priority-dual-path-20261006.md。

## 2026-10-06 最新：30圈直接换挡

主线在本地计数稳定确认达到30后直接切换阶段3速度模板，保留方向与技能，不等待阶段候选比较。577项测试通过；7529帧回放在2691帧读数30触发一次。最新逐帧页面：runtime/jump-rope/frame-review/count30-review/index.html。详见reports/count30-forced-shift-20261006.md。

# 新对话交接：hololive Dreams 跳绳

更新：2026-10-06；项目 F:\Codex\Game_agent。建议新对话先阅读本文件、docs/PROJECT_CONTEXT.md、docs/USER_GUIDE.md、docs/general-vision.md，再检查实际代码。旧路线历史只在需要追溯时读。

## 最新：加速候选规则已接入

用户要求检查并修改加速确认/保留/退出。run_jump_rope.cmd的当前音频主线改用jump_rope_acceleration_config.json；新AccelerationEvidenceBank仅阶段1–4可靠完整加速声音1.5s窗口内启用同帧确认、一个有限保留候选与更强的正常档退出证据。最初统一加长退出导致2752回归，已撤回并缩小到可靠声音窗口。572项测试通过；7529帧最终重跑，与原guarded预测曲线/相位一致，1405/2752/3244与原改善点保留。前段录像没有覆盖实测强声音仍选正常的场景，所以需要用户复测；不要声称已经解决全部速度选择。报告reports/acceleration-evidence-policy-20261006.md。

最新逐帧页acceleration-review/index.html，验证渲染输入一致后只读引用mainline-review原图片，无图片复制。打开和离线重建入口默认新配置；旧guarded配置保留。实机日志新增配置路径、配置内容、速度审查/提交和保护候选；用户仍要求显示预测驱动空格，不恢复置信度/落地抑制。GPU和捕获未改。

## 最新决定：暂不实施性能/GPU加速

用户要求先保留调查文档，继续测试当前版本能否满足使用。报告reports/runtime-performance-gpu-investigation-20261006.md记录RTX 3060 Laptop、本次41 FPS与耗时、当前CPU实现、GPU可选方向及限制。没有安装依赖或改捕获/识别路线；后续不要把GPU迁移当成本轮尚未完成的必做项。

## 最新补充：输入以显示预测为准

用户看到曲线预测正常但不发送，要求暂把显示预测视为100%正确。最新控制器只要求Go后有模型曲线及有效时钟，不再要求locked/confidence或角色/落地，不因帧间隔/处理耗时单独禁止输入；后台音频故障也不覆盖现有显示预测的输入。mainline_trust_prediction只作用于新主线，旧路线仍保留原鲜度门槛。按识别耗时续推当前显示时钟到派发时刻；早35ms至晚35ms允许一次短按，跨越后不再取模等到下一圈，也不补发更早的圈。保留0.30s防重复、Go开局、非单调时钟抑制、窗口/焦点/F12/异常释放。该约定是用户指定的输入实验假设，不将真实识别/跳跃标定标记verified。556项测试通过；最新7529帧检阅为132次模拟请求。报告reports/prediction-input-alignment-20261006.md。

## 最新：用户要求接入空格实测

run_jump_rope.cmd 无参数改为 --mainline --experimental-live；菜单第5项也改为当前主线。新增jump_rope_mainline.py：guarded配置、因果扬声器回环音频、同离线候选软加分与低空授权、ROI内Go开局门；按用户补充，去掉中央角色/落地识别，纯绳子模板时机触发。空格35ms同步短脉冲，释放不等下一次识别；F12/失焦/异常释放。时机来自原录像人工按下时的模板坐标初始值（正.74、反.25、低空前行.12/回程.98），不是已验证的短跳标定，不按录像时间或帧号安排动作。仍使用当前guarded主线，未启用终局实验。

新增7529帧短按检阅runtime/jump-rope/frame-review/mainline-input-review/index.html，复用主线图，124次模拟请求；纯绳子时钟判断，无法推断自动成败。550项测试通过。控制器只在输入实际派发后登记跳跃；计数不代替999成功验证。实机启动前留在开始界面，准备完自动聚焦游戏，再开始，需见Go。报告reports/mainline-input-20261006.md。

## 最新用户方向与独立候选

2026-10-06用户认可阶段5之前的识别，确认阶段5是最高难度且只有固定三个速度档位，此后无阶段升级；要求按独立策略考虑。已新增TerminalStageBank及jump_rope_terminal_stage_config.json。阶段5实际速度接管后锁定终局，保留三个档位的独立时钟，遮挡时续推，比较共同可见证据；三模式规则沿用。接管前保留旧速度过渡，不在计数70时强制改速。

当前主线mainline-review仍保留；独立候选页面terminal-stage-review/index.html。具体三个速度数值未重新标定，正常/加速相近及减速待标定仍是瓶颈，不要宣传终局已准确。报告reports/terminal-stage-strategy-20261006.md。

## 本轮进展（2026-10-06，继续开发）

最新开发候选为jump_rope_guarded_commit_config.json，完整逐帧页runtime/jump-rope/frame-review/mainline-review/index.html；历史audio-prefix-confirm基线保留。新增guard_speed_commits只对减速退出、加速/减速直接互换、跨阶段圆周速度，以及名义速率差小于3%的角色切换检查0.5秒独立同帧证据。无可信匹配声音要求至少0.30秒，有声音仍要求0.18秒。普通速度/低空规则保持原证据窗口，避免统一加长影响2752。

保住1405/2752/3244，3563保持减速，3710选中阶段3加速；这仅证明状态检查通过，不证明几何正确。5164未过早选阶段5加速，但5231仍未接管正确速度阶段；5758问题保留。保留全部旧候选及仅保留歧义圆周候选的试验均出现回退/错状态，未纳入最终代码。提交仍有候选清理，应继续解决明确确认后的可撤销机制，而不是随意保留旧时钟导致来回切换。

529项测试通过；报告docs/jump-rope/reports/guarded-speed-commits-20261006.md。提交前真实证据保存在speed-commits.json和对应replay帧；speed_window_review是最新评估，未必获胜，请核对候选编号与时间。复现入口run_jump_rope_offline_review.cmd默认当前候选；旧配置需显式--settings。当时新主线仅离线；最新输入状态见顶部。

## 下一步任务

沿“轨迹模板库＋整绳估计＋合法模式切换＋音频辅助”继续开发。首次3563误切已由保护规则阻止，继续检查减速退出后的正确速度确认、阶段5正常/加速模板的可分离性，以及5758之前首次进入错误分支的提交。防止一次错误清掉正确候选而使后续全错。不要把大偏差重建当作主修复，也不要为了目录整齐重写已有基础。用户认可该路线的遮挡跟踪，但尚未解决全部切换和速度问题。

## 已确认规则

- 空格短按约35ms。超过100ms会跳得更高，滞空影响下一次跳；空中按键无效，需落地。目标零失误，最大999；三条命不是允许失误的目标。
- 只关注中间箭头所指角色；旁边角色是气氛组。
- 正摇、反摇、低空左右摇三种合法模式；速度有阶段及正常/加速/减速，允许小范围校正。下落时不能长期零速；低空转向点瞬时零速但加速度存在。
- 反摇有独立发力/时间曲线，不能倒放正摇。低空结束必换方向：从后往前接反摇，从前往后接正摇。
- 计数门槛10/30/50/70对应阶段2/3/4/5。计数阶段和有效速度阶段分开，当前技能可继续旧速度；应保留旧、新阶段候选，不能机械强制更新。
- 绳子颜色不是必需线索，后期技能可能不变色；背景会换。整条连续平滑曲线和局部可见片段用于遮挡估计。
- 语音：ikizo左右摇；otsupekoyo加速；减速da减速；牛dong掉落物只影响遮挡，不影响速度或方向。声音含起跳声，匹配不是无误的。
- 前半圈安全，允许更长确认窗口；危险前必须有正确预测。丢失时按合法模板继续预测并尝试恢复，不因not observed马上退出；手动停止/失焦仍释放输入。

## 当前有效入口与状态

历史离线对照配置 domains/hololive_dreams/models/jump_rope_audio_prefix_config.json；当前开发候选为jump_rope_guarded_commit_config.json。
主线脚本 tools/jump_rope/replay_audio_review.py，默认前缀基线，支持--settings、--output、--audio-cache。
保留基线审阅 runtime/jump-rope/frame-review/audio-prefix-confirm/index.html。
根目录run_jump_rope_offline_review.cmd输出mainline-review，避免覆盖基线；open_jump_rope_frame_review.cmd优先打开它，无则打开基线。

新音频编排已新增实时输入包装器；视觉配置input_enabled=false仍约束原phase只判断入口，新的--mainline使用独立输入控制器并要求experimental-live。旧自动回退run_jump_rope_local_motion.cmd保持35ms实验空格。不要把旧A/G和最近音频实验混为同一基线。

long-speed-window挡住部分误切，却使2752左右摇退步，不能替代基线。phase-reanchor-review、count-phase-review也是隔离实验。计数实验通过use_count_hint显式启用，默认关闭。当前根目录旧cmd归档至tools/jump_rope/legacy_launchers/，核心代码/资产未搬动。

## 已知错误与回归点

| 帧 | 时间秒 | 已确认意义 |
|---|---|---|
| 1405 | 24.3567 | 应为低空左右摇，基线正确 |
| 2752 | 47.5618 | 应为低空左右摇，基线正确 |
| 3244 | 56.0464 | 应为正摇减速，基线正确 |
| 3563 | 61.5436 | 减速错误切加速，confirmed_temporal_speed_recovery |
| 5164 | 89.1251 | 错误选阶段5加速，confirmed_speed_stage_branch |
| 5758 | 99.3489 | 错误选阶段5加速，confirmed_temporal_speed_recovery |

速度提交来自多个通道，旧规则可仅6个好帧/约0.12秒就接管；有的只比活动项，不比次优角色。提交后self.items=[best]、证据清空，使后续正确分支难以回来。误切时没有对应可靠加速声音授权。EMA快照分数不能当作真实配对窗口优势。需要查看提交前连续证据，不能只看提交后归零的证据。

检查工具tools/jump_rope/audit_audio_regression.py，输出基线transition-audit.json已保存。当前只自动断言三个已修状态点，不能据此宣称全录像准确。用户七个后续反馈保存在domains/hololive_dreams/data/jump_rope_samples/human/20261006-seven-phase-stage-feedback.json；应先修上游再验证2727/2825/2955/3710/3763/5231/5293。

## 实现地图

- domains/hololive_dreams/models/jump_rope_phase_gear.py：局部视觉、多曲线相位搜索、模式/阶段观测。
- src/modular_agent/realtime/trajectory_bank.py、staged_trajectory_bank.py、landing_trajectory_bank.py、coexisting_stage_bank.py、evidence_recovery_bank.py：模板时钟、落地分支、阶段竞争和恢复。存在继承/共享，不能直接删除旧层。
- phase_tracking.py、curve_evidence.py、phase_evidence.py：相位及曲线视觉证据。
- audio_cues.py：本地频谱/DTW和语音证据；GoStartGate在jump_rope_start_gate.py。
- jump_rope.py：原组件调度、控制、输入接口；runtime.py/keyboard.py：共用实时框架。
- record_jump_rope.py/loopback_audio.py：录屏、人工输入、扬声器回环，共用单调时钟。
- export_jump_rope_review.py、tools/jump_rope/audio_review.html：完整逐帧审阅和波形标注。

## 必要资产与录制

主配置引用rotation_audio_wide_v1.json（新宽机位）、swing_v1.json（旧机位，未充分校准）、audio_forward_decelerate_trial.json（阶段3正摇减速约0.5475圈/秒）、stage_badges_v1.json，位于domains/hololive_dreams/data/jump_rope_phase/。不要因文件名trial就删除。

新录像runtime/jump-rope/recordings/20261005-185136-145077：7529帧、约129.86秒、1280×720，含audio.wav及时间戳。旧录像20261003-135733-386995：4010帧、无音频。声音模板runtime/jump-rope/audio-calibration/reviewed-cue-templates.json是离线脚本依赖，不能把整个runtime视为可删缓存。
人工标注17份在domains/hololive_dreams/data/jump_rope_samples/human/，音频标签20261005-reviewed-audio.json。时间段表示人工语音范围，不是硬编码状态切换时刻。模板来自同录像，尚不能证明泛化。

## 工作约束与验证

使用.conda/python.exe，PYTHONPATH=src，PYTHONUTF8=1。pytest未安装，用unittest discover；最后已跑全套为517通过，新计数模块尚未完整测试。先离线完整回放并保住三个回归点，再只判断实机，最后才接入输入。不得逐帧请求大模型/OCR/UIA/全屏模板；顶层默认full识别、猜高低和钓鱼接口保持。

截图存在不代表成功；画面消失为unknown。最新帧优先、单调时钟、显式按下释放、结束异常释放所有输入。用户已授权当前主线接入空格实测；不用录制时间或帧号硬编码状态。

## 可复制到新对话的请求

继续开发F:\Codex\Game_agent，先读docs/jump-rope/HANDOFF.md及当前说明。以audio-prefix-confirm为离线基线，沿模板库＋整绳估计＋三模式切换＋音频辅助改进。以mainline-review速度提交保护候选继续，保持3563减速与3710加速，处理阶段5接管、5758及其之前的首次错误提交，保住1405/2752左右摇和3244减速；不要优先用大偏差重建掩盖上游错误。保留旧自动回退及人工数据，离线验证后给出完整逐帧审阅。不要增加每次实验一个根目录cmd。
