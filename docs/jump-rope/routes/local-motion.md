# A：局部轨迹自动路线 v6

状态：现有主要自动路线。用户实机确认普通场景能稳定跳跃，不能泛化为全部技能零失误。没有接入新阶段模型。

代码：`domains/hololive_dreams/models/jump_rope/jump_rope.py` 的TrajectoryMotionVision/Controller；基础视觉/控制是jump_rope_vision.py、jump_rope_controller.py；片段补全是jump_rope_fragments.py。jump_rope_local_motion.py中的小ROI Hough方案属于早期试验，当前local入口并非直接使用它。

参数：jump_rope_config.json。ROI由local_motion_components设为[.475,.03,.655,.68]；颜色为快速路径，灰度运动片段为备用；跟踪中央箭头/角色。普通与低空使用不同触发路径，低空调slow_arrival.lead_seconds（当前0.10）、danger_y（0.57）和rearm_distance（0.015）。低空候选有锁存，不再仅靠瞬时低速度切模式。

运行：run_jump_rope_local_motion_judgment.cmd只判断；run_jump_rope_local_motion.cmd加--experimental-live，35ms按下/明确释放、等落地再跳。实验延迟60ms和滞空200ms未实测，calibration.verified=false。失焦、窗口变化、F12和异常有共用保护与输入释放。

局部识别失败时预测只短时补偿，不能靠动画附近的运动无限续期；连续静止/不合理形状被拒绝。已有一侧片段补全最多借用120ms内两侧形状，不为新路线改变此限制。

证据：用户反馈普通稳定；旧离线报告trajectory-motion-v4-report.json、low-mode-v6-tail-replay.json。没有生命/计数自动核验，不能把触发次数当成功次数。下一步可以继续解决变色/背景/遮挡和低空双向经过；保持本路线独立，C若验证成功再通过明确适配接口接控制。
