# 小地图定位与刷新点巡逻框架

当前显式路线执行：在 `navigation_editor.cmd` 规划后点击“仅W + 转镜头自动行走 / 跳跃”，读取完整镜头标定，停稳转向后只按W前进；不发送A/S/D，跳跃用W+Space。F12停止。详见[自动行走与跳跃](navigation-editor.md#自动行走与跳跃)。下文旧WASD框架仅保留离线/被动建议；未接自动拾取，W+镜头完整路线尚未实机验证。

不需要现成全图的替代方案已加入：[边走边扫描小地图建图](minimap-mapping.md)。入口 `minimap_scan.cmd`（手动走动只读建图）和 `minimap_explore.cmd`（显式开启短步自动探索）；生成的 `patrol-config.json` 可接本页定位预览。实机效果待验证。

2026-10-25。接入现有 Game_agent 源码及公共交互协议，独立入口 `patrol.cmd`，未修改每日计划和现有 GUI。用户确认小地图不旋转；世界坐标采用参考地图像素，左上为原点，X向右、Y向下。当前是离线诊断、手动路线编辑、被动实时预览与控制器框架，不是已经实机验证的自动拾取成品。

## 已有组件

- `src/modular_agent/domains/hololive_dreams/patrol_vision.py`：截取客户区小地图；圆形内圈、角色中心及青色动态标记遮罩；模糊 Lab 色彩布局、多尺度模板相关；全图首定位、时序范围跟踪；分数/竞争峰差/不合理位移/两帧确认。不读取游戏内存。分数不是概率。
- `src/modular_agent/domains/hololive_dreams/patrol.py`：独立 WASD 位移标定、短脉冲闭环控制、路线点/圈数预算、卡住/超时、拾取提示两帧/启用检测/三次有界重试；场景或弹层变化后禁止补旧 E。到点与拾取结果分开计数。
- 同文件 `astar()`：以人工核对的白色可行走遮罩寻路；侵蚀留出角色净空、四方向网格避免切角。地图的路面颜色本身不能证明没有障碍。
- `src/modular_agent/realtime/patrol.py`：离线图诊断、实时被动预览、路线编辑、遮罩寻路、标定文件转换；可选加载标定进行影子决策，只有日志，不发送输入。`GuardedPulseExecutor` 供后续接入，输入前/期间/后检查、过期拒绝、异常松键；本版 CLI 不构造输入执行器。
- `patrol_movement=realtime` 与 `patrol_pickup=claim` 已登记，拾取复用 `RetryBudget`。移动不继承菜单盲重试。

## 为什么先用固定视角 WASD

小地图方向固定，使地图位置误差容易直接反馈。固定摄像机后分别测 W/A/S/D 的地图位移向量，即使镜头和北向不对齐，也能选出减少位置误差的键，每次最多 150ms，再等待新帧纠偏。第一版只用独立实测的单键，不假定斜走速度或对向键完全对称。

角色自身转身通常不妨碍这一方案，但摄像机自动跟随/自动回正是否改变 WASD 方向仍需实测。若四键位移不能覆盖整张平面，标定会拒绝，不能强行猜方向。后续可比较转镜头+W：它需要额外标定鼠标转角和镜头回正，当前缺少这些样本，因此未实现该控制模式。

## 资源与来源

`domains/hololive_dreams/data/patrol/references/` 保存用户的四张原图，分别为 `free-world.png`、`map-partial.png`、`drop-map.png`、`pickup.png`。运行不依赖 Temp 剪贴板路径。`pickup-key.png`、`pickup-text.png` 来自第四张图的 E 与拾取局部；无 OCR。

`drop-map.png` 暂作参考，图标密集且并非已核验的完整无标记底图，`reference_reviewed=false`。`drop-candidates.json` 提取109个青色标记候选，可能包含设施图标，全部 `reviewed=false`；不自动导入路线、不代表109个真实掉落物。路线初始为空，避免编造可行走路线。

默认小地图 ROI 根据1260×709客户区估计，圆心(143,127)，半径82；随客户区宽度缩放，其他宽高比可能需调整。离线 `--decorated` 只针对这批截图去掉38像素标题栏；实时截图直接使用客户区。

## 使用

在 Game_agent 目录终端运行：

```bat
rem 被动预览：5秒后手动切回游戏；不会移动或按E
patrol.cmd preview

rem 静态截图诊断，不会把同一张图伪装为两帧定位确认
patrol.cmd offline --image domains/hololive_dreams/data/patrol/references/pickup.png --decorated

rem 手动布路线：左键添加，右键撤销，S保存，Q退出
patrol.cmd edit-route

rem 白色为可走、黑色为障碍；遮罩必须与参考图同尺寸
patrol.cmd plan-route --walk-mask path/to/walk-mask.png --cell 8 --clearance 6

rem 实测后照示例结构填写，示例中的数值不能当作实测
patrol.cmd calibrate --samples path/to/measured-samples.json

rem 加载实测向量，记录影子控制建议；仍不输入
patrol.cmd preview --motion-calibration path/to/motion-calibration.json
```

输出在 `runtime/patrol/时间戳/`：地图叠图、小地图裁剪与遮罩、观察 JSON/JSONL、停止原因。预览 F12、失焦、遮挡、窗口移动缩放、Ctrl+C 或 `--stop-file` 停止。预览窗口应放在游戏外并且不要点击它，点击会使游戏失焦，按既有守卫停止。默认20分钟预览，总时长可显式调整。

## 验证与剩余接线

`tests/test_patrol.py` 覆盖已知位置、多尺度、遮罩、重复地图结构、空白、过期帧、突跳、无标定、卡住、路线预算、A*障碍/净空、吞输入、延迟启用、延迟弹层、置灰、取消/失焦和异常松键。提供的自由图中拾取阴性、拾取图阳性、灰度图禁用通过。静态原图匹配仅是局部样本验证，不能证明全图精度。

本轮40项新增离线测试通过，包括模拟四边形巡逻闭环。`tools/patrol_report.py` 可复现静态诊断，保存至 `runtime/patrol/reference-check/`：自由图候选(550,480)，拾取图候选(606,452)，参考图/小地图尺度2.0，相似度约0.703。仅单帧所以报告仍为 `confirming_location`。本机全图首次搜索约262～272ms，重复静态图的局部跟踪中位约71～73ms；后者只测运行耗时，不是连续实机定位准确率。尚未运行真实游戏预览或发送巡逻输入。

真正实机自动巡逻还需要：完整干净地图；可行走遮罩与核对后的刷新点/路线；固定镜头 WASD 实测；自由页/未知弹层的可靠语义守卫接入；拾取结果独立检测；真实移动录像验证定位与速度。当前 `pickup_result` 为外部证据接口，没有假造结果检测。影子预览用定位可用作为场景假设，只用于预览，不能直接升级成实机输入依据。

初版卡住只停下并保存信息，没有未经验证的随机后退/跳跃/转镜头脱困。断定位不沿最后方向盲走。瞬移/地图切换后应重新启动定位器，当前不会用突跳强行更新坐标。
