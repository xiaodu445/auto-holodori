# 左右摇修正与逐帧审阅（2026-10-05）

本轮保留原G与阶段原型，不覆盖旧入口。新增两个仅判断入口：

- `run_jump_rope_gear_review_judgment.cmd`：原G速度集，加本轮低空修正。
- `run_jump_rope_stage_review_judgment.cmd`：分阶段模型，加本轮低空修正。

两个入口都不发送空格，沿用F12/Ctrl+C/失焦停止和原会话时限。自动跳跃A未修改。不能宣称已经完全解决瞬移。

## 发现与修正

旧时间模板生成器在起点缺失样本时用np.interp夹取第一个可见角度，形成0～0.05时钟段约0.183的角度变化。这个节点没有实际起点测量支持。新增v2采用两次重复运动的角度样本和周期平滑约束，联合搜索起始时刻，拟合时不再夹填缺失起点；该段变化约0.071。正时钟始终推进，低空端点允许位置速度瞬时为零、加速度非零。仍是单录像实验模板，不是引擎真值；其他阶段共用此形状仍未验证。

更重要的逻辑问题：低空有两个进入半程，却共用同一退出边界。新开关`swing_boundary_by_branch`记录每条候选的进入时钟，使用对应的返回边界；换挡子候选继承该边界。状态确认时保留候选从边界已经播放的行程，不能从确认瞬间重新累计整个周期。原配置不开启该开关，原G核心输出已逐帧核对保持一致。

灰黑色来自置信度降低后的unknown绘制，不是物理停止。新审阅入口即使置信度低也用橙色画模型，并明确标出没有视觉支持；不把它算成实测。跨状态确认仍会切换到已经播放的候选，可能出现几何跳变，未用画面插值隐藏它。

确认策略以危险经过前准确、稳定为目标，允许前半程积累证据。现有稀疏状态检查用于定位，不能把某个安全半程时间点的迟确认直接当作失败。尚缺逐帧人工危险经过标注，因此没有声称起跳成功率提高。

## 完整离线对照

所有回放均4010原始帧，仅判断，模拟跳跃0；以下几何误差来自少量可见绳子人工点，不是整场准确率：

|版本|20秒|32秒|55秒|
|---|---:|---:|---:|
|旧G|5.67px|6.98px|0.81px|
|仅平滑G|5.74px|19.83px|3.09px|
|新边界+平滑G|5.74px|6.94px|8.48px|
|旧阶段原型|5.76px|115.75px|12.60px|
|新边界+平滑阶段原型|5.09px|36.53px|5.62px|

阶段原型有所改善，但仍不能替代旧G。只改第一个角度节点的保守试验导致32秒错误低空、约272px，保留在conservative目录，未采用。不要运行该失败配置来替代正式入口。

447项测试通过；原G4010帧的whole_curve、phase_estimate、motion_state、selected_hypothesis与原报告逐帧完全一致。离线CV耗时受同时导出影响；不代表实机采集/控制60FPS验收。

## 逐帧文件与人工标注

审阅入口：`runtime/jump-rope/frame-review/index.html`，用浏览器打开。

- G新修正：`branch-boundary/index.html`。
- 阶段新修正：`stage-boundary/index.html`，包含等级、徽章确认来源和候选分支。初始阶段1是先验，最早约0.159秒徽章确认；阶段3提示动画本来约延迟1.3秒。
- 每个目录的`frames/000000.jpg`起对应一张原始采集帧，没有30FPS视频重采样。编号从0开始。
- `frames.jsonl`每行含该帧时间、相邻帧间隔、完整识别输出、决策、当前模式、阶段、模型编号、时钟/速度/加速度、候选（最高分四项）、合法性、视觉支持、落地批次、待确认时长及本帧事件。
- 当前选中模式是控制状态；visual=true表示当前有足够图像支持，预测不是实测。候选分数不是概率。
- 方向键逐帧，Shift+方向键移动10帧；按钮跳到切换/较大曲线跳变。可填写实际模式、阶段、问题和备注，保存当前帧后导出`jump-rope-human-labels.json`。浏览器缓存不是可靠文件保存，务必导出。
- 未启用阶段的G页面不会伪造预测阶段；可人工填写。

建议优先标注：低空前后两个半程、转折点、进入/退出边界、遮挡后重新出现的首帧，以及接近脚部的危险经过。记录“帧号+应该处于哪个模式+绳子在哪+是否允许此处确认”。用户提供标注后再校准确认条件；不凭空补真实危险规则。

## 复现

设置PYTHONPATH=src和PYTHONUTF8=1：

```text
.conda\python.exe -m modular_agent.realtime.build_jump_rope_smooth_time --regularized
.conda\python.exe -m modular_agent.realtime.validate_jump_rope_phase --gear --no-video --gear-settings domains/hololive_dreams/models/jump_rope/jump_rope_stage_config_review.json --output-dir runtime/jump-rope/frame-review/stage-boundary
.conda\python.exe -m modular_agent.realtime.export_jump_rope_review --replay runtime/jump-rope/frame-review/stage-boundary/replay.json --output runtime/jump-rope/frame-review/stage-boundary --settings runtime/jump-rope/frame-review/stage-boundary/settings-used.json
```

G同理使用jump_rope_phase_gear_config_review.json。验证耗时指标和配置快照在report.json/settings-used.json；source-manifest.json记录源码摘要。逐帧导出独立于专用实时循环，不增加每帧采集负担。未自动启动游戏，也未发送任何游戏按键。


## 1178帧反馈：档位与难度、低空退出速度（2026-10-05）

用户确认初始难度阶段没有反摇。本项目公开难度从1编号，用户的初始阶段0对应项目阶段1；speed_gear=0则是速度候选下标，不能当成难度。原逐帧stage-boundary的1178帧为25.444805秒、难度2、反摇、速度候选0（暂标减速），并非难度0。反摇确认实际发生在1103帧/23.808秒；若用户使用了其他视频帧编号，应保留这一时间对照。

该段慢档确实异常：确认速度约0.633圈/秒，随后下降至约0.616，下一次落地到1180帧才换较快档位。原因之一是旧Landing规则不允许低空退出后的其他速度候选自由确认，方向一旦确定就连同档位锁住，局部相位修正也会向档位下限推速度。

独立开关exit_speed_branches保留同一退出边界的速度候选，在方向确认后继续按相同帧时间的证据窗口比较；这些候选确认前固定播放，不能自行漂到慢速下限。旧G不启用。原速度数字绘制改名speed slot，减少编号混淆。

initial_stage_forward_only只在阶段徽章已经确认初始难度时禁止反摇。未知初始阶段不强行禁反摇，避免从高难度中途启动时套错规则；之后阶段允许反摇。原stage-boundary逐帧文件保留，不覆盖人工标注来源。

全局上半圈速度辅助试验导致后段状态退步，保存在rate-assist目录，不采用全局版本。继续对低空退出后的方向重新武装前窗口做限定试验；未经全场对照不能宣称速度问题已全部解决。


限定退出窗口的最终试验在exit-rate-assist目录：1140帧速度由0.6326提高到0.8168圈/秒；1178帧由0.7272变为0.7568。改动不是人为把第1178帧设成某速度，而是连续上半圈几何相位链（至少5帧、跨度0.12秒、残差<0.012、质量/运动/覆盖要求）测得的速度辅助。只在低空退出后圆周尚未重新武装的窗口使用；仍限于当前档位范围，不改变方向。过期0.12秒不再使用。

全场仍有退步：55秒误差16.77px（旧阶段审阅版本5.62px），32秒38.93px（旧36.53px）。因此这是针对用户反馈的独立改进试验，不替换旧G；没有宣称整场更优。阶段审阅启动器使用这份限定窗口试验配置，旧逐帧图片/标注来源不覆盖。451测试通过，完整4010帧无模拟空格。


2026-10-05 五处人工标注：1978仅标记加速、不作方向真值。独立只判断入口 `run_jump_rope_human_calibration_judgment.cmd`；逐帧页 `runtime/jump-rope/frame-review/human-calibration-clean-bank/index.html`。843/2279低空偏差改善，1978加速仍退步，不替换原G或A。详见 [校准报告](../reports/human-calibration-20261005.md)。


2026-10-05 三处标注跟进：独立入口 `run_jump_rope_clock_exit_judgment.cmd`，仍只判断；新逐帧页 `runtime/jump-rope/frame-review/clock-exit-reverse-cohort/index.html`。反摇退出多档竞争与重复帧证据窗口改善1115/2484附近；1869加速仍未修好，55秒位置退步，不替换原G。见 [分析与限制](../reports/clock-exit-20261005.md)。


2026-10-05 低空退出方向规则：从后往前才接反摇，从前往后才接正摇，且退出必与进入前反向。独立只判断入口 `run_jump_rope_directional_exit_judgment.cmd`；逐帧页 `runtime/jump-rope/frame-review/directional-exit/index.html`。902错误候选消除，959生成合法候选，1087确认反摇；加速1869仍未解决。见 [规则、接点与回放证据](../reports/directional-exit-20261005.md)。


2026-10-05 阶段速度库独立实验：模板改为“阶段 X → 正常 / 加速 / 减速”，正反摇分别保存时间曲线，未实测部分标待校准。入口 `run_jump_rope_stage_clock_library_judgment.cmd` 只判断；审阅页 `runtime/jump-rope/frame-review/stage-clock-library-review/index.html` 明确区分活动模板与候选。加速选择仍有错误，不替换 A/G。分析见 `docs/jump-rope/reports/stage-clock-library-20261005.md`。
