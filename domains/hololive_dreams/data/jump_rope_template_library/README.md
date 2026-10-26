## 最新检阅（2026-10-06）

自动候选已用外观/细线检查重提取，35个时间候选包含254个可追溯观测帧。严格外观选择试验存在反摇漏检，默认只输出独立外观分数用于人工对照。最新可见段/遮挡标注页：runtime/jump-rope/frame-review/rope-score-annotation-review/index.html。报告：docs/jump-rope/reports/rope-appearance-score-annotation-20261006.md。原人工点与原反馈保留。

## 当前运行库（2026-10-06）

阶段1–4默认加载 generated/stages_1_4_timed/catalog.json：35个候选、20种状态，阶段2减速排除。generated/automatic_cycles 保存自动提取原点及来源；人工点和原录像不改写。候选 active_runtime=false 是原始导出状态，是否加载以运行 catalog 和默认主线配置为准；运行接入不等于 verified。阶段5沿用原模型。详情见项目 docs/jump-rope/reports/stages-1-4-timed-mainline-20261006.md。下文原路线描述为历史。

# 跳绳统一模板库

本目录集中管理固定绳形候选、阶段技能状态、人工样本和生成数据。当前运行程序仍读取原jump_rope_phase目录，避免整理时改变已测试行为。本库导入数据均未自动晋升为正式模板。

## 目录

- shapes/rotation/wide_camera_v1：当前宽机位旋转绳形候选，candidates.json保留各相位41点整绳曲线；metadata.json保存原文件、校验值、机位与标定状态。
- shapes/low_swing/legacy_camera_v1：旧机位低空固定绳形候选，需要新机位补录。不可直接当成已验证的新机位数据。
- stage_1/normal_forward：阶段1唯一真实状态。阶段2–5分别包含normal/accelerate/decelerate的forward/reverse和low_swing，共29个状态目录；某组合实际不出现时，将该状态明确标记为unavailable，不需要录制。
- 每个状态的index.json：待补录或待独立验证状态、参考速度、绳形引用、来源和样本索引。
- 每个状态的generated/legacy_import/template.json：从当前主线参数提取的历史生成数据。包含完整原分支，使用时只取指定方向；没有方向形状的数据仍是占位参数，不表示已测量。
- 每个状态的samples/：存新增人工片段标注和提取结果。开始为空，没有虚构样本。
- recordings/index.json：引用5个现有原始录制目录和文件大小，原录像留在runtime/jump-rope/recordings，不在本库重复复制。
- annotations/：17份原人工标注的副本及来源索引。不同录像或旧回放的帧号不能直接混用。
- transitions/：阶段切换、技能进入/退出、方向变化、遮挡恢复的样本索引，目前待精确分段。
- schemas/sample.example.json：新样本登记格式，空值是待填写，不是已完成标注。
- manifest.json：总目录、来源校验及晋升规则。

## 新样本流程

1. 原始整局录像连同时间戳、音频、人工按键、summary.json放在原录制目录，只保存一份。登记到recordings/index.json。
2. 在相应状态的samples/建立唯一的sample_编号目录；复制sample.example.json为metadata.json，填写来源录像编号、原始帧区间[start,end)、机位、人工状态确定程度、可见性及训练/验证用途。由不同局分别提供拟合与验证样本。
3. annotations.json保存实际人工标注的可见点、周期边界、遮挡与技能边界；measurements.json保存从原始时间戳计算的相位、速度、残差及提取工具版本。未提取前不要建立虚假的测量文件。可选clip.avi仅供查看，时间以原录像timestamps.json为准。
4. 稳定样本登记在状态index.json的samples；转换片段登记在transitions/index.json。切换段不能与稳定档混算平均速度，低空需保留完整往返。
5. 拟合完成后写入状态generated/新的版本目录/template.json；保存来源sample_id列表、处理参数、形态版本、误差与独立验证结果。旧版本保留。正式采用时明确指定运行配置和模板版本，不通过扫描目录自动加载最新文件。

固定形态与时间模型分开：阶段技能引用形态库，不为每个速度复制整绳曲线。后续背景排除应检查可见片段能否对应固定绳形、两端和连续运动；遮挡允许缺失。本次保存候选与来源，没有新增背景拒绝算法，形变容差仍待标定。

整理校验工具：tools/jump_rope/validate_template_library.py。首次历史导入工具organize_template_library.py对不同的已有内容会拒绝覆盖；它不是新增样本或更新索引的工具。

补录清单：docs/jump-rope/RECORDING_CHECKLIST.md。
