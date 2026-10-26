# 轨迹与速度挡位 v4（C4，独立实验）

2026-10-04 长时离线改进。保留 A 自动、C1/C2/C3 和历史 C4；当前 C4 仍只判断。

## 启动与回退

双击项目根目录 `run_jump_rope_phase_gear_judgment.cmd`，或路线菜单按 G。显示曲线、速度、技能片段与重入许可，不发送空格。F12、Ctrl+C、失焦停止；视觉丢失首帧继续原模型播放。默认会话 180 秒，到时仍正常结束，不是因未识别到绳子而退出。

自动跳跃仍用 `run_jump_rope_local_motion.cmd`（A，35ms短按），这次未修改它。完整入口见 [索引](../README.md)。

快照：原 C4 为 `history/gear-v4-before-episode-lock/`；片段锁后为 `history/gear-v4-before-coherent-evidence/`；加入遮挡重入保护后为 `history/gear-v4-before-multiple-swing-gears/`。不自动加载快照。

## 保留的修正

只有已确认状态能生成后继。每次低空确认后清除旧分支、冻结进入方向，只能退出到相反整圈方向一次；整圈不能直接翻转。候选在模板脚下边界产生，0.75 秒未确认即过期，不递归产生后继。

新发现：退出后要求一整圈相邻可见行程，遮挡令累计停在 0.848 圈，阻止真实下一次低空。新增 `occlusion_tolerant_rearm=true`：至少播放一圈整圈时钟，同时在上半圈累计至少 0.08 圈实际相邻视觉行程，才允许重入。原一整圈可见行程条件仍保留。单点或时间流逝不足以解锁。这是工程保护，不是已证实的技能冷却。

低空退出优先要求两端支持；端点被遮挡时，可用一个已播放低空周期及持续整圈证据。漏检恢复接受与冻结进入方向相反的连续上半圈阶段证据。最终回放第4次退出使用了恢复分支，尚无独立录像验证。

丢失观测立即按原时钟推进；可信图像小幅回正。阶段修正及同路径替换跳跃限制为 0.008 周期和当帧推进量30%。模型时钟始终为正。低空投影速度可在端点归零，但模板加速度非零；二阶导数在时序节点不保证连续。不同状态接缝仍有误差，合法运动不等于跟对真实绳子。

## 校准与默认配置

独立颜色掩膜、受限二次曲线拟合、重复高度经过，得到低空周期约 **2.399、2.005、1.710秒**，对应 **0.41684、0.49881、0.58482往返周期/秒**。不是已证实的游戏内部档位。只使用实际覆盖的短间隔相邻样本夹住的经过，不外推遮挡高度。

永久点数据及配方在 `domains/hololive_dreams/data/jump_rope_samples/calibration/`；结果为 `domains/hololive_dreams/data/jump_rope_phase/swing_rates_v1.json`。中段黄色123点、后段蓝色104点可重提取；首段黄色84点保留原始点数据，原始提取流程未完整保存。

**默认暂保留第一个低空档，±8%校正。** 直接加入三个档位明显恶化：第一次慢摇选快档，退出和后续方向随之出错。正确样本不等于正确的在线档位选择。其余档位只在离线实验启用。

首段黄色生成21节点单调周期三次 Hermite 时序 φ=W(θ)，再由 q=(1−cos(2πφ))/2 播放有限路径。速度连续；加速度输出是常速模板解析值，不是图像实测，也不包含调速额外加速度。中段和蓝色段是否共用这个时序尚未验证。

普通中心仍为0.735、0.9475、1.07、1.4325圈/秒，±16%；来自整条模板独立窗口匹配。起始名义速度0.73。`speed_calibration.verified=false`，不是游戏真实最低/最高速度。

实时继续复用 C3 局部灰度边缘、细条、帧差、固定轨迹匹配。离线颜色采样不影响实时逻辑。没有每帧 OCR、UIA、大模型请求或生命/计数识别，画面消失不判成功。

## 最终验证

421测试通过，包括旧组件、输入释放、片段锁、一次反转、遮挡重入、正值时钟、端点加速度、夹区间校准、实验输出隔离。测试输入是模拟设备，未实机发送空格。

完整4010帧：1289帧接受视觉支持；8次切换，4进4出；11个稀疏状态点吻合。这是开发录像检查，不是100%准确率。第4次低空从旧基线76.676秒提前到74.972秒；75.5秒状态恢复正确。0.1秒密抽确认74秒仍为整圈，已修正此前标签误判。

无直接整圈翻转、错误退出方向、非正时钟或档位越界。2155个同假设纯播放检查误差为零；本次选择的时钟范围0.38349～1.2412，不代表游戏全局范围。见 `constraint-report.json`。

14/20/32/55秒曲线中位误差约 **6.14/5.95/31.26/37.16px**，32/55仍失配。C3对应约10.55/5.90/9.27/13.39px，不能宣称C4取代C3。加速选择、复杂背景和遮挡精度尚未解决。

CV平均9.19ms、P95 12.12ms，不含采集、预览、输入；实机60FPS未验证。`runtime/jump-rope/phase-gear/` 的 report、replay、2648帧30FPS annotated视频、final-manifest 对应最终默认配置。未做C4实机输入或999次验证。

## 复现与继续开发

[长时分析](../reports/c4-long-run-20261004.md) 保存原因、对照、下一步；[独立实验说明](../../../domains/hololive_dreams/models/experiments/README.md) 保存配方。失败方案不进入默认。

项目根目录设置 `PYTHONPATH=src`、`PYTHONUTF8=1`，使用 `.conda\python.exe`：

```text
-m modular_agent.realtime.extract_jump_rope_swing_samples
-m modular_agent.realtime.build_jump_rope_swing_rates
-m modular_agent.realtime.build_jump_rope_time_profile --output runtime/jump-rope/phase-gear/rebuilt-swing-time.json
-m modular_agent.realtime.validate_jump_rope_phase --gear
-m modular_agent.realtime.validate_jump_rope_gear_constraints
-m modular_agent.realtime.validate_jump_rope_gear_experiments --case baseline --case occlusion-rearm
```

验证器支持 `--output-dir`。实验各写独立目录；综合 comparison 保留全部已保存试验并使用最新人工标签统计，last-batch 只列最近批次。下一步优先独立连续曲线/切换标注，校准多档位的完整时序和接缝，避免以模型自身偏置的候选点证明其速度正确。
