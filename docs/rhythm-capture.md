# DXGI截图优化

双击run_rhythm_dxcam_preview.cmd运行DXcam实机预览（720宽分析）。旧启动器默认
auto优先DXcam，初始化失败时显示原因并回退MSS。可附加--capture mss对照。
DXcam显式入口失败就报错，不静默变成MSS。当前支持游戏完整位于主显示器，
窗口移动、失焦、F12仍由现有窗口守卫及输入调度检查处理。

DXcam 0.3.0已安装在项目.conda，pyproject新增可选capture依赖，不要求CUDA。
新适配器逐次获取DXGI最新帧，使用copy=True确保图像内存归当前处理所有。
不启动内部录像队列，也不回放cached frame。没有新桌面帧则跳过识别，游戏区域
CRC32相同也跳过。日志capture_stats区分polls/new_desktop_frames/no_new_frame/
region_duplicates。桌面更新或CRC变化不等于游戏逻辑/渲染的新帧。

抓取时刻采用API调用区间中点，仅为时间估计，不冒充DXGI展示时间戳。
低帧率/静止时旧观测超过220ms会停止历史输入并松键。预览关闭同样停止。

只读基准：1280×720桌面区域，每后端2秒；MSS中位9.75ms、P95 14.10ms；
DXcam中位1.15ms、P95 1.96ms。数据为runtime/rhythm/capture-benchmark.json。
不包含音符识别/输入，不是实机歌曲FPS或Perfect保证；两次顺序测量画面变化率
不同，不能将changed_region_fps直接作为库性能比较。

初测出现comtypes释放警告。源码确认dxcam0.3.0对部分COM指针显式Release后
又由Python所有者析构Release。本地适配器对该版本的显式释放补足对应引用，
不改动第三方库。复测完整释放未出现访问异常；其他版本走普通release。

只读基准命令（项目目录，先设置PYTHONPATH=src）：

    .conda\python.exe tools\benchmark_rhythm_capture.py --seconds 3 --output runtime/rhythm/capture-benchmark.json

该命令不发送输入、不保存图像，仅输出数值。当前共20项音游相关测试通过。
