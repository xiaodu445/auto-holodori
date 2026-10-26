# 人工声音片段导入，2026-10-05

用户提供 15 段确认区间：左右摇 6、加速 6、减速 2、掉落 1。原始区间完整保存到 domains/hololive_dreams/data/jump_rope_samples/human/20261005-reviewed-audio.json，并生成 runtime/jump-rope/audio-calibration/reviewed-cue-templates.json。

掉落提示只意味着观察质量可能降低，不改变速度、不改变方向，不是第四种速度档。audio_cues.cue_effect 明确分开 motion_hint 和 occlusion_hint；其模板可用于区分声音及拒判，不能成为加减速证据。没有接入自动控制。

## 首次声音检验

每次测试排除被测片段本身，使用同类其他出现作为模板；掉落只有一段，无法做同类留出检验。原有阈值 .16、差距 .03 未为追求召回盲目放宽。

14 个留出事件：4 个正确接受、0 个错误接受、10 个拒判。17 个未标注背景抽样：2 个被接受（117 秒加速、121 秒左右摇）。这些区间尚未由用户确认，不能直接断言是假阳性，也不能当正确识别。当前模型不具备实机切换可靠性，不把人工裁剪片段检验当成连续流检出率；未测触发延迟、起止定位或独立录像泛化。

这是初始局部频谱/DTW 模板的诊断结果，提示需要背景抑制、起止对齐或更稳健声学特征。自动输出保持候选；下一步优先根据人工确认的声音区间验证运动模板，而不是让低可靠声音结果驱动状态。

结果 runtime/jump-rope/audio-calibration/cue-holdout.json；复现工具 tools/jump_rope/evaluate_audio_cues.py。

## 轨迹校准索引

window-fits-audio-context.json 给已拟合的 39 个窗口附上最近运动提示、重叠运动提示和遮挡提示；cue-anchored-trajectory-plan.json 保存提示结束后至下一提示前的候选采样区间。语音播放起止不是精确运动切换边界，也不证明技能持续到下一提示，必须结合画面完整周期核对后才能命名模板。计数阶段提示仍不是速度阶段。本轮未重新宣称旧六组候选已完成阶段/技能定标，旧 A/G 路线保持。
