# 文字任务、接口和执行计划

用户文字由 GeneralAgent 的模型解释。模型先用 `list_capabilities` / `read_capability` 读取接口，再用 `execute_plan` 提交结构化计划。参数和静态业务约束在整份计划开始前校验；引用结果的参数在结果可用后再次校验。程序只调用已登记的可信适配器，不执行模型生成的 shell 或 Python。

## 三类配置

- `config/model*.json`：模型服务、地址、认证等本机配置；不会作为能力接口交给模型。
- `domains/hololive_dreams/capabilities.json`：公开能力说明、参数类型/范围/默认值、前置条件、返回值与结果语义。这是模型读取的接口文件。
- `daily_tasks_config.json` 和各小游戏配置：执行默认值。日常 `request.config_overrides` 只作用于本次调用，不写回原文件。小游戏 `config_path` 可选择领域内已有 JSON，厨房 `weights` 可选择领域 models 内已有权重。

## 已接入的能力

完整 ID 均以 `hololive_dreams.` 开头。

| 名称 | 主要参数 | 边界 |
| --- | --- | --- |
| launch_game | 无 | 启动/聚焦并走已有启动树 |
| return_to_free | timeout_seconds | 退出已识别菜单、关闭已登记弹层；连续三帧确认自由界面，不退出未知小游戏 |
| daily_tasks | request、startup | request 支持选择任务、派遣、奖励记录、玩法预算、通知策略和临时路线/等待/识别配置 |
| greed_cards_entry | 无 | 只进入，不下注 |
| greed_cards_play | max_rounds、max_loss、daily_collected、stage | 用户明确要求游玩；保留同会话账目，中途不能改起始参数 |
| fishing_loop | max_rounds、timeout_seconds、phase、config_path | 人工进入轨道/TAP!/结算继续页后调用 |
| fishing_assist | timeout_seconds、phase、config_path | 人工进入实际轨道 |
| jump_rope | timeout_seconds、config_path、preview | 当前 CUDA 引擎；仍需 F8 武装，不自动导航 |
| kitchen | duration、targets、weights、device、点击/批次/置信度策略 | 人工进入厨房；全部公开字段见接口文件 |
| rhythm | timeout_seconds、config_path、overrides、preview | 单曲实际打歌页；overrides 提供偏移、BPM、FPS、采集等参数 |
| multi_live | rounds、timeout_seconds、offset、grid_snap、匹配/单曲预算、rhythm_profile 等 | 使用已有菜单与结算树，等人零点击 |

日常选择的任务仅限接口枚举。新小游戏通过计划中的独立能力步骤组合，不伪装成尚不存在的日常任务 ID。每个能力的 params 结构独立，例如日常参数在 `params.request` 中。

## 模型协议

读取接口：

```json
{"decision":"read_capability","capability":"hololive_dreams.fishing_loop","reason":"核对用户指定轮数和时长的参数"}
```

执行（游戏须已人工进入钓鱼）：

```json
{
  "decision": "execute_plan",
  "plan": {
    "schema_version": 1,
    "timeout_seconds": 630,
    "steps": [{
      "id": "fish",
      "capability": "hololive_dreams.fishing_loop",
      "params": {"max_rounds": 5, "timeout_seconds": 600},
      "timeout_seconds": 610
    }]
  },
  "reason": "按用户要求最多钓鱼5轮、实时组件最多运行10分钟"
}
```

加 `plan_only:true` 可预览，不创建电脑输入执行器或实时进程。模拟会话同样只预览。旧 `use_skill` 保留兼容；传 `params` 时走相同校验和计划执行链，旧 `daily_request` 继续可用。一般优先使用新协议。

`steps` 严格按数组顺序执行，最多100步。多个不同 ID 可以调用同一能力，适合“领取 → 小游戏 → 再领取”。这不解除能力的前置条件，也不重置强欲之牌中途账目。执行器不会自动补充未授权的导航、消费或缺失训练能力。

- `depends_on:["earlier"]`：只可引用前面的步骤；依赖非 success 时跳过。
- `when:{"ref":"earlier.outcome","equals":"success"}`：值相等才执行。要依据失败进入备用分支，前一步须显式 `on_failure:"continue"`，备用步骤不能再把失败步骤列为必须成功的依赖。
- 参数中的 `{"$ref":"earlier.completed_rounds"}`：读取已返回字段。只支持对象字段路径，不支持代码表达式、数组索引或文件读取。字段缺失、类型或范围不符则该步失败。
- `on_failure` 默认 stop；continue 仅继续后续独立步骤。unknown/failure 不会被后来的独立成功覆盖；只有下文声明的前置条件恢复允许一次重试。
- `recovery` 默认 auto；none 关闭自动恢复。不是让所有失败都重试，仍需能力接口声明恢复目标与可信前置条件失败证据。
- 总预算与步骤预算取较小值。实时进程还有各自轮数/时长限制；取消以正常停止信号优先，卡死超时才结束进程并释放可能持有的输入。截图、推理或底层阻塞不承诺硬实时截止。

条件和参数引用必须针对实际结果；返回结构中的可选字段可能因早期退出而缺失。不要假设厨房有通关结果、钓鱼有已确认奖励，或仅用 elapsed_seconds 推断任务成功。

## 前置状态自纠正

日常能力在业务操作前观察界面。已处于自由界面直接继续；已识别菜单或弹层则返回结构化错误，保留当前状态和未发送业务输入的事实：

```json
{
  "outcome": "unknown",
  "verified": false,
  "error": {
    "code": "precondition_not_met",
    "phase": "precondition",
    "expected_state": "world.free",
    "observed_state": "menu.recognized",
    "business_input_sent": false,
    "recoverable": true
  }
}
```

接口的 `precondition_recovery` 将这种错误映射到 `return_to_free`。执行器最多进行一次“恢复 → 验证目标状态 → 重试当前步骤”，不重跑前序步骤，不重置原步骤/总计划预算。恢复必须同时返回 success、verified=true 和 state=world.free；只有退出动作成功还不够。第二次前置失败、恢复失败或预算不足都会返回模型，不递归重放。

恢复状态机使用公共transition/RetryBudget：已识别地图、通知、任务/成就/活动/工作菜单优先用新鲜关闭目标，没有关闭目标时才对这些已知页面发送Escape；关闭控件明确禁用时等待。GET/RANK UP先处理当前弹层，不能点击后面的关闭按钮。未知页只允许一次重新发现，不盲按Escape或空白。最多6次退出/确认输入、默认30秒，连续三帧自由界面才完成；重复捕获时间的旧帧不能计入确认，verification_samples保留最后三帧状态及时间。输入前复核窗口焦点、位置和遮挡，F12或人工取消立即停止；输入发送后才发生的取消仍保留已发送记录，失败输入单独标记交付未知。

未知小游戏、对话/选项、刮奖券、多人匹配/成员确认、购买确认不由这个恢复器退出。当前只为daily_tasks声明自动恢复，不会把要求进入钓鱼轨道或强欲下注页的能力错误地“修复”为自由界面。强欲、厨房等后续可以按各自明确前置状态增加独立恢复器，不能仅凭错误文字猜目标。

已经发送领取、派遣、下注或实时输入后得到unknown，不添加可自动重试的前置错误标记。它仍交给顶层模型核对现场和结果。空日常选择不截图、不恢复；startup=true仍保留原有启动/聚焦路径。旧模型use_skill调用已登记能力时也走同一计划执行链；独立小游戏程序和local-daily入口保留原流程，不自动套此策略。

`recovery_attempt` 保存初始失败、恢复结果和重试次数；事件日志记录recovery_started、recovery_finished、step_retry_started。恢复确认只证明回到自由界面，不证明奖励到账。可在步骤设置 `"recovery":"none"` 让前置失败直接返回模型。

## 命令行

在项目根目录，以环境内 Python 调用（先将 `src` 加到 PYTHONPATH）：

```powershell
$env:PYTHONPATH = "$PWD/src"
.\.conda\python.exe -m modular_agent capabilities --domain hololive_dreams
.\.conda\python.exe -m modular_agent capability --capability hololive_dreams.kitchen
.\.conda\python.exe -m modular_agent execute-plan --task-plan config/task-plan.example.json
.\.conda\python.exe -m modular_agent execute-plan --task-plan config/task-plan.example.json --live --goal "钓鱼5轮，最多10分钟"
.\.conda\python.exe -m modular_agent plan-status --run-id <运行ID>
.\.conda\python.exe -m modular_agent plan-cancel --run-id <运行ID>
```

运行开始打印 ID。`runtime/task-plans/<ID>/state.json` 保存当前步骤和每步结果，`events.jsonl` 保存开始/参数/结束事实；实时子进程日志位于步骤目录。status/cancel 可从另一终端调用。新计划间使用 OS 互斥锁；手工启动的旧独立入口不自动受这把锁管理，运行实时引擎时应让它独占游戏输入。

不自动恢复或重放中断计划。进程崩溃可能留下 running 状态；状态文件是最后写入的事实，不证明进程仍存活。重新执行前核对游戏与日志，避免重复领取或下注。

## 验证和扩展

输入发送、控制结束、观察到结算、奖励入账是不同证据。各适配器沿用原场景门控、焦点/遮挡/停止检查；本层不增加新的 UI 点击策略。厨房、跳绳、单曲音游当前仍主要返回 unknown 和运行统计，不能因退出码0升级为 verified。多人演出的局数确认也不等于奖励数量核实。

增加能力时，同时添加接口条目和可信领域适配器及离线回归；manifest 不能指定可执行文件或任意导入路径。通用层负责接口、校验、计划和事实日志，领域层负责游戏条件与现有引擎调用。测试与生成工具仍在相邻 Game_agent_dev，不进入运行仓库。

本次验证为模拟模型、模拟电脑和离线回归；未对真实游戏发送输入，也未验证当前模型服务理解这些新接口的实际成功率。
