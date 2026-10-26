# 本地识别接口

2026-10-02 更新。GeneralVision 只读本地截图，输出结构化信息，不调用大模型、不上传图片、不操作键鼠。旧 observe/analyze 调用兼容；顶层和现有决策树仍使用完整 full，未自动改成快速模式。

## 独立开关与单次配置

```python
from modular_agent.perception import GeneralVision
vision = GeneralVision.for_project(project_root, "hololive_dreams")
try:
    report = vision.observe(
        window_handle=game_handle,
        enable_ocr=True, enable_uia=False, enable_cv_buttons=False,
        enable_knowledge=True,
        template_names=["map2", "smallgame"],
        template_scales=[1.0], template_threshold=0.65,
        region=[100, 200, 900, 500],
    )
finally:
    vision.close()
```

| 参数 | 含义 |
|---|---|
| enable_ocr / enable_uia / enable_cv_buttons / enable_knowledge | bool；None 继承实例配置。各阶段独立关闭 |
| window_handle | 本次可见窗口句柄；裁剪到窗口与屏幕交集 |
| region | 桌面物理像素 x,y,width,height；Python 也接受 Rect 或同名四字段 dict |
| ocr_max_side | 64..8192；None 保留 OCR 实例默认1600，不强制降低分辨率 |
| template_names | 指定模板名字，匹配前过滤；None 扫全部，空列表不匹配任何模板 |
| template_scales | 1..16 个0.25..4的缩放值；None 继承匹配器设置 |
| template_threshold | 单次阈值覆盖，0..1且不含0；不会修改注册文件 |
| prefer_templates | 旧兼容选项，默认False；True且模板命中可跳过OCR，现有 full 不启用 |

区域坐标不是窗口相对坐标，也不是 left,top,right,bottom。超出已捕获范围时裁剪取交集，完全不相交报 ValueError。负坐标适用于多屏；所有返回位置仍是桌面物理像素。observe 中先窗口裁剪，再区域裁剪；analyze(image, origin=..., region=...) 可离线处理同样的区域参数。

## 主动搜索

```python
result = vision.find_text(["移动", "继续"], mode="contains", window_handle=game_handle)
result = vision.find_text("猜高低", mode="exact", min_confidence=0.7, region=[100, 200, 900, 500])
result = vision.find_templates(["map2", "smallgame"], template_scales=[1.0], window_handle=game_handle)
result = vision.wait_for("text", ["活动", "游戏", "演出", "任务"],
                         require_all=True, stable_count=2, timeout=30,
                         interval=0.5, cancelled=lambda:computer.stopped,
                         window_handle=game_handle)
```

find_text 仅运行 OCR：NFKC标准化、忽略空白与大小写，支持 exact/contains，保留当前文字位置和 query 关联。它仍需要对搜索区域做 OCR，不是免费的字符串检测。find_templates 只运行指定模板匹配，不运行OCR/UIA/形状候选。两者返回 found、matches、frame、observed_at、capabilities、warnings、timings_ms；找不到不等于后台识别成功，应同时检查 capabilities。未知模板名返回空命中，不猜测替代模板。

wait_for 的 kind 是 text/template；query 是字符串或列表。require_all 要求全部目标，stable_count 要求连续1..10轮目标及量化位置稳定，忽略临时ID与微小置信度变化。每轮重新截图，不复用历史目标。timeout 为0..300秒（0单次检查），interval为0.1..30秒；超过时限不再开启新识别。正在执行的本地识别不能中途强杀，因此返回时间可超过名义超时一轮识别耗时。等待不发送键鼠，不点击，也不自动切换窗口。

状态为 matched / timeout / cancelled；last_result 保留最后一轮能力与错误信息。Python 可提供 cancelled；轮询睡眠分为短片段。MCP 客户端取消会设置取消事件，在当前识别结束或等待片段后退出。

## 缓存、并发与扩展

模板注册、解码、缩放缓存保留；指定模板跳过其余模板的解码与匹配。OCR 仅复用完全相同像素/区域原点/尺寸/置信度设置的结果，并返回副本，避免文字关联污染。注册和图片变更按文件时间与大小刷新。不跨帧复用目标坐标。

GeneralVision 用可重入锁串行保护 observe/analyze/warmup/close，单次参数不改变长期配置。wait_for 的轮询间隔不占锁；MCP 的识别在工作线程执行，避免阻塞服务事件循环。close 可重复调用，关闭后识别明确报错。外部自定义后端通过 ocr.recognize、desktop.windows/controls、knowledge.match 注入；使用新增模板筛选选项时后端需要支持相应关键字参数，不静默退回全库识别。

参数先校验再截图；单阶段运行失败记录为 failed 和 warnings，保留其他阶段结果。截图失败、无效区域/窗口、关闭实例会直接抛出错误。按钮形状仍是未经确认候选，文字关联不把它自动升级为真实按钮。

## 输出与性能

ScreenReport 字段不变：frame、windows、buttons、texts、knowledge_matches、capabilities、warnings、timings_ms、observed_at。frame 添加本次区域/模板选项元数据；对应 schema 在 docs/schemas/screen-report.schema.json。坐标形式为 x,y,width,height 及 bbox。

性能优化应从当前状态所需区域和目标集合入手，不必裁减识别输出。例如启动只查文字，地图只匹配 map2/smallgame。完整识别依然保留。尚不能承诺30FPS通用OCR；合成基准也不等于实机游戏延迟。

## MCP

`.conda/python.exe -m modular_agent.perception.mcp_server --project-root . --domain hololive_dreams` 提供 observe_screen、find_text、find_templates、wait_for。observe_screen 开放独立开关、区域、模板名单、缩放、阈值；MCP region 固定为 [x,y,width,height]。全部只返回JSON，图片留本地。示例配置见 config/vision-mcp.example.json；客户端注册仍需按使用环境设置。

## 验证与限制

状态接口兼容性、区域坐标/裁剪、禁用阶段零调用、指定模板跳过工作、配置不被覆盖、参数拒绝、等待超时/取消与稳定条件、MCP工具暴露由 tests/test_perception_queries.py 和 tests/test_vision_mcp.py 验证。通用文字识别仍可能漏字，模板可能误匹配；降低阈值不会提高OCR召回。遮挡游戏像素无法恢复，本模块只截可见桌面。

离线合成基准（2026-10-02）：640×360、8模板、3缩放，预热后3次中位数，全库约207ms，指定单模板约22ms；只衡量模板阶段，不能外推游戏OCR或端到端FPS。结果保存在 runtime/perception-query-benchmark.json。

2026-10-03：按用户要求，现有注册模板、启动匹配、钓鱼上钩模板、跳绳角色模板均降到0.5；新建/导入模板默认0.65。单次显式阈值覆盖仍有效；OCR置信度及非模板控制参数不变。降低匹配阈值不解决缩放适配，可能增加误匹配。

2026-10-03：用户要求所有模板阈值统一调整为0.65，覆盖此前0.5配置，包含强欲之牌及新建/导入默认值。

2026-10-03：1208×724用户地图截图smallgame约0.85倍。原完整观察五档最佳约0.43；0.85倍约0.958。完整及精简观察缩放列表补充0.85，阈值仍0.65。入口逻辑不变，此修复尚非任意窗口尺寸自适应。截图保存为data/template_sources/samples/smallgame_map_085.png，供回归且不导入模板库。

2026-10-03：用户针对Q点数0.632未通过问题，要求强欲之牌玩法组件阈值恢复0.5（点数、花色、鬼牌、玩法按钮）；其他模板仍0.65。实图guess_q_20261003.png用于Q♦回归。


2026-10-05 音画后续校准：新机位独立空间图集及六组实测正反摇候选时钟已保存；声音区间等待人工标注，离线频谱/DTW 导入工具不控制输入。旧 A/G 入口保持。试听页 runtime/jump-rope/audio-calibration/index.html；验证边界和导入步骤见 [校准报告](jump-rope/reports/audio-calibration-20261005.md)。

2026-10-06：KnowledgeMatcher保留PNG透明通道，用alpha非零像素参与遮罩匹配；JSON可设置mask_mode=warm_ui，仅为启动menu/stage/task启用亮色暖色图形与白色文字遮罩，背景不参与相关系数。其他模板默认none。透明图不能全透明；遮罩至少16像素。遮罩匹配分数仍需实图验证，非通用自动抠图；颜色变化或浅色背景误纳入可能需要手工透明PNG。每日任务13张模板已导入，流程尚未接通。
