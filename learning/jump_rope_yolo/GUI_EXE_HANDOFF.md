# 跳绳 GUI / EXE 发布交接（2026-10-16）

## 目标与边界

用户准备向群友发布，目标是下载一个EXE即可启动使用，有中文GUI、无需手动安装Python或敲命令。允许首次运行自动解压运行库、建立缓存，但界面应说明进度。
用户没有指定C#；C#只是讨论过的选项，不要未经评估就全面重写。先比较纯推理发布方案的模型输出一致性、端到端延迟、硬件覆盖及实际包体，再选实现。
在独立目录 `D:/Code/Codex/JumpRopeRelease` 开发发布版，保留现有Game_agent和封存包。用户反复要求不要自行启动游戏/实机自动化；离线验证可以进行，实机由用户手动启动。
此任务是GUI和可执行文件分发，不继续调跳跃策略。产出本地可分发EXE/安装包、使用说明、兼容范围、校验文件。

## 当前可信版本：以工作目录为准

项目根：`D:/Code/Codex/Game_agent`。
当前运行代码：`learning/jump_rope_yolo`。
入口：`run_game_jump_loop.cmd` / `run_game_jump.cmd`（同一程序、自动循环由配置启用）。
用户最新实机确认“问题解决了”的版本，包含下述阶段3修复。

重要：`D:/Code/Codex/packages/jump-rope-stable-20261016-090429.zip` 是清理前快照；
`jump-rope-compact-20261016-091025.zip` 是精简包。两者均早于阶段3最终修复与阶段4提前量调整！
不要把旧ZIP、README早期段落或STABLE_BASELINE.json误认为当前最终参数。STABLE_BASELINE.json现已更新为stable-2026-10-16-stage3-fixed；最新稳定包位置见D:/Code/Codex/packages/latest-stable-snapshot.json。
本交接旁的 CURRENT_RELEASE_BASELINE.json 记录当前关键文件哈希；packages 内的 gui-handoff-current-overlay ZIP包含当前源码/配置覆盖层，可叠加在精简包上恢复。

## 当前有效行为和参数

- YOLO置信度0.03；输入960方形、batch1、rect=False，FP16，retina_masks=True。
- 两帧预测历史掩膜叠加RGB；编码必须与 `run_temporal_trial.composite` 一致，不能把人工标签作为运行输入。
- 模型输出经下游模板时钟匹配后按空格；不能只靠单点绳高决定方向。
- 阶段主要由 RopeProgress 的危险经过次数决定，10/30/50/70切换，stage5锁定；普通旋转每圈一次，低空往返每方向一次。
- “死亡后用OCR补偿圈数”只写过草案，用户要求先留住稳定版，已撤回。不要擅自启用。草案独立在packages/unapplied-count-correction-*。
- 默认匹配：13有效列、形状误差0.025、外推250ms；stage4低空摇及stage5：10列、0.035、400ms。
- 基础触发窗口：目标前35ms至后35ms。35ms空格脉冲，不额外限制重复跳跃；正在按下的脉冲不堆叠。
- 阶段3低空摇：运行配置 jump_progress_nodes_by_template 覆盖为 [0.2981181391370996, 0.7705]。后向前节点恢复0.7705，额外提前0ms。用户已明确反馈该修复解决问题。
- 阶段4低空摇：仍用旧几何先验，后向前额外提前50ms（最早前85ms），另一方向无额外提前。
- 阶段5全部模式额外提前50ms（最早前85ms）。
- 模板文件本体和目录SHA没有因阶段3修复被改写：JumpClock读取并校验后应用配置覆盖。发布版必须保留这个覆盖；绳子计数也使用覆盖后的节点。
- F8开始/暂停且保留圈数；F9清零并暂停；F10只保存最近3秒；F12退出。暂停/退出/切场要释放空格。
- 游戏窗口标题 hololive-Dreams（当前代码比较时lower），捕获客户区并核对窗口边界/遮挡，点击坐标由客户区相对位置转换。

## 自动结算循环与记录

round_loop.py + loop_assets 的参考图识别四页：分数结果→下一步、奖励→OK、活动结果→下一步、跳绳菜单→游玩。
稳定0.8秒，分数页1.2秒；点击间隔2秒，同页3次仍不离开就等待人工检查。过渡页等待且停止跳跃。
点击游玩后确认计数/爱心HUD连续0.5秒出现，清空时钟、圈数和历史掩膜，开始新局。
每局最终分数来自结算大数字，不是最佳分数，也不是内部按键次数。多帧确认；不确定留空并标记needs_review，保存截图。
输出：results/round-scores/scores.csv、scores.jsonl、每局截图和JSON。
失败审查：failure_capture.py，仅F10手动保存前3秒，含帧、无损掩膜、候选/已接受相位、输入边沿、配置、HTML逐帧页。不要重新开启自动疑似死亡判定。

## 文件与资源

必需代码：game_jump_live.py、game_jump_logic.py、run_temporal_trial.py（composite）、live_video_preview.py（ROI/回放）、counter_reader.py、count_digits_complete_v2.json、round_loop.py、loop_assets、failure_capture.py、game_jump_config.json。
现有代码依赖ROOT/src/modular_agent中的模板、截图和Windows输入实现；不要只复制learning目录就假定独立运行。
当前模型：runs/temporal-history-07-late/weights/last.pt（约6MB）。
当前引擎：engines/history-07-late-960-fp16-nms/history-07-late.engine。
模板目录由config.catalog指定：domains/hololive_dreams/data/jump_rope_template_library/generated/stages_1_5_yolo07_trial/catalog.json，实际引用其他生成目录的文件，需要保留路径及SHA校验。
本机跳绳环境：learning/jump_rope_yolo/.venv/Scripts/python.exe；核心/录像环境：项目根.conda/python.exe。
当前机器RTX5060 8GB。现有标准TensorRT引擎不可假定跨所有显卡通用。

开发资产保留：训练集datasets/temporal-trial-07；387张训练/历史原始帧在runtime/jump-rope/frame-review/recording-20261006-115004-094950/exact-frames。
保留完整录像：runtime/jump-rope/recordings/20261006-115004-094950/screen.avi，约1.17GB；这是开发资产，群友运行包不要附带。
录像工具：根目录record_jump_rope.cmd和src/modular_agent/realtime/record_jump_rope.py。
升级：upgrade.py / upgrade.cmd，check、train、export、templates；新权重不自动启用。
标注：annotation_tool.py、rope_mask_visibility_review.html/js及当前results/rope-late-occlusion-annotation-07/index.html。
依赖：requirements-runtime-lock.txt是可迁移的实际安装版本锁；旧requirements-installed.txt有F盘wheel地址，不要用于新机器直接安装。
install_environment.ps1是开发环境安装辅助脚本，不是最终面向群友的用户体验。

## 发布方案调研结论：还未构建，体积与性能不可当成已验证

当前程序经ultralytics调用标准TensorRT，同时带torch及大量开发依赖；不要直接冻结整个环境后宣称数GB不可避免。
可以在开发机导出，发布时只带模型和纯推理运行库，复现必要预处理/后处理：缩放填充、颜色/数值顺序、NMS、分割原型与掩膜缩放裁剪、历史叠加。曾有检测头分支差异问题，现有基线是one-to-many/external NMS，metadata.end2end=False。
候选：ONNX Runtime Windows GPU（WinML/DirectML）、NCNN/Vulkan、TensorRT for RTX；不能把“支持模型”当成端到端延迟已满足跳绳。
C# GUI+ONNX是常见路线，但Python轻量推理也能缩包。若换后端，先验证相同输入下的掩膜一致性、方向/相位/触发输出，再做GUI集成。
NVIDIA TensorRT for RTX不同于当前标准TensorRT：官方运行库小于200MB，有RTX本机JIT，仍需核对显卡/驱动/算子支持；这个数字不是最终应用包体。
来源：
https://docs.nvidia.com/deeplearning/tensorrt-rtx/latest/index.html
https://docs.nvidia.com/deeplearning/tensorrt-rtx/latest/inference-library/porting.html
https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html
https://onnxruntime.ai/docs/build/custom.html
https://github.com/nihui/waifu2x-ncnn-vulkan
https://github.com/NickSwardh/YoloDotNet
https://github.com/Tencent/ncnn/wiki/build-minimal-library

## GUI建议（可以自主完善）

中文界面：选择/刷新游戏窗口、开始/暂停、重置圈数、保存3秒片段、退出；显示硬件/推理后端、阶段/圈数、运行/等待页面状态、每局分数列表；打开分数与审查目录。
显示首次准备/引擎生成进度和兼容检查结果，运行数据保存到用户可写目录，避免从只读解压/安装目录失败。快捷键行为和GUI状态必须一致。
分发包仅包含运行必需项，训练集/录像/训练工具留在开发包。单EXE可以是自解压或安装启动器，首次启动会落地依赖，不要承诺运行时永远没有外部文件。

## 验证与交付

当前完整离线检查：39项通过，阶段3最终修复已获用户实机成功反馈。测试位于learning/jump_rope_yolo/test_*.py。
发布版至少验证：相同掩膜下相同决策；后端转换的一致性和真实端到端时延；暂停/退出释放按键；新局重置；四页循环；分数与F10审查；离线/首次运行/不可写目录和不兼容硬件的明确信息。
保留当前稳定版，发布成果与其分开。不要自动启动游戏做实机验证；需要实机时给用户入口和具体验证步骤。


稳定版同步：已按用户要求将当前阶段3修复纳入新稳定包，旧ZIP仅作回退。请用packages/latest-stable-snapshot.json定位最新包，以当前配置和基线哈希为准。
