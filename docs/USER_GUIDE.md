# 使用手册

> 2026-10-06 跳绳当前主线与新对话交接见 [HANDOFF](jump-rope/HANDOFF.md)，常用入口见 [跳绳索引](jump-rope/README.md)。本文后面的历史实验名称不作为当前推荐入口；旧cmd位于tools/jump_rope/legacy_launchers。


## 顶层 Agent

双击 start_agent.cmd，输入“启动holodori”或“打开强欲之牌”。启动与进入小游戏的链式调用已由用户实机确认；界面版本变化和未知状态仍需人工引导。

任务开始由联网模型先观察并选择技能；launch_game 通过Steam启动/切回，再由本地启动树处理登录奖励到自由主界面。强欲之牌入口组件只在模型判断和执行器复核初始条件符合后接管，到实际High&Low界面结束，不下注。

任务中直接输入补充指示或 /guide 指示；看到已排队和已接收才算生效。/stop（不区分大小写）或F12停止；停止会话需重启。/logs on/off显示隐藏浮动日志；/status查询状态；/observe默认full；/windows查看当前窗口；/models、/model配置名切换模型；/quit退出。

默认任务步骤不限，但网络重试、本地组件、持键时长和错误恢复有局部上限。--live 才发送真实键鼠；模拟模式不会完成真实任务。

## 不依赖联网模型的入口

- run_game_startup.cmd：Steam启动、奖励处理，到自由主界面结束。
- run_greed_cards_entry.cmd：本地导航到实际High&Low页面，不下注。

二者不要与正在操作的顶层Agent并行运行。加载文字会等待，闪烁提示可由有限中央点击推进。当前本地玩法/赌场时间选择仍未实现。

## 模板和知识

图片放 domains/hololive_dreams/data/template_sources/in_game 对应目录，同名JSON描述含义、角色和threshold；启动任务自动同步，也可运行 import_game_templates.cmd。现有模板（含启动图标）匹配阈值统一0.65，新建及导入模板默认0.65。具体见 docs/vision.md 和源目录README。

顶层共享经验在 knowledge/global，游戏内经验在 domains/hololive_dreams/knowledge。任务事实在 runtime/memory/task_sessions；完整决策/反馈保存在事实记录，终端显示简化输出。模型 write_knowledge 记录需标注来源与验证状态，不能保证每次主动保存。

## 识别与升级

现有顶层及决策树保持完整full，不截断模型收到的屏幕报告。新接口支持独立开关、桌面区域、指定文字/模板搜索、等待与取消，可供以后按状态优化。Python/MCP用法见 docs/general-vision.md。配置模型和密钥见 docs/models.md；操作接口见 docs/computer.md。

按目录知识检索已接入：先列目录/标题，再按领域、目录或文件分页读取；历史日志默认排除。Skill只发当前领域调用元数据。详见 [知识与技能上下文说明](knowledge-routing.md)。

## 强欲之牌本地玩法（0.1.0）

新组件greed_cards_play.py已接入顶层和local-play，从下注页执行留牌/换牌/猜大小/结算，素材不足及未知状态交回。使用与素材命名见[玩法组件说明](high-low-play.md)。原入口保持不变，顶层完整full观察保持不变。当前尚未实机验证；补卡牌及高低按钮模板、中奖/结算/同点截图后再测试。

## 钓鱼辅助（0.1.0）
手动进入钓鱼轨道后运行 run_fishing.cmd，默认只判断；--live 开启左键实时控制，--phase waiting 从上钩等待开始。调参、离线回放及限制见 [钓鱼辅助说明](fishing-assist.md)。结果由其他模块确认。

## 钓鱼循环决策树
手动进入钓鱼后运行 run_fishing_loop.cmd --live；已抛竿等待时加 --phase waiting。默认999轮、总时长100小时，--max-rounds和--timeout可调整，F12停止。顶层可调用fishing_loop，由本地树串行调用实时程序和结算继续识别。见 [循环说明](fishing-loop.md)。

2026-10-03：启动hololive_dreams时自动恢复并调整窗口外框为1208×724物理像素（含标题栏），适用于新启动和已打开窗口。配置domains/hololive_dreams/launch.json的window_size.width/height，删除window_size可禁用。新增本地resize_window动作；调整后最多2秒重新枚举确认实际尺寸和前台状态，未生效返回failure。为保证完整可见，窗口位置收进主显示器工作区；尺寸超过该工作区则拒绝。尚未实机执行验证，全屏模式可能拒绝调整。

## 跳绳组件

双击run_jump_rope_routes.cmd选择路线，或读[跳绳路线索引](jump-rope/README.md)。
当前自动：run_jump_rope_local_motion.cmd（35ms实验空格）；只看判断：run_jump_rope_local_motion_judgment.cmd。
新固定轨迹：run_jump_rope_phase_judgment.cmd，只判断并实时显示阶段、速度、置信度和推测曲线；run_jump_rope_phase_replay.cmd用已有录像验证，不发送空格。
旧整绳、形状实验和录制器仍保留；run_jump_rope.cmd无参数会发实验空格，Python CLI无参数仍只判断。
F12、Ctrl+C、切走游戏停止；启动时自动切回已打开游戏。新路线仅有普通旋转轨迹，低空摇摆和跳跃时机尚未标定。不要同时运行两个实时组件，结果unknown不代表失败或成功。
旧逐次说明完整保存[整理前使用手册](jump-rope/history/before-route-index-USER_GUIDE.md)。


反向固定轨迹预览：run_jump_rope_phase_reverse_judgment.cmd，或路线菜单按0。rate可为负，direction为路径前进/后退，turns为确认方向变化次数。仅判断不发空格；原前向预览和自动入口保留。[说明和对照](jump-rope/routes/fixed-phase-reverse.md)。


2026-10-04：三状态v3观察：run_jump_rope_phase_state_judgment.cmd，或路线菜单S；不发送空格。回到基线仍运行反向v2入口。[说明](jump-rope/routes/fixed-phase-state.md)。


2026-10-04：C3三状态路线已加入候选可撤销关联、丢失首帧原状态续推及下落零速拒绝；入口不变，仍只判断。370项测试通过。完整回放显示推进连续性改善，但55秒重获取精度退步，60FPS实机尚未确认。详情见docs/jump-rope/routes/fixed-phase-state.md的即时续推修正；修改前C3快照保留，C2与自动路线保留。





2026-10-04 C4长时离线改进：保留片段锁和一次反转，修复遮挡后可见行程不足造成重入锁住；永久保存三个实测低空周期，但多档竞争仍更差，默认保留单档。421测试通过；4010帧回放11个稀疏状态点吻合，32/55秒曲线仍失配。菜单G/`run_jump_rope_phase_gear_judgment.cmd`仍仅判断，A自动和C2/C3保留。详细参数、对照与启动见 [C4说明](jump-rope/routes/trajectory-gears.md) 和 [长时分析](jump-rope/reports/c4-long-run-20261004.md)。


2026-10-05：G/C4新增圆周落地分支，四档从共同落地边界播放、多帧确认接管完整阶段，确认清除旧批避免反复换档。32/55秒几何约31/37px降至7/1px；低空75.5秒仍迟入，10/11稀疏状态点。431测试通过，仍只判断。旧版独立入口 `run_jump_rope_phase_gear_baseline_judgment.cmd`，A/C3保留；见 [本轮说明](jump-rope/reports/landing-branches-20261005.md)。


2026-10-05 分阶段原型：录像核对计数10/30/50/70切级，每级常态/加速/减速/左右摇四角色，方向单独处理；50/70次在低空中升级，保留轨迹和片段，整体改速。独立入口 `run_jump_rope_stage_judgment.cmd`，只判断。加减速同级周期未独立校准，分阶段版本32秒仍失配，不替换G。见 [阶段模型与证据](jump-rope/routes/stage-templates.md)。


2026-10-05 逐帧审阅：新增低空进入边界/已播放周期修正与平滑模板独立入口run_jump_rope_gear_review_judgment.cmd、run_jump_rope_stage_review_judgment.cmd，均只判断。原G保留；阶段原型改善但未胜过G。逐帧网页runtime/jump-rope/frame-review/index.html，支持人工标注导出。详见docs/jump-rope/routes/frame-review.md。


2026-10-05 独立反摇时间模板：用户确认前慢后快，不能倒放正摇时序。新增反摇时钟与图集位置映射、反解和解析速度/加速度；原G保持。实验入口run_jump_rope_reverse_timing_judgment.cmd，只判断；详见docs/jump-rope/routes/reverse-timing.md。


2026-10-05 五处人工标注：1978仅标记加速、不作方向真值。独立只判断入口 `run_jump_rope_human_calibration_judgment.cmd`；逐帧页 `runtime/jump-rope/frame-review/human-calibration-clean-bank/index.html`。843/2279低空偏差改善，1978加速仍退步，不替换原G或A。详见 [校准报告](jump-rope/reports/human-calibration-20261005.md)。


2026-10-05 三处标注跟进：独立入口 `run_jump_rope_clock_exit_judgment.cmd`，仍只判断；新逐帧页 `runtime/jump-rope/frame-review/clock-exit-reverse-cohort/index.html`。反摇退出多档竞争与重复帧证据窗口改善1115/2484附近；1869加速仍未修好，55秒位置退步，不替换原G。见 [分析与限制](jump-rope/reports/clock-exit-20261005.md)。


2026-10-05 低空退出方向规则：从后往前才接反摇，从前往后才接正摇，且退出必与进入前反向。独立只判断入口 `run_jump_rope_directional_exit_judgment.cmd`；逐帧页 `runtime/jump-rope/frame-review/directional-exit/index.html`。902错误候选消除，959生成合法候选，1087确认反摇；加速1869仍未解决。见 [规则、接点与回放证据](jump-rope/reports/directional-exit-20261005.md)。


2026-10-05 阶段速度库独立实验：模板改为“阶段 X → 正常 / 加速 / 减速”，正反摇分别保存时间曲线，未实测部分标待校准。入口 `run_jump_rope_stage_clock_library_judgment.cmd` 只判断；审阅页 `runtime/jump-rope/frame-review/stage-clock-library-review/index.html` 明确区分活动模板与候选。加速选择仍有错误，不替换 A/G。分析见 `docs/jump-rope/reports/stage-clock-library-20261005.md`。


2026-10-05 阶段二正常/加速反摇独立拟合：扣固定背景支持，正常.750、加速.910；新只判断入口 run_jump_rope_stage_clock_v2_judgment.cmd。仍实验，旧路线保留，见 docs/jump-rope/reports/stage-clock-v2-20261005.md。


2026-10-05 计数/速度阶段共存独立实验：run_jump_rope_stage_coexist_judgment.cmd只判断；计数升级只增候选，旧时钟继续，由连续证据接管。详见docs/jump-rope/reports/stage-coexist-20261005.md，原入口保留。


2026-10-05 连续证据圆周速度纠错独立试验：run_jump_rope_temporal_recovery_judgment.cmd只判断，保留候选时钟，接管清旧阶段；不改变低空规则。详见docs/jump-rope/reports/temporal-recovery-20261005.md。


2026-10-05 前后半圈速度切换独立入口run_jump_rope_half_cycle_judgment.cmd只判断；前半圈收紧、后半圈连续证据纠错，详见docs/jump-rope/reports/half-cycle-20261005.md。


2026-10-05 采集程序加扬声器回环音频：record_jump_rope.cmd默认5分钟，F12停止；保存audio.wav及audio-timestamps.jsonl，与画面/空格共用单调原点。先录10秒检查样本/峰值/错误；关闭其他声音。详见docs/jump-rope/routes/audio-recording.md。本轮不改分支或轨迹模板。


2026-10-05 音画后续校准：新机位独立空间图集及六组实测正反摇候选时钟已保存；声音区间等待人工标注，离线频谱/DTW 导入工具不控制输入。旧 A/G 入口保持。试听页 runtime/jump-rope/audio-calibration/index.html；验证边界和导入步骤见 [校准报告](jump-rope/reports/audio-calibration-20261005.md)。

2026-10-06版本0.2.0：同一顶层任务允许再次启用玩法组件，保留同一个决策树账目、留牌计划与待确认动作；需再次验证当前窗口、素材、状态，首次仍从下注页开始，新任务不恢复中途账目。未确认输入不重发。牌面短暂不完整/置信不足最多等待原8秒反馈预算，缺素材、停止和输入失败不自动绕过。局部OCR最大边960，按钮图片缓存，诊断PNG/JSON成对最多每2秒写一次（错误时立即保存），顶层full不变。runtime/high-low/observations.jsonl记录当前状态、牌面、识别耗时；runs.jsonl追加每次调用结论、时长与ledger。guess_win_rate为已确认猜牌胜率（同点不计），return_on_fees为本任务已收取净收益/已确认下注费用，无下注或无猜牌时为null；不代表真实每日总收益。再次调用沿用累计统计，runs各行不能相加，否则重复累计。尚未实测帧率，不能声称50Hz。

2026-10-06：用户确认当前固定尺寸1190×714，启动window_size预设同步为1190×714（现有配置表示含标题栏/边框的窗口外框物理像素）。玩法模板原尺寸匹配不变，覆盖此前1208×724预设。

2026-10-06：用户要求固定常见分辨率，启动窗口外框预设统一1280×720物理像素（含标题栏/边框，并非客户区尺寸），覆盖1190×714。小游戏不做多尺度搜索，按钮与状态模板须在此固定尺寸下重新截取或验证；卡牌角标归一化不变。


2026-10-07：High&Low 过渡画面和输入反馈持续检测，按连续等待10秒交接，不按帧数退出。修复再来一次补点被提前等待分支挡住的问题；原结果页按钮仍被当前识别定位时，间隔至少0.5秒补点，最多3次，补点不重置10秒等待窗口。到下注页立即结束补点；下注和猜牌不盲目重复。

2026-10-07：全部小游戏点击支持反馈未变化时补点（至少间隔0.5秒，最多3次），仍以当前帧重新定位，且不延长10秒反馈等待窗口。留牌只补点当前尚未符合计划的牌；猜牌只在基准牌点数和花色未变化时补点。界面切换或无法识别时继续等待，不使用旧坐标。

2026-10-07：结算金额缺失或不一致时继续检测10秒；猜牌直接进入结算先核对精确翻倍金额，成功后才更新奖励与胜场，避免过渡数字重复记账。结算帧保存诊断截图与金额OCR原文。

2026-10-07：手动指定今日已收取累计：`run_greed_cards_play.cmd --daily-collected 12800`。无需另传stage，累计10000至19199采用第二笔6400策略，19200以上采用最后一笔策略，0至9999采用首笔策略；特殊记录可显式用--stage覆盖。未手动指定时继续沿用同日已核对累计与阶段，跨日归零。

独立启动`run_greed_cards_play.cmd`时，先定位正在运行的游戏窗口并聚焦，核实已到前台再开始截图决策；失败则交接。不会启动或导航游戏。

2026-10-07：按用户偏好，留牌阶段角标分离失败时使用固定角标区域的最高分模板候选，完整五张候选允许重复牌判据继续决策；无法取得完整候选则持续重识别，不因牌面识别异常主动交接。停止、人工引导和组件总时限仍有效。

2026-10-07 策略修正：当日已收取累计大于18000（剩余额度小于2000）时，自动进入最后一笔策略，继续翻倍至本局奖励至少10000再收取，允许超过每日门槛；覆盖旧第二阶段记录。输入19000无需--stage。恰好18000仍沿用第二阶段策略。

2026-10-07：每次运行结束输出局数、已收取奖励、赢局净赚、输局数与损失、下注成本、净收益。输局净收益-50，赢局净收益为到账奖励减50。JSON结果ledger包含round_history；runtime/high-low/runs.jsonl保存运行统计，runs.log追加易读汇总和逐局结果。未结算对局不当作输局，下注成本仅在确认进入留牌页时计入。

2026-10-08：重新启动自动恢复当日已确认累计与阶段，启动输出恢复值；last-result.json不可用则从runs.jsonl倒序读取最后一条有效同日账目。每次结算核对成功立即写入检查点，不等整个运行结束，强制关闭后仍可恢复。直接运行run_greed_cards_play.cmd即可；--daily-collected仍可覆盖，跨日默认0。

2026-10-08：小游戏总时限保持1800秒（半小时），默认局数上限由20调为999，独立/顶层/每日入口一致。净亏损预算仍为1000，可用--max-loss覆盖；收取6400、下注1000时净收益5400不会触发净亏损预算。退出日志分别明确局数、净亏损或总时限原因。基准8的高低等概率，当前固定选高。

2026-10-08：按用户要求，所有High&Low入口默认局数上限统一为200局，总时限仍为半小时。
