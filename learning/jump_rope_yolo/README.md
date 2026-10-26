# 跳绳稳定版（2026-10-16）

本版保留用户实机认可的跳跃及自动循环行为，未启用“死亡后分数补偿”草案。

## 使用入口

- `run_game_jump_loop.cmd`：自动跳绳与结算循环；`run_game_jump.cmd` 是同一版程序的兼容入口。
- F8：开始/暂停，F9：清零并暂停，F10：保存最近3秒画面/掩膜/参数，F12：退出。
- `open_failure_clips.cmd`：失败片段审查。
- 项目根目录 `record_jump_rope.cmd`：独立完整录像工具，不发送游戏输入。

阶段由绳子危险经过计数决定，10/30/50/70切换，阶段5锁定。低空往返每方向计一次。
当前仍可能因偶发死亡或失联漏计；这是稳定版本的已知限制，本轮没有改动这个行为。
阶段1–4默认13列/0.025误差/250ms外推；阶段4左右摇单独10列/0.035/400ms；阶段5同样放宽。
阶段3–4低空后向前提前100ms，阶段5全模式提前50ms。YOLO阈值0.03。
结算循环逐页确认，点击至少间隔2秒；新局自动清零。分数在 `results/round-scores/scores.csv`，保留结算截图与待复核记录。

## 保留资产

- 当前模型：`runs/temporal-history-07-late/weights/last.pt`。
- 当前引擎：`engines/history-07-late-960-fp16-nms/history-07-late.engine`。
- 训练集：`datasets/temporal-trial-07`；对应387张原始训练/历史帧保留在根目录 runtime/jump-rope/frame-review。
- 一份完整录像：`runtime/jump-rope/recordings/20261006-115004-094950/screen.avi`。
- 当前失败片段、分数记录及本日运行日志保留；旧输出在精简前的稳定备份包中。

## 升级工具

命令在本目录终端执行；均不自动启动游戏，也不自动启用新权重。

```
upgrade.cmd check
upgrade.cmd train --name 08 --epochs 30 --batch 4
upgrade.cmd export --name history-08-test --weights runs/temporal-history-08/weights/last.pt
upgrade.cmd templates
```

训练明确以当前07权重初始化并生成预测历史，可用 --prior-weights 指定其他教师；不会冒充已经缺失的control05原始实验。
`run_temporal_trial.py` 和 `rope_continuity_loss.py` 保留训练及独立评估逻辑；不要混用人工历史掩膜和网络输入。
升级前用新实验名，先检查评估和导出结果，再手动决定是否替换当前引擎；当前运行引擎路径固定于 game_jump_live.py。

## 审查与标注

`results/rope-late-occlusion-annotation-07/index.html` 是保留的当前标注页面。
为其他录像生成全新标注页面：

```
.venv\Scripts\python.exe annotation_tool.py --video ../../runtime/jump-rope/recordings/20261006-115004-094950/screen.avi --frames 600,601,602 --output results/annotations-08
```

生成页嵌入图片，支持画绳子、遮挡属性、不确定区域及JSON导入导出。新标注需审核、转换并合并到训练集，不能仅把导出JSON当成训练标签。

## 备份和迁移

Python环境及下载缓存不放进源码资产包；本机环境保留原位。
新机器需要Python3.12、NVIDIA驱动及CUDA版PyTorch；执行本目录 `install_environment.ps1` 安装锁定环境。
TensorRT引擎与GPU/运行时相关，换机器应从保留的PT重新导出并检查。
`package_project.py` 生成包含模型、数据、工具和录像的ZIP，逐文件校验SHA256；压缩包包含MANIFEST.json，外部有压缩包校验文件。


工作副本试调（2026-10-16）：阶段4低空后向前额外提前量100ms→50ms，窗口由参考前135ms改为前85ms，末端仍为后35ms。其他阶段/方向不变。STABLE_BASELINE.json及已封存ZIP记录的是试调前稳定版，未被覆盖。

工作副本试调：阶段3低空后向前参考相位0.886276→0.7705，取消该阶段额外100ms提前；通过配置jump_progress_nodes_by_template覆盖加载，原始模板及目录SHA不变。普通前35ms/后35ms窗口保留，绳子计数使用同一覆盖后的节点。封存稳定ZIP未改动。

稳定版更新：阶段3最终修复已纳入新的stable-2026-10-16-stage3-fixed快照，STABLE_BASELINE.json现已更新；旧090429/091025包仍为历史版本，不要作为最新版本使用。
