# 速度提交保护与完整逐帧检阅（2026-10-06）

本轮以audio-prefix-confirm为对照，完成8轮预测实验及最终7529帧完整导出。当前开发候选为jump_rope_guarded_commit_config.json；页面为runtime/jump-rope/frame-review/mainline-review/index.html。历史基线、原录像、模板、人工标注及旧自动回退全部保留。本轮没有向游戏发送输入。

## 实际结果

1405与2752仍是左右摇，而且这两帧的整绳预测曲线与基线完全一致；3244仍为阶段3正摇减速。3563的减速→加速误提交被挡住，活动项继续减速。其后3573由连续证据转正常、3706转加速；3710与3763选择阶段3加速，但这两个检查点仍无当前视觉支持，不能宣布几何问题已解决。4055的后续低空进入保留，后续方向没有因漏掉这一次低空而错一轮。

5164没有过早提交阶段5加速，保持阶段4正常；这是阻止旧误切，不是确认正确速度阶段。5231计数阶段已5、有效速度阶段仍4；阶段5接管仍不够好。5293仍无视觉支持。5758仍是阶段5加速，原位置/速度错误尚未解决。本轮只完成部分上游保护，不是全录像零失误版本。

| 原始帧 | 时间秒 | 对照活动模板 | 当前候选活动模板 | 当前视觉支持 |
|---|---:|---|---|---|
| 1405 | 24.357 | stage_1/low_swing | stage_1/low_swing | true |
| 2727 | 47.136 | stage_2/accelerate | stage_2/accelerate | true |
| 2752 | 47.562 | stage_2/low_swing | stage_2/low_swing | true |
| 2825 | 48.821 | stage_3/low_swing | stage_3/low_swing | true |
| 2955 | 51.063 | stage_3/low_swing | stage_3/low_swing | true |
| 3244 | 56.046 | stage_3/decelerate | stage_3/decelerate | false |
| 3563 | 61.544 | stage_3/accelerate | stage_3/decelerate | true |
| 3710 | 64.069 | stage_3/accelerate | stage_3/accelerate | false |
| 3763 | 64.989 | stage_3/normal | stage_3/accelerate | false |
| 4055 | 70.025 | stage_3/low_swing | stage_3/low_swing | true |
| 5164 | 89.125 | stage_5/accelerate | stage_4/normal | false |
| 5231 | 90.286 | stage_5/accelerate | stage_4/accelerate | true |
| 5293 | 91.349 | stage_5/normal | stage_4/normal | false |
| 5758 | 99.349 | stage_5/accelerate | stage_5/accelerate | true |

2727、2825、2955沿用audio-prefix-confirm的输出。用户七处反馈原先针对long-speed-window，不能把切回基线本身算作全部修复。2727计数/有效速度阶段仍2；计数提示仍默认关闭，未把OCR硬更新接入主线。

## 提交依据改动

新增guard_speed_commits开关，历史配置默认关闭。对减速退出、加速与减速直接互换、跨阶段圆周速度提交，以及名义速度差小于3%的角色切换，使用独立0.5秒记录。普通证据窗口仍0.32秒，低空进入/退出不借用新速度门槛。

歧义切换要求至少10个受支持的同帧配对记录、至少65%支持比例、配对平均绝对支持至少0.45、对当前时钟配对优势大于0.025；与其他阶段/角色时钟在共同时间上的优势至少0.015。无可信匹配声音要求观察跨度至少0.30秒；最近1.5秒同角色声音距离不大于0.22、类别差距至少0.04时仍需0.18秒视觉，声音不强制提交。

阶段5正常1.4325、加速1.45的名义时钟差约1.2%。比较采用名义模板速度，不能因活动速度小范围适配后看似相差较多而绕过歧义保护。这些模板和语音均来自同一录像，尚不能证明泛化。

速度阶段、时间窗口恢复及普通合法性通道共享保护方法。resolve_speed_commit在清理前保存真实获胜候选的同帧证据；speed_window_review仍是最近一次评估，不一定属于获胜者。通过候选编号、提交时间及guard_review区分，不再只看提交后的零证据。

全保留旧候选以及仅保留歧义圆周候选均试验过：前者2752/3244退步，后者3710仍停在减速并出现反复提交。两者未保留在最终实现。最终仍清理已提交速度队列，保留拒绝提交期间的候选；可撤销确认机制尚需设计，不能简单让全部旧时钟无限竞争。

## 检阅与复现

页面支持原始7529帧逐帧切换、播放、人工标注导出；增加14个重点帧入口、下一速度提交、候选同帧窗口优势、声音与实际提交前证据。原始时间与录像逐项相同，没有30FPS重采样。

现有run_jump_rope_offline_review.cmd默认生成当前开发候选。用--settings domains/hololive_dreams/models/jump_rope/jump_rope_audio_prefix_config.json可以显式选择对照配置；若需保留当前页，同时提供独立--output。没有增加根目录启动器。replay_audio_review.py还支持--no-export进行低占用预测实验，及--export-only从已保存且配置一致的回放重新生成页面。

## 验证与文件

- 全套unittest：529项通过（含12项新增提交保护测试）；日志runtime/jump-rope/guarded-commit-tests.log。最终审计记录调整后12项针对测试再次通过。
- 完整回放：7529个原始时间戳、7529张独立检阅图，manifest回放SHA256与文件一致，保存配置与导出配置一致。
- 1405/2752/3244回归检查通过；3563减速、3710加速模板标签检查通过。后两项仅验证状态标签，未验证几何。
- 页面脚本语法检查通过；模拟页面元素验证9个重点帧跳转、图像存在、重点帧选择、下一速度提交、标注保存与导出。另人工目视检查3563/3710/5164/5758对照图。未声称已在实际浏览器完整人工验收全部帧。

同目录transition-audit.json记录37次模板变更；speed-commits.json记录23次阶段/时间证据提交通道的提交，不含所有落地切换。comparison.json保存14个重点读数；experiment-summary.json保存8轮试验的重点状态、拒绝原因和转换摘要。中间预测大JSON删除以免堆积重复回放，无对应人工标注来源被删除。最终完整replay.json、frames.jsonl及图片全部保留。

下一步应从阶段5模板可分离性、5231阶段接管与5758之前首次错误速度选择继续，结合提交前序列验证；继续检查3763等位置误差。不要用帧号或人工语音时间直接排程，也不要把“大偏差重建”用来掩盖上游提交错误。

本轮清理8份新生成中间replay.json约641 MiB；保留对应摘要。最终检阅图对照见runtime/jump-rope/frame-review/mainline-review/comparison-grid.jpg，完整性记录见verification.json。
