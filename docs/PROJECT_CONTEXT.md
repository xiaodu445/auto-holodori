# 项目交接与顶层模块总览

> 当前交接（2026-10-26）请先读 [PROJECT_STATUS.md](PROJECT_STATUS.md) 和 [ASSET_CATALOG.md](ASSET_CATALOG.md)。下文保留早期架构及开发历史；2026-10-06 跳绳路线已非当前 YOLO 自用主线，不应照此覆盖最新配置。

> 2026-10-06 跳绳当前主线与新对话交接见 [HANDOFF](jump-rope/HANDOFF.md)，常用入口见 [跳绳索引](jump-rope/README.md)。本文后面的历史实验名称不作为当前推荐入口；旧cmd位于tools/jump_rope/legacy_launchers。


## 项目是什么

这是一个模块化、自扩展的 Agent 系统。目标是让通用模型处理理解、规划和未知情况，而让低成本、可验证的 Skill 完成重复任务；成功经验经过审核后进入知识库或固化为新 Skill。

当前已接入顶层规划、真实游戏启动和强欲之牌入口决策树；用户于2026-10-02确认链式调用成功。专属玩法训练尚未实现。

## 当前可用能力

| 能力 | 状态 | 入口 |
| --- | --- | --- |
| 通用模型调用 | 已实现 | `run`，支持 mock、OpenAI Responses 和 Kimi Chat Completions |
| Skill 注册与确定性路由 | 已实现 | `src/modular_agent/skills/` |
| 单轮 Observe → Route → Execute → Verify 闭环 | 已实现 | `agent/orchestrator.py` |
| 长期 Markdown Memory | 已实现 | `memory/store.py` |
| 屏幕/图片模板匹配 | 已实现 | `vision-*` 命令 |
| 人工模板反馈与可靠性统计 | 已实现 | `vision-feedback` |
| 真实鼠标、键盘、窗口控制 | 已实现，基础桌面实测通过；游戏入口已有用户验证 | `computer/`，见 `docs/computer.md` |
| 本地操作 MCP 服务 | 已实现，stdio 握手与模拟调用已验证 | `computer/mcp_server.py` |
| 通用本地感知（窗口、按钮、文字、知识匹配） | 已实现，Windows 桌面与中英文 OCR 已验证 | `docs/general-vision.md` |
| 通用视觉 MCP | 已实现，返回 JSON，不返回截图 | `perception/mcp_server.py` |
| 入口状态检测和本地决策树 | 已实现，用户确认成功路线 | domains/hololive_dreams/models、agent/startup_tree.py |
| 专用玩法模型训练 | 未实现 | 领域 models 预留扩展 |

## 顶层与领域的边界

```text
顶层：config/ prompts/ knowledge/global/ src/modular_agent/
      └─ 所有领域共享的模型设置、总控逻辑、CV 程序与规则

领域：domains/<domain>/
      ├─ knowledge/       仅该游戏/应用的知识
      ├─ skills/          仅该领域的 Skill
      ├─ vision_library/  该领域的 UI 模板与命中统计
      ├─ models/          该领域的小模型
      └─ data/            该领域训练和评估数据
```

不要把某个游戏的坐标、截图、模型或流程写入顶层通用目录。不要在 `_template/` 中存放真实资源。

## 后续新对话建议提供的信息

在项目目录下的新对话中，可以直接说明：

```text
阅读 docs/PROJECT_CONTEXT.md 和 docs/<相关模块>.md。
我要在 domains/<名称>/ 中实现 <目标>。
当前目标游戏/应用是 <名称>，允许/不允许真实控制，测试素材位于 <路径>。
```

如果工作涉及真实鼠标键盘操作，还需明确给出允许操作的应用、窗口或测试环境；没有该授权时应继续使用截图和 dry-run。

## 验证基线

```powershell
conda activate F:\Codex\Game_agent\.conda
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

当前基线为 66 个测试通过（含可选 MCP 依赖测试）。2026-10-01 已实测窗口枚举、鼠标移动/恢复与 Shift 输入发送。

2026-10-01：新增通用本地感知，实测 Windows 窗口/控件读取与 OCR。首次完整桌面识别约 4.9 秒，顶层执行循环已接入；hololive dreams 启动经验已注册，实际启动待用户验证。

2026-10-01：顶层命令行已连接通用感知、模型指令解析、操作与 Memory。入口 start_agent.cmd；所有任务由模型驱动，模型主动请求观察、知识读写、动作或本地技能。见 docs/agent-console.md。

顶层循环：用户目标 → 模型请求 observe → 本地结构化屏幕 → 模型请求知识/动作 → 等待并再观察 → 模型继续判断。未配置真实模型时不启动游戏。

2026-10-01：默认 Kimi kimi-k2.6，真实连通性与首次 observe 请求已验证。命令行 /models、/model 支持切换并持久化。凭据在 runtime/secrets 下按桌面 Windows 用户加密保存。

2026-10-02：加入 Kimi 429 错误分类、有限退避重试、请求间隔和停止取消。新代码需重启命令行生效。


### 2026-10-02：经验、Steam 与不限步骤

- 默认 `max_steps=0`（不限决策数），保留可选正整数上限、F12 和 /stop。
- hololive_dreams 配置 Steam 客户端 D:/Steam/steam.exe，AppID 4282500；通过 Steam 启动，已有游戏只聚焦。
- 模型收到本地 progress_evidence 与自动检索经验，系统提示主动总结经验和有条件重试。
- 重复输入第一次无变化、再次输入后出现可观察变化时，运行时自动写入 agent_notes，标记未独立验证；重复内容去重。
- 状态比较使用结构化元素及16×16缩略像素，不上传图像，不能单凭变化证明因果或任务成功。


### 游戏图标阶段收尾

- 创建 in_game/buttons、icons、states 原始模板目录与批量导入入口 import_game_templates.cmd / vision-import。
- 同名 JSON 提供简述，Markdown 记录条件与预期反馈，正式库/知识关联自动管理并去重。
- 用户说明游戏内鼠标 UI 需按 Alt；配置 mouse_modifiers=[alt]，操作模块支持鼠标修饰键，移动前按住、异常/结束释放。仅在目标游戏前台且坐标在窗口内时自动应用；相对移动保留转视角用途。
- 当前阶段只做图标定位与鼠标 UI，实时视角、小游戏专用模型/CV留后续；未声称30FPS。90项自动测试通过，真实 Alt 游戏操作仍待用户验证。


### 常驻识别优化

- UIA由每次启动子进程改为会话内常驻，JSON行请求，超时杀进程后重启；console/MCP退出显式关闭。
- OCR启动预热，限制最长边避免小图再次放大，轻量模式960且不做角度分类；完全相同像素/尺寸/原点缓存结果。
- 模板注册表、图像与缩放缓存，文件修改后重载。
- 任务每次完整full，不跳过OCR。新识别接口开放独立开关、区域、主动搜索和等待，默认调用不变。
- 本机只读少量模板测试：预热1.10s，完整3.16s，轻量OCR3.13s，仅图标82ms；游戏在后台，不能视为实际游戏FPS。97项测试通过。

## 2026-10-02 识别API扩展

完整使用说明以 docs/general-vision.md、docs/USER_GUIDE.md 和 docs/agent-console.md 为准。新增接口不自动改变现有决策树；下一步可根据状态选择目标/ROI进行性能优化。历史基准不代表当前实机FPS。

按目录知识检索已接入：先列目录/标题，再按领域、目录或文件分页读取；历史日志默认排除。Skill只发当前领域调用元数据。详见 [知识与技能上下文说明](knowledge-routing.md)。

## 2026-10-02：High&Low玩法组件0.1.0

已新增domains/hololive_dreams/models/greed_cards/greed_cards_play.py、本地CLI及顶层接管入口；规则来自用户本对话，不替换稳定导航。玩法采用卡牌CV/局部模板/规则/反馈状态机，非联网模型。当前素材未补齐，下注前拒绝运行；结算及同点真实页面尚待补图。说明docs/high-low-play.md，确认规则domains/hololive_dreams/knowledge/minigames/greed_cards_rules.md。不要误称已实机成功或数学最优。

## 2026-10-02：钓鱼辅助0.1.0
新增共享realtime采集/循环/输入锁存及领域fishing识别器、控制器、状态机；run_fishing.cmd默认只判断，显式--live输入。顶层fishing_assist仅复核实际轨道后独占接管，不运行每帧模型。用户截图静态识别已验证；动态与实机性能未验证。详情docs/fishing-assist.md。轨道丢失返回unknown交给收尾，成功失败判断未实现；既有full与猜高低保持。

## 2026-10-02：钓鱼循环决策树0.1.0
新增领域fishing_loop.py及共享桥接入口、run_fishing_loop.cmd；顶层fishing_loop调用树再调用实时组件，结算局部OCR识别继续并验证离页后再等待。默认999轮/100小时（360000秒），未知交还，成功失败不推断。实时参数未改变，原full默认行为保持；实机循环待继续页验证。说明docs/fishing-loop.md。

2026-10-03：启动hololive_dreams时自动恢复并调整窗口外框为1208×724物理像素（含标题栏），适用于新启动和已打开窗口。配置domains/hololive_dreams/launch.json的window_size.width/height，删除window_size可禁用。新增本地resize_window动作；调整后最多2秒重新枚举确认实际尺寸和前台状态，未生效返回failure。为保证完整可见，窗口位置收进主显示器工作区；尺寸超过该工作区则拒绝。尚未实机执行验证，全屏模式可能拒绝调整。

## 2026-10-04：跳绳当前路线

已按路线整理：[路线索引](jump-rope/README.md)，机器映射domains/hololive_dreams/models/jump_rope/jump_rope_routes.json。
A/local_motion_v6为现有自动入口，用户确认普通稳定；B/whole_v2和B2/shape_v3只诊断；C/fixed_phase_v1新增固定录像轨迹＋阶段/速度跟踪，仅旋转素材，只判断。新C不替换A、不删除B，预测模型存在与当前视觉支持分开，图像丢失仍保留阶段假设并降低置信度。
共用采集、输入、预览、单调时钟和窗口保护；新通用阶段组件src/modular_agent/realtime/phase_tracking.py，领域jump_rope_phase.py；记录隔离runtime/jump-rope/phase/。当前都未自动核验计数/生命/成功，校准verified仍false。高低牌、钓鱼、顶层full默认行为保持。
原跳绳逐次修改说明已完整留存[整理前项目说明](jump-rope/history/before-route-index-PROJECT_CONTEXT.md)，过期参数不再作为当前指令。继续开发先读所选路线文档和证据，再读历史。


2026-10-04补充：C2反向v2独立标志--phase-rope --phase-reverse，配置jump_rope_phase_reverse_config.json，记录隔离runtime/jump-rope/phase-reverse/。有符号速度和多帧确认转向，仍只判断，不替换C/v1或A自动；入口run_jump_rope_phase_reverse_judgment.cmd（菜单0），细节见[反向路线](jump-rope/routes/fixed-phase-reverse.md)。录像32秒遮挡位置改善，19～20秒仍失配。


2026-10-04：新增独立C3/v3合法三状态与低空有限轨迹；原v2保留，当前默认自动仍A。入口run_jump_rope_phase_state_judgment.cmd，菜单S，只判断。[说明](jump-rope/routes/fixed-phase-state.md)。


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


2026-10-05 收到 15 段人工声音区间，已保存并生成离线模板；牛dong仅遮挡提示，不选速度或方向。留出检验14段仅4段接受正确，10段拒判；未标背景17段中2段接受，待确认。尚未接入实时状态切换。见 [人工音频导入报告](jump-rope/reports/reviewed-audio-20261005.md)。


2026-10-05 离线音画回放加 Go 局部门控，394帧/6.941秒后才启动轨迹及纯开局后尾窗声音匹配。新页 runtime/jump-rope/frame-review/audio-start-gated/index.html，旧回放保留。见 [开局门控报告](jump-rope/reports/audio-start-gated-20261005.md)。


2026-10-05 第3244帧反馈修复：低空提交增加近期专属语音授权，阶段三正摇减速接入新录像0.5475圈/秒实测时钟。新独立页 runtime/jump-rope/frame-review/audio-decelerate-repair/index.html；旧回放/速度库和A/G保留。详见 [根因和回放证据](jump-rope/reports/audio-frame3244-repair-20261005.md)。


2026-10-05 左右摇1405/2752反馈：完整声音识别过晚且边界候选先过期。独立前缀证据+1.25秒候选保留，明确前缀与视觉一致时35毫秒确认。新页 runtime/jump-rope/frame-review/audio-prefix-confirm/index.html；两帧为低空，3244仍正摇减速。见 [前缀与候选保留](jump-rope/reports/audio-prefix-retained-20261005.md)。


2026-10-06 统一长速度窗口独立试验long_speed_window：三个通道共用0.25–0.45秒证据/次优角色分离。新页runtime/jump-rope/frame-review/long-speed-window/index.html；3563/5165加速误切被挡住，但5763仍有偏差、2752低空退步，不替换旧版。见 [长窗口回放结果](jump-rope/reports/long-speed-window-20261006.md)。

2026-10-06 修复优先级调整：以 audio-prefix-confirm 为离线主基线，先定位首次错误速度提交，再处理后续误差。replay_audio_review.py 默认恢复该配置，--settings/--output 可选择独立实验，use_count_hint 默认关闭。phase-reanchor-review 和 count-phase-review 保留，不提升为主线。audit_audio_regression.py 检查1405/2752低空、3244减速并导出按时间排序的模板切换证据；这三个点通过不代表全录像准确。首次重点为3563帧 confirmed_temporal_speed_recovery 的减速→加速误提交，随后再核查5164与5758；不以大偏差重建掩盖上游错误。

2026-10-06版本0.2.0：同一顶层任务允许再次启用玩法组件，保留同一个决策树账目、留牌计划与待确认动作；需再次验证当前窗口、素材、状态，首次仍从下注页开始，新任务不恢复中途账目。未确认输入不重发。牌面短暂不完整/置信不足最多等待原8秒反馈预算，缺素材、停止和输入失败不自动绕过。局部OCR最大边960，按钮图片缓存，诊断PNG/JSON成对最多每2秒写一次（错误时立即保存），顶层full不变。runtime/high-low/observations.jsonl记录当前状态、牌面、识别耗时；runs.jsonl追加每次调用结论、时长与ledger。guess_win_rate为已确认猜牌胜率（同点不计），return_on_fees为本任务已收取净收益/已确认下注费用，无下注或无猜牌时为null；不代表真实每日总收益。再次调用沿用累计统计，runs各行不能相加，否则重复累计。尚未实测帧率，不能声称50Hz。


2026-10-07：High&Low 过渡画面和输入反馈持续检测，按连续等待10秒交接，不按帧数退出。修复再来一次补点被提前等待分支挡住的问题；原结果页按钮仍被当前识别定位时，间隔至少0.5秒补点，最多3次，补点不重置10秒等待窗口。到下注页立即结束补点；下注和猜牌不盲目重复。

2026-10-07：全部小游戏点击支持反馈未变化时补点（至少间隔0.5秒，最多3次），仍以当前帧重新定位，且不延长10秒反馈等待窗口。留牌只补点当前尚未符合计划的牌；猜牌只在基准牌点数和花色未变化时补点。界面切换或无法识别时继续等待，不使用旧坐标。

2026-10-07：结算金额缺失或不一致时继续检测10秒；猜牌直接进入结算先核对精确翻倍金额，成功后才更新奖励与胜场，避免过渡数字重复记账。结算帧保存诊断截图与金额OCR原文。

2026-10-07：手动指定今日已收取累计：`run_greed_cards_play.cmd --daily-collected 12800`。无需另传stage，累计10000至19199采用第二笔6400策略，19200以上采用最后一笔策略，0至9999采用首笔策略；特殊记录可显式用--stage覆盖。未手动指定时继续沿用同日已核对累计与阶段，跨日归零。

2026-10-07 策略修正：当日已收取累计大于18000（剩余额度小于2000）时，自动进入最后一笔策略，继续翻倍至本局奖励至少10000再收取，允许超过每日门槛；覆盖旧第二阶段记录。输入19000无需--stage。恰好18000仍沿用第二阶段策略。

2026-10-07：每次运行结束输出局数、已收取奖励、赢局净赚、输局数与损失、下注成本、净收益。输局净收益-50，赢局净收益为到账奖励减50。JSON结果ledger包含round_history；runtime/high-low/runs.jsonl保存运行统计，runs.log追加易读汇总和逐局结果。未结算对局不当作输局，下注成本仅在确认进入留牌页时计入。

2026-10-08：修复结算已记账但再来一次按钮未加载时的误交接。保留已记账标记，继续识别当前按钮，不重复累计奖励、胜局或阶段；进入下注页后清除标记。

2026-10-08：重新启动自动恢复当日已确认累计与阶段，启动输出恢复值；last-result.json不可用则从runs.jsonl倒序读取最后一条有效同日账目。每次结算核对成功立即写入检查点，不等整个运行结束，强制关闭后仍可恢复。直接运行run_greed_cards_play.cmd即可；--daily-collected仍可覆盖，跨日默认0。

2026-10-08：小游戏总时限保持1800秒（半小时），默认局数上限由20调为999，独立/顶层/每日入口一致。净亏损预算仍为1000，可用--max-loss覆盖；收取6400、下注1000时净收益5400不会触发净亏损预算。退出日志分别明确局数、净亏损或总时限原因。基准8的高低等概率，当前固定选高。

2026-10-08：按用户要求，所有High&Low入口默认局数上限统一为200局，总时限仍为半小时。
