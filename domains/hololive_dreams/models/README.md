# hololive Dreams 本地策略组件

## 按功能分类（2026-10-26）

| 目录 | 内容 |
| --- | --- |
| `fishing/` | 钓鱼状态机、识别器、控制器、循环和配置 |
| `greed_cards/` | 强欲之牌入口桥接、猜高低玩法与结算 |
| `jump_rope/` | 历史 CV／轨迹跳绳实现、各路线配置和路线索引；离线实验在 `experiments/` |
| `rhythm/` | 六轨音游引擎与配置 |

各玩法的源码与配置放在同一目录，避免顶层平铺。根目录 `.cmd` 入口、GUI、共享加载器、回放和发布脚本已使用分类后的路径；不在旧位置留重复副本。直接引用旧源码或配置路径的外部脚本需增加分类目录。

日常任务属于游戏层的编排，配置在上一级 `domains/hololive_dreams/daily_tasks_config.json`，与 `launch.json` 并列，可选择调用各小游戏。执行与状态识别仍在 `src/modular_agent/agent/` 及 `src/modular_agent/domains/hololive_dreams/`。

跳绳当前 YOLO 自用主线仍在 `learning/jump_rope_yolo/`，厨房实现仍在 `src/modular_agent/domains/hololive_dreams/`、`learning/kitchen_*`；本次不移动训练资料，不将历史跳绳路线提升为当前主线。下文保留组件历史，未写完整路径的文件名请在上表对应目录查找。

## greed_cards_entry.py，版本 1.0.1

第一个本地决策树：从自由主界面/地图导航到强欲之牌实际 High&Low 页面，不调用大模型、不下注、不玩卡牌。

直接调用：`load_greed_cards(project_root).decide(screen_report)` 输出当前状态与动作；`tree.run(observe, computer, progress)` 独占操作直到成功、停止、超时或需要帮助。加载接口位于 src/modular_agent/local_models.py。不要与顶层 Agent 同时操作键鼠。

命令：`.conda\python.exe -m modular_agent local-run --domain hololive_dreams --live`，需设置 PYTHONPATH=src。也可双击项目根目录 run_greed_cards_entry.cmd。不带 --live 只返回模拟模式提示，不执行键鼠。无需 API Key 或网络模型配置。

来源：2026-10-02 成功日志 agent-20261002-113650-459247.log、用户说明。每次沿用 full 识别，保留原分辨率和多尺度模板。地图标题决定地图，不以 map2 命中认定已经进入；右侧小图标选择后以详情名称核对。Cruising 短暂漏采样时根据移动输入和自由场景过渡处理。

成功条件：非地图页的 High&Low 标题，配合押注金额/开始按钮/加倍提示，或实际选牌/替换界面。自由主界面需至少四个指定 HUD 标签；地图页需 MAP 与地图模板。

成功日志有 0.3 秒 W 短按。本组件最多两次 W；点猜高低后对话最多两次 E（用户确认弹出对话框后可按 E 或点击屏幕中央推进，本组件选择 E）。同阶段普通输入最多三次，不按动画变化重置重试。位置坐标全部取当前识别；每次输入前切回游戏，鼠标加 Alt，结束释放按键，F12 可停止。

边界：未知页面、识别缺失、错误小游戏、游戏场状态或时间设施选择未知时，返回 unknown 给调用者，不猜坐标。尚未实现自动修改赌场时间；识别到未知时间选项时交回顶层。300 秒默认总超时可通过 run(timeout=...) 修改。

评估：见 tests/test_greed_cards_tree.py 的状态和完整合成路线测试；入口链式调用已由用户确认成功，修改后的全部异常分支仍需实机验证。回滚：停用 local-run，继续使用原顶层 Agent，不修改知识/模板数据。

## 顶层 Agent 确认后调用

launch.json 的 local_models.greed_cards_entry.enabled 控制启用。顶层必须先 observe，再根据 local_model_conditions 和当前证据选择 use_skill（skill=greed_cards_entry，domain=hololive_dreams），不再由任务关键词直接启动。

初始条件：目标为强欲之牌且非说明/禁止操作；真实模式；游戏可见且前台；无 Agent 遮挡区域；当前画面能被本地树判为支持的自由主界面、地图导航、目标详情、传送、现场入口或实际小游戏界面。未知状态、错误小游戏、未定位控件、时间设施选项不明等不符合。执行器会在交接前再次截图验证，防止模型等待期间界面变化。

进入类目标由本地成功即可结束；游玩/获胜等更大目标仅完成入口阶段后回到顶层。失败、未知、异常返回顶层，一次任务不重复接管。F12/stop 结束会话；人工引导在观察边界释放本地控制权，由顶层重新规划。启动游戏先用 launch_game，不由本地入口组件隐式启动。

用户已实机确认链式交接成功，异常分支仍需持续验证。测试覆盖前置观察、模型选择、初始条件及交接前变化、失败反馈、较大目标、人工引导与停止。停用时将 enabled 改为 false。

1.0.1 修正：对话不再使用 Space；可从已识别的 Shiori“为了抓住机会”对话直接按 E 恢复，不依赖之前的点击历史。

## 游戏启动前置组件

共享启动树位于 src/modular_agent/agent/startup_tree.py；顶层经验位于 knowledge/global/hololive_dreams_startup.md。顶层 launch_game 先启动/切回 Steam 游戏窗口，再串行运行启动树到自由主界面。直接运行根目录 run_game_startup.cmd，或 local-start --domain hololive_dreams --live。独立强欲之牌入口命令也会先处理启动页；若已经在地图/小游戏则交给入口树判断，不由启动树强行退出。

不依赖大模型；加载等待、继续点击、每日奖励关闭和有限中央点击由本地规则处理。尚未实机覆盖每日奖励所有类型。

识别API扩展：支持目标模板过滤、任意桌面ROI和独立开关，但当前树仍保持用户要求的完整full。升级时可通过 GeneralVision.find_text/find_templates/wait_for 使用按状态搜索，详见 ../../../docs/general-vision.md。

## greed_cards_play.py，版本0.1.0

独立本地玩法组件，CardVision/GreedCardsPlay/PlayObserver三层；接入local_models.py、CLI local-play及顶层use_skill。入口greed_cards_entry.py不变。规则、当前素材缺口及运行说明见项目docs/high-low-play.md。原始截图在领域data/high_low_samples，局部模板在data/high_low_templates。不复用历史坐标，不把输入派发当作验证。当前仅离线与合成反馈测试，真实运行待素材与实机验证。

## fishing辅助0.1.0
fishing_vision.py、fishing_controller.py、fishing.py分别保存识别、预测控制及状态机；fishing_config.json提供调参。共享实时基础设施在src/modular_agent/realtime，说明见项目docs/fishing-assist.md。用户确认左键持升松降、惯性反弹、无需Alt；结束不直接报告成功。

## fishing_loop决策树0.1.0
树内串行调用已有实时程序，识别结算继续后进入下一轮waiting；只处理循环，不换饵图鉴领奖。顶层skill=fishing_loop。说明docs/fishing-loop.md。

## 跳绳路线（2026-10-04）

[路线索引](../../../docs/jump-rope/README.md)、jump_rope_routes.json说明所有识别/控制分支。local_motion_v6仍为现有自动入口；whole_curve_v2/whole_shape_v3仅诊断；新增jump_rope_phase.py和独立参数/轨迹素材，仅普通旋转阶段跟踪、禁止输入。旧代码和入口保持。

2026-10-06版本0.3.0：玩法观察默认关闭OCR/UIA/通用knowledge，使用限定区域的多尺度文字轮廓模板、当前牌框CV决定阶段和操作。猜大小高低按钮分别限定上下区域；替换/全留/下注共位候选取最佳，牌框数量额外验证。首次获奖Congratulations模板触发当前窗口中心Alt点击，无需点击继续模板。初始获奖及最终结算金额使用区域OCR；挑战中有已确认奖励上下文时根据成功弹窗确认翻倍，不重复OCR金额；无上下文则OCR读金额。每个下注页首次仍OCR核对50，避免默认为任意下注。缺状态或必需按钮时每组判据/待确认动作只触发一次完整局部OCR，继续失败仍有界等待或交接；缺牌点/花色仅诊断OCR，不凭OCR猜花色。分支记录runtime/high-low/ocr-fallbacks.jsonl包含缺文件/低分/多位置、匹配分数、OCR文字/阶段及待确认动作，日志不用于提供历史坐标。金额未精确识别不记账；阈值保持0.5；顶层full不变。

2026-10-06版本0.4.0：用户要求去掉固定点击后等待、批量规划选牌。单次当前五张牌截图生成所有需切换标记的计划，按牌序点击，牌间等待0.1秒，最后重新截图统一核对；部分标记尚未更新只等待不重发。固定0.5秒点击后等待移除，过渡轮询间隔改0.1秒，金额/输入反馈仍核对，停止及人工引导逐动作检查。坐标仅来自该次规划截图，批内复用是用户明确要求；若批量期间窗口/牌面异常则下一观察交接，实时窗口移动仍可能造成部分输入，因此不要在批量选牌途中拖动窗口。0.1秒为牌间等待，不含输入按键及定位耗时，不声称实机10次/秒。

2026-10-06版本0.4.1：按内部预期阶段扫描必要模板；相同窗口尺寸/文件的高分缩放档位优先匹配，失败恢复多尺度扫描，不缓存坐标。批量选牌确认阶段仅匹配计划所需替换或全留按钮，重新检测当前五个牌框与粉色留牌标记；角标归一化轮廓与本轮首次牌面一致时复用已确认点数花色，变化或低相似度恢复完整牌识别。12次静态截图预热测量快速观察中位37.1ms、范围33.2–40.7ms，不含截图、窗口检查、磁盘日志、输入及动画；实际循环帧率待实机日志确认。
