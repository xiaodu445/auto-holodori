# 本机环境安装记录

日期：2026-10-15。项目：D:\Code\Codex\Game_agent。

## 已安装

- Miniconda：D:\Code\Codex\setup\miniconda；官方签名验证通过，未添加到系统 PATH。
- 通用环境：.conda\python.exe，Python 3.12.15，已安装 .[vision,recording,mcp]。
- 跳绳环境：learning\jump_rope_yolo\.venv\Scripts\python.exe。
- GPU：RTX 5060 8GB，驱动596.49。PyTorch 2.7.1+cu128、torchvision 0.22.1+cu128，CUDA矩阵计算通过。
- ultralytics 8.4.177、numpy 2.2.6、opencv-python 5.0.0.93、pillow 12.3.0、mss 10.2.0。
- ONNX 1.19.1、onnxslim 0.1.98、onnxruntime 1.31.0。
- TensorRT 10.16.1.11（Python绑定、CUDA12运行库及封装）已安装；pip check与GPU构建器检查通过。

顶层依赖按pyproject.toml的版本范围解析，未严格复现旧环境的所有传递依赖；实际清单见 ..\setup\requirements-core-local.txt。

## 已完成验证

两个ZIP及全部2842个解压文件通过SHA256校验。
通用环境pip check、模块导入、CLI帮助、Tcl 8.6.13初始化通过。
YOLO07使用07模型初始化历史，离线处理录像7002–7009帧通过，8帧worker耗时中位数23.21ms（含解码与历史处理，不代表实机帧率）。报告：learning/jump_rope_yolo/results/migration-local-pytorch-smoke/smoke.json。
独立跳跃逻辑3项测试通过。未验证图形预览界面，未发送游戏按键。

## 通用工程测试待处理项

694项：686项通过、6项失败、2项报错。日志：..\setup\core-tests-final.log。
对8项未通过测试以UTF-8复核后，旧跳绳人工标签读取通过，其余仍为6项失败、1项报错。复核：..\setup\core-failures-utf8.log。
涉及每日任务、High&Low、Agent技能反馈和模板匹配。不视作整套测试通过；尚未确定各项差异是否由新环境引起。
测试启动时将stdin.isatty设为False，防止Windows控制台编辑器绕过模拟input并等待实际按键；工程源码未修改。

中文Windows运行相关工具时，可在PowerShell先设置：

    $env:PYTHONUTF8 = '1'

真实游戏成功率、间歇卡顿尚未验证或修复。模型服务凭据仍需重新配置。

## TensorRT最终验证

运行库2,206,065,494字节，官方索引SHA256匹配：ed0d4536f1322aa2f76da54feb3f9bd2d14d89e4325cef02165a98f3a2c1a493。
本机07引擎已生成：learning/jump_rope_yolo/engines/history-07-late-960-fp16-nms/history-07-late.engine。
固定batch1、960方形、FP16、workspace 1GiB，元数据确认end2end=False。源权重哈希保持不变，导出信息见同目录export.json；详细日志见 ..\setup\tensorrt-export.log。
TensorRT离线处理7002–7009帧通过，8帧worker耗时中位数11.52ms，含解码与历史处理，不代表实机帧率，也不构成人工准确率或完整视频一致性评估。
报告：learning/jump_rope_yolo/results/migration-local-tensorrt-smoke/smoke.json。
跳绳环境最终版本清单：..\setup\requirements-jump-rope-local.txt。

## 使用

- TensorRT录像预览：learning\jump_rope_yolo\view_history.cmd。
- PyTorch录像预览：learning\jump_rope_yolo\view_history_pytorch.cmd。
- 只判断入口：learning\jump_rope_yolo\view_game_jump.cmd；本次未在游戏中启用。

安装包、下载分段、缓存和原迁移ZIP均保留。本次没有运行训练或发送游戏输入。


## 阶段5试验接入

07实机默认目录已增加7个阶段5候选，原1–4的35个目录项保持不变。6项逻辑测试通过，240帧录像回放完成并提出5次建议，未核对成功率。原配置备份为learning/jump_rope_yolo/game_jump_config_stages1_4.json。详见README_game_jump_v1.md。

## 取消等待后的试验版本

2026-10-15：删除150ms初始化/换档禁跳及300ms重复跳跃抑制；YOLO confidence 0.05→0.03。7项逻辑检查通过，阶段5同一240帧离线片段回放完成。短脉冲发送器继续保证已按下的35ms脉冲不叠加；窗口、画面年龄和有效观测检查保留。多次建议触发不视作成功跳跃统计。


## 失败片段自动记录

现有实机入口默认开启计数停滞监测，后台缓存最高60FPS、96MiB。稳定计数变化至少两次后，停滞2秒保存最后一次变化前6秒至触发时刻的画面和同步参数，输出统一在learning/jump_rope_yolo/results/failure-clips。F10手动保存，F9可补存未自动保存的本轮尾部。默认不再写整局events.jsonl，保存的片段含全部决策行。12项记录检查、7项跳跃检查通过；900帧离线回放无误报、0队列丢帧。此次没有启动实机程序。


## 低空后向前提前试调

阶段3、4后向前触发窗口额外提前100ms，保留原始按键时刻；其他方向和阶段不调整。配置low_swing_back_to_front_extra_early_seconds_by_stage。注意阶段3人工校准后的第二个按键点才对应后向前。10项跳跃检查及12项记录检查通过；未启动实机程序。


## 当前片段设置覆盖

旧集中片段已清空。自动死亡判定和F9补存关闭，只按F10保存最近3秒。配置auto_detect=false、save_on_reset=false、manual_seconds=3。13项检查通过，未启动或停止实机程序。
