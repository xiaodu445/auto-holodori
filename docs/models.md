# 模型配置与切换

当前默认顶层模型是 Kimi `kimi-k2.6`，通过官方 `https://api.moonshot.cn/v1/chat/completions` 接口调用，thinking=disabled，JSON 输出。已用提供的密钥完成真实联网测试，也验证了模型面对“启动hololivedreams”会先请求 observe。这些测试未发送桌面信息或截图，未执行启动动作。

## 使用

```powershell
.\start_agent.cmd
```

终端会显示当前 provider 和模型。输入 `启动hololivedreams` 开始模型驱动循环。F12 紧急停止，`/quit` 退出。

任务间切换模型：

```text
/models
/model kimi
/model kimi-thinking
/model kimi-k3
/model openai
/model mock
/model
```

| 配置名 | 模型/模式 |
| --- | --- |
| kimi | kimi-k2.6，非思考模式；默认，已验证 |
| kimi-thinking | kimi-k2.6，思考模式；尚未联网验证 |
| kimi-k3 | kimi-k3，使用服务默认思考参数；尚未联网验证 |
| openai | OpenAI Responses 模型配置，需要自己的 OPENAI_API_KEY 和可用模型名 |
| mock | 固定模拟响应，不规划或操作 |

切换会更新 `config/model.json`，下次启动沿用。只在任务之间切换，当前任务不会中途换模型。启动时临时选择（不保存）：

```powershell
.\start_agent.cmd --model-profile kimi-thinking
```

可在 `config/models.json` 增加/修改配置名。每项指定 provider、model、base_url、api_key_env 等。支持 mock、openai_responses 和 openai_chat。API 协议及参数必须与服务匹配；不是任何服务都能只改模型名。

## 密钥

提供的 Kimi 密钥已使用 Windows DPAPI 加密，文件位于 `runtime/secrets/moonshot.dpapi`，绑定当前桌面 Windows 用户。runtime 被排除在版本管理之外。配置只保存加密文件路径，不包含明文密钥。环境变量 MOONSHOT_API_KEY 如存在，优先于加密文件。

更换密钥时在本机运行下面的命令，输入会隐藏，不需要把新密钥发到聊天：

```powershell
$env:PYTHONPATH = "src"
.\.conda\python.exe -m modular_agent.credentials --name moonshot
```

聊天中已经出现的旧密钥建议在 Kimi 控制台撤销后换新。加密文件只能在加密它的 Windows 账户下解密；复制到其他账户/电脑时需重新配置。不要用沙箱账户覆盖桌面用户的凭据。

接口错误不会打印 Authorization、密钥或提供商原始响应内容。401 表示认证失败，429 表示限流或额度问题；账号费用/余额由服务端决定。

## 验证

66 项测试通过，包含 Chat Completions 请求构造、JSON 输出解析、截断拒绝、HTTP 错误脱敏、加密读写、模型切换及配置持久化。另已完成 Kimi 的真实连通性和 Agent 首次决策协议测试。

官方接口实际返回的可用模型包括 kimi-k3、kimi-k2.7-code、kimi-k2.7-code-highspeed、kimi-k2.6；最初尝试的 kimi-k2.5 返回 404，因此当前不配置为可用选项。可用性以账号和服务的实时返回为准。

整个游戏启动流程仍需用户测试，其他模型配置未做联网验证。

官方资料：
- https://platform.kimi.com/docs/get-api-key
- https://huggingface.co/moonshotai/Kimi-K2.6


## 429 限流处理（2026-10-02）

当前 Kimi 请求至少间隔 2 秒。临时 429 默认最多重试 3 次，等待 2、4、8 秒；优先遵守 Retry-After。服务要求等待超过 30 秒时不会提前重试，会提示用户等待后重新提交。

错误响应在本地解析分类：RPM、TPM、并发、服务过载、每日限额、余额/额度不足。原始响应和账号信息不回显。余额/额度不足、每日限额不自动重试；需要检查控制台或等待重置。旧版泛化的错误消息不能确定具体原因，应重启新版 Agent 后查看分类提示。

F12 会取消后续请求和重试等待。正在进行的网络请求可能继续等待，但返回后不执行操作。此策略只缓解暂时限流，不能增加账号限额；多个 Agent 进程仍可能共享账号限额，当前节流只作用于单个模型客户端。

排查来源：https://www.kimi.ai/help/kimi-api/api-troubleshooting


## 请求等待与重试

每次请求都会记录当前尝试次数、单次超时，等待响应时每 10 秒记录进度。网络断连、超时、HTTP 408/429/500/502/503/504 会按配置有限重试；默认最多重试 3 次（总共 4 次），退避等待 2、4、8 秒。余额不足、每日额度耗尽、认证和参数错误不反复请求。服务器 Retry-After 仍优先遵守，超过最大等待时明确报错。

`timeout_seconds` 限制等待整次响应的时间，而不仅是单次 socket 读取；`/stop` 或 F12 取消本地等待并阻止返回结果执行操作。远端已接收的请求不一定能取消，迟到结果会被忽略，可能仍被供应商计费。所有尝试失败后结束本任务，命令行仍接受新任务。
