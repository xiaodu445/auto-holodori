# 新音画校准与实测时钟，2026-10-05

## 已完成

新录像 7529 帧、约 130 秒、57.98 FPS，编码无丢帧。音频连续样本和单调块时间已核对，未报告设备错误；实际音画偏移尚未独立校准。

新机位比旧录像更宽，先用 9–19 秒普通蓝绳重建空间图集 rotation_audio_wide_v1.json，再独立拟合正反摇时间曲线。未改旧图集、A/G 默认自动入口或分支策略。新空间图集只适用于本录像机位，低空图集尚未重建，不应直接替换整套实机配置。

39 个四秒窗口：前约 75% 拟合、后约 25% 检查未来位置；28 个窗口因拟合/未来支持低、歧义或周期不足排除。11 个合格窗口按方向、计数阶段提示及相近速度合并为 6 组候选。每组保存完整周期位置、速度、加速度和来源时间；反摇独立拟合，不倒放正摇时间曲线。

数据：domains/hololive_dreams/data/jump_rope_phase/audio_recorded_clock_cohorts_v1.json。可读表和曲线：runtime/jump-rope/audio-calibration/measured-clocks.csv、measured-clocks.svg。

## 验证边界

未来检查是同录像开发检查，不是独立录像验收；背景分位统计仍用了整个窗口。图集来自同一录像，部分早期窗口与图集训练区间重合，代表样本优先选择未来区间在 19 秒之后的窗口。分数是视觉支持，不是准确率。

记录的是屏幕轨迹相位，不是已校准的真实三维角度。计数阶段提示也不是实际速度阶段。六组保留 skill_role=null 和 effective_speed_stage=null，未假造“正常/加速/减速”名称。低空、被遮挡或跨状态的窗口不能硬拟合成圆周模板。

## 声音

本地 base/small 日语语音识别无法可靠定位短促技能口号，诊断转写不用于标签。没有上传声音。试听页 runtime/jump-rope/audio-calibration/index.html 按原始单调时间对齐画面与音频；标开始、结束、四类含义，导出 jump-rope-audio-reviewed.json。用户已表示回来标明，当前尚未收到这些区间。

新增 audio_cues.py：16kHz 局部频谱、音量归一化、受限 DTW 比对和低支持拒判；只接受人工确认的标签，阈值还需另一次技能出现和负背景验证。它目前是离线候选工具，不控制跳跃，不是实机声音识别已完成。

导入（项目根目录 PowerShell）：

```powershell
$env:PYTHONPATH='src'
.conda\python.exe -m modular_agent.realtime.audio_cues --recording runtime/jump-rope/recordings/20261005-185136-145077 --annotations runtime/jump-rope/audio-calibration/jump-rope-audio-reviewed.json --output runtime/jump-rope/audio-calibration/reviewed-cue-templates.json
```

导出文件需放到上述 annotations 路径，或改为实际路径。导入检查录制来源一致；不接受其他录像的时间区间。后续用确认的语音区间定位技能前后完整周期，补全各阶段正反摇速度及低空曲线，再独立回放核对，最后讨论分支规则接入。

## 自动检查

完整回归 506 项通过；随后补充的 WAV 重采样/人工片段导入测试及声音模块共 4 项通过。新测试覆盖增益不变性、异类音调区分、未审核拒绝、空片段拒判、时间映射、越界片段拒绝，以及反摇解析速度与曲线导数一致和低未来支持排除。这些是工具正确性检查，不代表真实技能声音检出率。

## 波形剪辑标注页

试听页已改为完整采集帧与约 2 毫秒 min/max 波形。拖动选择片段，拖边缘裁剪；滚轮缩放，Shift＋滚轮平移，概览点击定位；←/→ 逐原始源帧，I/O 标起止，空格播放，支持 0.5/0.75 倍速和仅试听选区。数值框使用采集单调秒，与旧导出格式和缓存键兼容，原已标片段保留。新增条目列表、定位及删除；最终导出 JSON 保存。音频样本时间与画面时间通过原块时戳互相映射，帧步进不假定固定帧率。

可复现生成器 tools/jump_rope/export_audio_review.py 和页面模板 tools/jump_rope/audio_review.html；在项目根目录运行生成器，传 --recording 录制目录及 --output 含 analysis-mono.wav 的输出目录。仅浏览器本地播放和标注，不控制游戏输入。
