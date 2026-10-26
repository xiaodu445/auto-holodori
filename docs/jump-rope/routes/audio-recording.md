# 音画和人工空格采集

双击项目根目录 record_jump_rope.cmd。默认5分钟，3秒后自动切回游戏，F12、Ctrl+C、切走游戏停止。程序只观察人工空格，不发送输入。保留跳绳现有默认自动入口及分支规则。

录制前确认游戏声音打开，游戏使用Windows默认扬声器/耳机输出；关闭其他发声应用和通知。本实现采集所选输出设备上全部声音，不采集麦克风，也尚不是仅限游戏进程的音频。默认设备回环已能枚举，但实机音画录制仍需用户验收。

推荐先录10秒有游戏声音的短片，确认结束信息“样本帧”大于0、“峰值”大于0、错误为空，再正式录制。参数 --duration 10 可覆盖默认；--list-audio-devices 列出设备，--audio-device N 选择对应loopback索引；--no-audio 可恢复旧无音频录制。

请尽量包含连续普通正摇、反摇、低空，以及各阶段技能语音到其结束后的完整过程。按短空格人工跳跃，允许失误；不需要刻意保持固定跳跃节奏。为了拟合发力点，请保留每段至少数个完整周期及切换前后画面。建议从计数较低开始，录到较高阶段，结束后提供整个录制目录。

## 保存文件

runtime/jump-rope/recordings/时间目录下：screen.avi（画面）、timestamps.json（每个原始帧的单调时间）、inputs.json（人工空格边沿）、audio.wav（原采样率16-bit多声道PCM）、audio-timestamps.jsonl（每块样本位置/采集时间/设备状态）、summary.json（音视频帧数、静音峰值、设备与错误）。请保留全部文件，而不只提供avi。

音频回调独立线程，写盘由有界队列后台完成，不在视觉循环中阻塞录音。音频队列溢出明确停止并报错，不静默丢失样本；video仍按旧实现优先最新帧，丢帧留记录。WASAPI/PortAudio ADC时钟在回调时映射到共同time.perf_counter原点；设备不提供可用ADC时间时，标为callback_duration_estimate，未宣称绝对音画零误差。每块状态标记保存，可用来识别丢音、间隙和时间不确定性。

AVI名义帧率不等于实际采集帧率，WAV连续样本也可能与设备时戳存在间隙；离线拟合必须使用两份原始时间戳对齐，不能直接把AVI播放器时间当真。当前没有合并音视频或语音技能分类，本轮只负责采集。

依赖：PyAudioWPatch==0.2.12.8，已安装本项目.conda环境。新环境可安装项目recording可选依赖。参考官方PyAudioWPatch WASAPI回环示例：https://github.com/s0d3s/PyAudioWPatch/blob/master/examples/pawp_record_wasapi_loopback.py。

测试覆盖共享时钟映射、缺失ADC时间明确标记、后台PCM写入/样本索引/状态记录/关闭资源；设备只做枚举检查，没有自动录下用户桌面声音。
