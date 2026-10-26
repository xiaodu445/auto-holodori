# 可组合每日任务接口（2026-10-17）

本轮目标是将既有每日流程拆成“纯计划＋执行器＋证据记录”。没有新增云模型调用，也没有改动用户holo之家路线（当前配置为W 2.5秒）。保留旧启动命令和play_greed_cards默认行为。

## 计划示例

```json
{
  "selected_tasks": ["holowork", "wheel"],
  "record_rewards": true,
  "redispatch_holowork": true,
  "max_rounds": 200,
  "max_loss": 10000
}
```

示例已保存为config/daily-plan.example.json。显式选择这些任务后不会附带其他通知或卡牌玩法。selected_tasks为空列表时完全不操作游戏；null或省略则沿用配置，配置也为null时兼容旧逻辑：五类通知，加上play_greed_cards控制的入口与玩法。

支持ID：holowork、holo_home、the_cell、kaogan、wheel、greed_cards_entry、greed_cards_play。
- 只选greed_cards_entry：进入准备页即返回，不下注。
- 选greed_cards_play：计划显式增加greed_cards_entry依赖，并在added_dependencies列出。
- 通知分支先于入口，入口先于玩法，可信扩展任务在后；通知页面扫描采用所选任务优先级，仍受当前可见页影响，不保证绝对执行顺序。
- 未实现的expiry_notice会被拒绝，不会当完成；task_pass/events/achievements现已接入可选模块，详见文末。没有保证清除全部感叹号。
- 重复任务、未知字段、错误类型和越界预算在输入前拒绝。

## 命令

从项目根目录运行：

```powershell
.\.conda\python.exe -m modular_agent local-daily --domain hololive_dreams --daily-plan config/daily-plan.example.json --plan-only
.\.conda\python.exe -m modular_agent local-daily --domain hololive_dreams --daily-tasks holowork,wheel --record-rewards --live
.\.conda\python.exe -m modular_agent local-daily --domain hololive_dreams --daily-tasks greed_cards_entry --live
```

--plan-only不会构造桌面控制器，不启动或切换游戏，即便同时传--live也只预览。旧run_daily_tasks.cmd现在透传参数，可加--daily-tasks、--daily-plan、--plan-only等。

--record-rewards / --no-record-rewards覆盖计划记录开关。max_rounds/max_loss在每日计划JSON中指定；CLI同名旧参数目前主要服务local-play，不覆盖每日JSON预算。

## Python接口

```python
from modular_agent.local_models import execute_daily, run_daily_tasks
from modular_agent.domains.hololive_dreams.daily_plan import build_plan, catalog

# 无副作用：根据已有配置生成可审阅计划。
plan = build_plan(config, {"selected_tasks": ["holowork"], "record_rewards": False})

# 使用已有会话及唯一输入执行器。
result = execute_daily(
    adapter,
    request={"selected_tasks": ["holowork"], "redispatch_holowork": False},
    startup=False,
    on_event=receive_event,
    reward_reader=read_reward_overlay,
    should_yield=cancel_requested,
)
```

execute_daily/startup=False要求调用方已保证合适起始状态，并继续进行当前帧的窗口/状态检查。startup=True默认复用游戏启动模块。

扩展钩子：
- on_event(event)：收到计划、观察、输入、任务开始/结束、奖励证据、结果。只用于观察/统计，避免阻塞或再次操作输入。回调异常被记录，不中断主流程。
- reward_reader(report)：仅record_rewards=true且新奖励层出现时调用；返回包含items列表的字典。读取器异常作为reader_error保存，不让领取流程崩溃。
- should_yield()：已有停止/人工接管接口，检查发生在观察和输入边界。
- task_handlers={"custom_id": callable}：可信Python注册扩展任务，request只能选已注册ID，不能在JSON内加载或执行代码。函数接收adapter/config/plan/observe/progress/should_yield/emit上下文，返回含outcome的字典。不能覆盖内置ID；扩展处理器要自行确认界面、遵守唯一输入所有权及取消条件。
- selected_tasks、redispatch_holowork、max_rounds/max_loss：执行范围、派遣及玩法预算。

扩展任务当前没有通用自动恢复或任意依赖图。需要更复杂的前后置关系时扩展TaskSpec与build_plan，并补测试，而不是把顺序写进自然语言后假定执行器懂了。

## 给AI的接口

catalog()返回支持任务、说明、依赖和未实现ID；build_plan验证模型生成的JSON。Agent的daily_tasks技能支持daily_request字段，能力描述中已给任务目录和字段说明。

建议链路：用户需求 → AI生成daily_request → build_plan校验/预览 → 执行 → 返回分任务证据及下一步问题。部分任务必须显式selected_tasks；只要求进入不要选择玩法。自然语言规划的可靠性仍需对话验证，不能说“任意需求都已能自动规划”。

## 奖励记录的准确含义

默认关闭专门的奖励记录，不调用reward_reader。开启后，仅对每日领取流程中捕获到的奖励展示层保存一次证据；关闭该层后再次出现才开启下一条。该去重是展示层连续性，不是账户级交易去重，也不保证一次领取只有一个奖励层。

记录包含任务ID、观察时间、文字/模板证据及可选reader_result。amounts_verified保持false：看到奖励弹层、读到数字，都不等于已核对背包到账。当前不自动识别所有奖励名称和数量，不计算跨任务总资产；High & Low继续使用原有独立账本。

关闭record_rewards不会关闭常规诊断事件；观察日志仍可能包含奖励页文字和模板证据。它控制专门的奖励记录/reader成本，不是“所有日志都不记录奖励画面”的隐私开关。

## 每日逻辑调整

礼物交互泛化：在右侧识别前景“礼物”文字与同一行附近蓝色E键，形成gift_prompt；不依赖NPC名、气泡台词或整块粉色背景。礼物目标出现后立即停止追加移动，按E交互；原专用模板保留兼容。已用用户The Cell失败截图及无专用模板的模拟流程回归，97项相关测试通过，仍需实机确认。

固定HUD备用点击：attention模板漏检时，可用配置attention_fixed_region（默认enabled=true、x_ratio=0.205、y_ratio=0.125）点击游戏窗口内的小喇叭中心。仅在已确认自由场景/附近交互且无已知覆盖层时使用，窗口过小或比例异常拒绝；按Alt点击，随后必须验证通知面板/条目，不能以固定点击代替成功判断。可关闭或根据UI布局调比例。游戏窗口移动不影响相对定位。

2026-10-18修正：打开通知后最多等8秒（不超过配置过渡时限）；已知条目出现可立即处理。无匹配不能当清空，须等至少2秒后连续两帧检测到通知标题且无白色条目，才接受空列表。面板未知或仍有未识别条目时暂停后续玩法。所有所选通知已处理时直接结束本轮，不反复重开通知。Holowork的GET改为Alt点空白，持续识别直到消失；2秒间隔最多三次，未关闭则报奖励层具体错误，不提前转去等待统一设置。空面板结构规则仍待真实空通知样本验证。

转盘收尾修正：用户确认领取后附近交互提示会常驻。收尾及通知返回允许带交互提示的自由场景；交互后先观察一次界面变化，再连续确认自由场景，不要求提示消失。未观察到变化则等待超时，不反复E。此检查仍不核实奖励数量。

- free判断共用领域状态，奖励/对话/地图/选项/错误/加载优先于背景HUD。
- 收尾对话按E，GET/升级Alt点空白；陌生层先等，最多两次有间隔空白探测，不无限点击。
- 行走中暂时未知先释放/不新增移动并等待，不立即当失败；错误或持续超时返回具体原因。
- Holowork可只领不重新派遣；通常仍使用原推荐流程。
- 通知按选择过滤，每项本轮最多一次；未扫描到记skipped/未验证，不表示已完成。
- 某任务未完成时停止后续依赖操作，后续条目标为未执行，不在未知页面强行继续。
- 观察按通知、Holowork、礼物阶段缩小模板名单，默认不OCR；现有共享world_features自动提供结构证据。每日模板未全部改造成入口同款ROI搜索。

## 结果与日志

每次执行使用runtime/daily-tasks/<时间-ID>/：
- events.jsonl：结构化计划、状态、观察报告、输入参数和结果。
- result.json：本次结果。
- runtime/daily-tasks/last-result.json：最近一次兼容索引。
- 旧run_daily_tasks输出文本log仍保留；greed-entry和high-low仍保存各自记录。

items按所选任务给success/unknown/failure/skipped；依赖自动加入项也列入。顶层verified表示模块处理范围的流程确认，不代表所有任务目标完成、奖励数量核实或感叹号清空。应同时检查items和各项verification。

## 验证与未完成范围

125项相关离线测试通过，含计划校验、空计划零输入、预览零桌面控制、子集过滤、玩法依赖、只领不派、共享覆盖层、奖励去重/关闭/reader异常及可信扩展日志。用户实际游戏全流程尚未验证。

任务通行证、活动、成就、截止提醒仍待实现可执行模块。视觉资产和世界规则已有归档，但不能把“知识已保存”当“任务执行器已支持”。逐个新增处理器后再加入支持目录。
# 活动、任务通行证、成就领取模块（2026-10-18）

## 模块选择与未知通知策略

临时选择：`run_daily_tasks.cmd --daily-tasks achievements,events,task_pass`，仅执行列出的模块，不附加默认玩法。

持久选择：编辑`domains/hololive_dreams/models/daily_tasks_config.json`的`selected_tasks`，设为任务ID数组；`null`沿用旧默认，`[]`不执行。CLI的`--daily-tasks`优先于JSON计划文件，再优先于默认配置。

可用ID：`holowork`工作领取/推荐派遣；`holo_home`holo之家礼物；`the_cell`The Cell礼物；`kaogan`颜岩山礼物；`wheel`红心轮盘；`achievements`成就；`events`活动；`task_pass`任务及通行证；`greed_cards_entry`仅进入强欲之牌；`greed_cards_play`玩强欲之牌（自动补入口依赖）。

`unknown_notification_policy`默认`ignore_run`：确认通知面板展开、按页扫描后，没有本次可处理项就退出。本次忽略剩余感叹号，通知阶段`stage_complete=true`，允许继续后续模块；不把未知通知标为领取成功，`verified=false`。忽略仅保存在本次执行对象中，不持久化到下一次运行。设为`stop`恢复遇剩余未处理通知暂停。两种策略都不会把“没有匹配/面板未展开”当空列表。

提示：截图中的“活动徽章兑换即将截止”仍无专用处理器，此次只忽略，不自动兑换，也不声称其实际感叹号已消除。

已注册`achievements`、`events`、`task_pass`，可独立选择；默认计划不变，不自动加入强欲之牌。示例见`config/daily-claims.example.json`。

运行：`run_daily_tasks.cmd --live --daily-tasks achievements,events,task_pass`。先预览可加`--plan-only`。也可通过现有`--daily-plan`加载示例JSON，`--record-rewards`启用奖励证据记录。

任务通行证：每日/每周/季度领取Pt后再领通行证。成就：栏目→可领取条目→当前条目全部领取→GET/可选升级→返回栏目。活动：轮播GO进入活动（仅此导航允许GO）→任务每日/自由，或直接任务列表，只点领取，不追做目标。活动、任务通行证位于后置phase40，成就phase30；顺序稳定保留请求相对顺序。

安全性：新模块领取文字阈值0.92并要求同帧启用蓝色；未知页面超时停止。所有输入复用DailyTasks的焦点/遮挡/停止/Alt与日志逻辑，奖励复用RewardRecorder。默认每列表6页、成就每栏目8页、活动最多8次切换，有界扫描不保证全覆盖。结果返回`verified=false`及`reward_episodes`，不当作完整清空或数量入账证明。

当前没有真实活动可领取截图，暂复用其他任务的领取字样；字体/布局不同时可能漏检。置灰按钮已有真实截图负例验证，其余新流程尚未实机验证。兑换截止通知仍未实现。缺陷台账与防回归规范见`docs/bug-ledger.md`、`docs/development-guardrails.md`。

