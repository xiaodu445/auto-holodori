# Hololive Dreams GUI 发布说明

首版发布壳只做两件事：

1. 单曲打歌：调用现有 `domains/hololive_dreams/models/rhythm_game.py` 的 `run(...)`，不复制或调整音符算法；GUI 默认观察/干跑，实时按键需显式勾选。
2. 多人演出：只展示已确认流程与目标局数字段，当前不执行任何菜单输入；没有把多人循环伪装成已实现。

## 离线构建

在 `Game_agent` 目录执行：

```powershell
python release/build_release.py
```

这会生成隔离的 `release/output/HololiveDreamsGUI-source`，不覆盖用户配置、不启动游戏。

安装了 PyInstaller 后再执行：

```powershell
python release/build_release.py --pyinstaller
```

当前环境的项目 Python 若没有 PyInstaller，构建脚本会保留源发布包并明确报告未生成 EXE；不自动联网安装依赖。

## 已知边界

- 当前引擎默认结果仍是 `unknown`；GUI 不把输入 API 成功或引擎退出当作歌曲结算/Perfect。
- 曲终结算识别、菜单让权和多人自动循环尚未实现；因此 GUI 不会自动接管菜单。
- 未做真实游戏按键测试；流速/间隔识别仍处于排查状态。
- `run(...)` 的 finally 清理协议负责停止调度、释放按键；GUI 停止按钮只请求该协议结束，并等待清理完成。

源码调试可直接运行 `run_hololive_dreams_gui.cmd`；它只启动 GUI，不自动寻找或操作游戏窗口。
