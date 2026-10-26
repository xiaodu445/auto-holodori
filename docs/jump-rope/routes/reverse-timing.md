# 独立反摇时间模板（2026-10-05）

用户指出：反摇的发力点在后半程，前慢后快，不能直接将正摇的时间序列倒放。旧实现使用正摇录像按时间采样的空间图集，再以phase -= speed*dt沿图集回放，因此继承了相反的圈内速度分布。此前把反摇错误当成平均挡位偏慢，整体加速并不能解决圈内节奏问题。

## 新表示

圆周每档仍有正时钟速度（整圈周期）；反摇另外使用独立的单调时间映射W。以落地为锚点，时钟进度u递增，图集位置为anchor-W(u)，位置速度为-clock_rate*W'(u)，加速度为-clock_rate²*W''(u)。前半程和后半程的速度可以不同，不依赖把正摇倒放或调大整个档位。正摇、低空模板保留。

识别到的位置反解为时钟误差，再进行有限修正；不能把图集相位差直接当成时间差。初次获取、遮挡退出重获取也做相同转换。低空与圆周切换仍在原落地锚点；各档周期调整独立于W。反解使用单调查表，不在热循环做42轮二分。默认配置没有reverse_time_profile，因此旧G输出逐帧保持一致。

## 独立数据

生成器build_jump_rope_reverse_time.py只做离线全图集局部灰度边缘/条状/运动证据匹配，不读取跟踪器的预测位置或速度。96个图集位置用反向连续路径动态规划选链（软速度先验0.8、最大步长4*dt+0.02），再拟合正导数的周期谐波时间形状。数据在runtime/jump-rope/reverse-time/samples.json与fit.json。它依然是CV推断，不是人工真值；公共空间图集正确这一假设尚未独立验证。

24.5～28秒用于拟合：整圈约0.755圈/秒，a=-0.0609、b=-0.3225；65～68、68～71秒独立拟合b=-0.3588/-0.3999，也支持前慢后快。第一模板半周期仅覆盖约39.7%的图集路径，其后半周期覆盖约60.3%；这不是引擎的精确比例。训练段角度残差RMSE约0.0201圈，后两段约0.0337/0.0236圈。28～31.5秒误差约0.098圈、匹配不可靠，不拿来改模板或声称有效留出验证。

数据reverse_time_v1.json保留verified=false。第一段形状用于公共反摇模板，不混合后两段来提高训练分数。速度上下界仍受挡位约束。

## 路线与验证

分阶段接入试验配置jump_rope_reverse_timing_config.json，报告在frame-review/reverse-timing：完整4010帧，32秒几何误差57.90px，比前一试验更差。独立匹配窗口24.5～28秒的跟踪相位中位差也从约0.0585升至0.2585圈。不能以接受观测1535帧声称成功；状态确认/选档和时间映射之间仍有接入问题。

另有只在原G增加反摇时间映射的对照配置jump_rope_reverse_timing_gear_config.json，保留旧G其他规则，便于隔离接入问题。最终结果写在下方追加记录；不替换原G默认入口。

459项测试通过：前慢后快、正导数、位置与时钟跨圈反解、获取位置一致、解析速度/加速度、遮挡时正时钟续推、正摇与旧配置不变、快速反解误差及非法模板拒绝。旧G4010帧四项核心输出与此前完全相同。没有发送任何游戏按键。

## 复现

设置PYTHONPATH=src、PYTHONUTF8=1，使用.conda/python.exe运行模块：

- modular_agent.realtime.build_jump_rope_reverse_time：独立匹配和拟合。
- modular_agent.realtime.validate_jump_rope_phase --gear --no-video --gear-settings domains/hololive_dreams/models/jump_rope/jump_rope_reverse_timing_gear_config.json --output-dir runtime/jump-rope/frame-review/reverse-timing-gear
- modular_agent.realtime.export_jump_rope_review --replay runtime/jump-rope/frame-review/reverse-timing-gear/replay.json --output runtime/jump-rope/frame-review/reverse-timing-gear --settings runtime/jump-rope/frame-review/reverse-timing-gear/settings-used.json

旧图片不覆盖。人工审查应分开标注“位置是否正确”“圈内加速点是否正确”“平均周期是否正确”“何时确认方向/速度”，不要再把这些问题混成一个速度挡位问题。


G隔离试验（reverse-timing-gear）第一段24.5～28秒，相对于独立CV匹配位置中位差约0.01374圈。这个窗口匹配不是人工真值；不能推导整场准确率。1178帧整圈clock_rate约0.7751，此刻位置速度约-0.9662，说明独立圈内节奏已实际参与回放。该试验32秒约12px，55秒约33.50px；尾部低空退出仍失配，不能仅以第一段改善升级默认路线。另一对照启用既有swing_boundary_by_branch，在reverse-timing-boundary单独保存，旧试验不覆盖。


边界对照32秒改善到9.41px，但55秒仍33.50px、尾部仍迟出，因此不采用边界对照作为新入口。run_jump_rope_reverse_timing_judgment.cmd仅加载G独立反摇时间配置，输出对应reverse-timing-gear。原G第一反摇窗口独立匹配中位差0.11285圈，独立反摇时间对照约0.01374圈；仅说明该开发片段改善。整场仍未胜过基线，原入口保留。新逐帧页仅标注已启用的参数，不伪造G没有运行的阶段识别。
