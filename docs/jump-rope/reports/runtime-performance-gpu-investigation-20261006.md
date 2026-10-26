# 实时性能与GPU加速调查（2026-10-06）

用户决定暂不实施加速，先测试当前版本是否够用。本轮仅保留调查记录；没有安装GPU依赖、替换捕获后端、迁移识别运算或更改实测入口。

## 本机与当前实现

通过Windows显卡注册信息读到NVIDIA GeForce RTX 3060 Laptop GPU，另有GameViewer Virtual Display Adapter。当前OpenCV版本为5.0.0，cv2.cuda.getCudaEnabledDeviceCount()返回0：当前环境没有可用的OpenCV CUDA后端，不能据此说本机没有GPU。OpenCV构建信息显示OpenCL支持（NVD3D11），当前代码使用普通NumPy数组，并没有验证或启用这条GPU路径。环境中未安装dxcam和torch。

当前捕获在src/modular_agent/realtime/runtime.py：mss抓取游戏窗口ROI，转为CPU NumPy BGR数组并复制，保留前台、窗口几何、桌面边界和F12检查。识别在domains/hololive_dreams/models/jump_rope/jump_rope_phase_gear.py及jump_rope_phase_state.py：CPU侧缩放、灰度、边缘与距离变换、模板采样和候选证据比较。不能仅设置一个CUDA开关就迁移整个识别过程。

## 最近实测证据

2026-10-06 10:34左右结束的会话：2779帧，运行约67.66秒，平均41.07 FPS，实际44次短按请求。平均捕获10.63ms、识别11.08ms、控制0.072ms、预览提交0.122ms。最近600帧的帧间隔中位数23.28ms，P95为43.84ms，P99为65.81ms，最大89.19ms。上述均为该次实机记录，不能外推到所有窗口大小、模式和后台负载。

音频记录没有报错，未丢匹配窗口；阶段2–3已有加速声音候选，但模型仍出现正常/加速间反复跳档。一次强加速匹配的距离约0.172、类别差距约0.193，仍伴随选择正常档的帧。没有同步原始画面，无法确定每次真实档位；这说明选档规则也需调查，不能将错误全部归因于帧率。短时帧间隔波动可能拖慢变速证据积累。

原会话证据见runtime/jump-rope/sessions中的独立会话记录；last-result.json会被下一次实测覆盖。此文记录的会话路径：F:\Codex\Game_agent\runtime\jump-rope\sessions\1791254045141249000.json。

## 可供以后实验的方向

1. 先拆分捕获耗时，比较当前mss与DXGI桌面复制路径。DXGI提供GPU中的桌面图像，但交给CPU识别时仍有读回、复制与同步成本；更换后端是否更快需本机同场景实测。
2. 对识别热点逐项测量，检查模板采样和数组临时分配、重复计算、音频后台竞争；优化时保留同一输入下的模式、速度和曲线回归检查。
3. 再做整段GPU识别实验。需要合适的CUDA/OpenCL实现，尽量让批量运算数据留在GPU；小操作逐项上传下载不保证提速。当前未测量GPU方案，不能承诺具体FPS或延迟收益。

任何性能方案都不能代替速度档位选择规则的正确性检查。目前保持现有版本，让用户先判断它能否满足实测。

## 官方资料

- [Microsoft Desktop Duplication API](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/desktop-dup-api)：DXGI桌面图像表面及GPU处理路径。
- [OpenCV CUDA](https://opencv.org/platforms/cuda/)：CUDA运算支持，需要配套实现与可用构建。
