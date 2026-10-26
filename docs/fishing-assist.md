# 钓鱼辅助实时组件（0.1.0）

用户于2026-10-02确认：TAP!出现后左键响应；持续按左键黄色滑块上升，松开下降，有惯性，高速触边反弹；蓝色鱼需位于黄色滑块内。左键任何位置有效，不需要Alt。抛竿、换饵、图鉴、领奖和成功失败判断由其他模块负责。

## 使用顺序

1. 离线截图：`run_fishing.cmd --image domains/hololive_dreams/data/fishing_samples/control.png --title-bar 44`
2. 离线视频：`run_fishing.cmd --replay <视频路径> --phase control`。包含窗口标题栏时指定实际`--title-bar`。按视频FPS推进模拟时间，绝不发送输入。输出局部标注图及observations.json到runtime/fishing/replay。
3. 手动进入游戏钓鱼轨道后，运行`run_fishing.cmd`，默认control且只判断不输入。默认留3秒供你切回游戏，可用`--start-delay`调整；运行期间保持游戏前台。
4. 确认识别后运行`run_fishing.cmd --live`启用实机。想从等待鱼咬钩开始：`run_fishing.cmd --phase waiting --live`。用户自行抛竿后组件等待局部TAP!，发送一次左键按下/松开，等待轨道。默认不自动抛竿、不循环重开。

不要与正在操作的Agent或其他组件并行运行。F12停止live会话；Ctrl+C停止命令行。默认180秒总超时。原操作接口30秒连续持键保护保留；达到保护会停止并释放，未放宽，也不通过重复按下绕过。

## 调整入口

编辑domains/hololive_dreams/models/fishing_config.json，下一次启动生效；也可用`--config <文件>`指定独立配置。

| 参数 | 含义与调整方向 |
| --- | --- |
| lookahead_seconds | 默认0.12秒。上升过冲时可增加，太早松手则减少；不是实测惯性常数 |
| velocity_samples / velocity_alpha | 速度估计样本数和新估计权重；权重越高反应越快，也更易受噪声影响 |
| inside_margin | 黄色条高度比例的中心容忍区，默认0.18；增加可减少切换 |
| minimum_hold | 默认0.035秒，限制普通按下/松开切换；停止与丢失释放不受限制 |
| edge_margin / edge_speed | 接近上下边界且速度较高时提前制动；坐标与速度均按轨道局部高度归一化 |
| max_speed | 速度估计限幅，单位轨道高度/秒 |
| short_loss_seconds / long_loss_seconds | 默认0.10/0.8秒；短暂丢失保留输入，超过短阈值释放，超过长阈值停止交还 |
| control_roi / bite_roi | 游戏客户区相对坐标[left,top,right,bottom]，不是桌面坐标；默认按用户截图校准 |
| yellow_hsv / fish_hsv | OpenCV HSV上下限；颜色、轮廓面积、宽度、位置与尺寸过滤 |
| fps | 目标60；不是已验证性能 |

当前默认control_mode=bang_bang；PWM因用户实机反馈停用，保留为可选实验模式。PWM模式使用位置误差和速度反馈计算占空比，lookahead_seconds与inside_margin只影响旧bang_bang模式。

黄色条中心通过横向对齐的剩余片段上下端点合并估计；完全遮挡或多候选不猜测。速度采用近期位置差和时间差平滑，不训练神经网络。边界制动是启发式规则，尚未拟合真实反弹物理。窗口平移更新客户区原点并重置速度；尺寸变化停止，避免缩放引起坐标误判。失焦、最小化、窗口关闭、区域超屏、异常均退出并尝试释放。

## 接口与目录

共享WindowCapture、InputLatch、run_loop位于src/modular_agent/realtime/runtime.py；只进行局部MSS采集，无OCR/UIA/全屏模板匹配，统计缓存最多600轮。

领域fishing_vision.py与fishing_controller.py分别保存识别及预测控制，fishing.py保存waiting→hook→control状态机。CLI及调用桥接位于src/modular_agent/realtime/fishing.py。顶层可在人工进入轨道后调用use_skill fishing_assist；执行器full复核前台游戏，再用局部CV验证轨道，独占运行后返回。原启动、猜高低及默认full观察行为保留。顶层等待阶段暂不自动接管；独立CLI支持waiting。

Python：`run_fishing(root, computer, handle, live=True, should_yield=..., progress=...)`，调用者负责串行独占，既有持键/鼠标按钮必须先释放。传入live=False仅判断。顶层不会参与每帧决策。

返回outcome始终unknown、verified=False。轨道长期丢失返回track_lost_result_pending；收尾模块应重新观察后明确判断成功/失败/未知，不因消失直接确认成功。当前尚未实现换饵、图鉴、领奖收尾组件。

runtime/fishing/last-result.json记录实际FPS、采集/识别/控制/输入平均耗时及最近600轮识别和决策；均值只覆盖缓存窗口，FPS覆盖整个运行。输入耗时包含变更时的操作审计写盘；无输入帧只测状态锁存开销。

## 验证范围

两张真实截图验证轨道、鱼遮挡的条片段合并与TAP!识别，0.75/1/1.5倍缩放静态图已测试；另测试预测制动、丢失、单次上钩输入、状态变更派发、取消与异常释放、配置拒绝。未做真实视频动态回放、实机只判断或实机输入验证，不能据此宣称稳定钓鱼或60FPS。

全量回归：189项测试通过（含9项钓鱼测试）；未发送真实游戏输入。


## 点按/PWM控制更新

曾针对忽上忽下加入PWM，后因用户反馈升降效果不佳恢复bang_bang默认。以下为实验PWM参数说明。每160ms一个周期，悬停起始占空比50%，即约80ms按住、80ms松开。根据位置与速度在25%到75%之间调整，周期内固定占空比，避免误差波动产生额外点击。真实时间精度由循环频率与输入耗时决定；这些初始数值未实机调校。

- pwm_hover_duty：平衡占空比。整体往上跑就降低（如0.45），整体往下掉就提高（如0.55）。
- pwm_position_gain：位置修正力度，默认1.5；仍大幅摆动可降低至1.0。
- pwm_velocity_gain：速度制动力度，默认0.25；升降太快可适当增加，过强可能产生反复修正。
- pwm_period_seconds：周期，默认0.16秒。缩短会更细碎，但必须满足最短保持和至少两帧的按下/释放时间；过快配置会被拒绝。
- pwm_min_duty / pwm_max_duty：普通控制占空比上下限，默认0.25/0.75；边界制动仍可覆盖脉冲请求。

重启组件后生效。记录中增加duty（本轮期望占空比）与cycle_duty（当前周期执行占空比），方便比较调参。自动测试覆盖悬停脉冲、速度反馈方向、周期内占空比固定、真实操作接口的独立释放和过快配置拒绝；尚未验证实机平稳性。

## 提前惯性制动

默认bang_bang增加inertia_braking=true：根据与鱼的距离设定接近速度，越接近鱼允许的速度越低。实际上升速度过快时提前松开，下降速度过快时提前按住，即使鱼仍在黄色条内也会制动；仍通过按下/释放操作，不使用PWM。保留最短保持、边界保护及停止释放。

approach_seconds默认0.25，增大可让接近更缓慢；approach_max_speed默认0.6（局部轨道高度/秒），减小可限制接近速度；velocity_deadband默认0.08，防止速度噪声频繁切换。修改后重启；inertia_braking=false可恢复前一版本预测控制。旧自定义配置缺少该开关时保持旧行为。

日志增加target_velocity和braking。合成惯性/重力/反弹模型中，与原控制相比稳态平均误差从约0.046降至0.015轨道高度、峰值从约0.126降至0.024；此模型不代表游戏真实物理，不是实机成绩。真实效果仍需用户验证。
