# 本地屏幕感知与人工模板库

第一层感知不需要 LLM：MSS 只读截图，OpenCV 在本机执行模板匹配，并输出结构化 JSON。它适合固定或变化较小的游戏 UI、图标和按钮。

```text
screen/image → OpenCV template matching → Detection JSON → State / Router
                                      ↑
                        人工添加最小 UI 截图 + 人工验证反馈
```

## 工作流

```powershell
# 1. 创建专门领域，并添加稳定 UI 的小截图（PNG）
python -m modular_agent domain-init --domain game_x
python -m modular_agent vision-add-template --domain game_x --name reward_button --image .\samples\reward.png --environment game_x --threshold 0.90 --notes "主界面奖励按钮"

# 2. 优先离线扫描截图
python -m modular_agent vision-scan --domain game_x --image .\samples\game_screen.png --environment game_x

# 3. 或只读扫描当前屏幕；不会点击或上传截图
python -m modular_agent vision-scan --domain game_x --environment game_x --monitor 1

# 4. 人工反馈，更新模板可靠性
python -m modular_agent vision-feedback --domain game_x --name reward_button --accepted
python -m modular_agent vision-feedback --domain game_x --name reward_button --rejected
```

`vision-scan` 输出单行 JSON。`bbox` 是 `[left, top, right, bottom]`，原点是输入图像左上角：

```json
{"environment":"game_x","detections":[{"template_id":"uuid","label":"reward_button","confidence":0.9721,"bbox":[820,740,980,810],"environment":"game_x"}]}
```

## 持续学习的安全边界

- 新模板只能由人工明确添加；原图被复制到 `domains/<domain>/vision_library/images/` 并记录 SHA-256。
- 人工确认/驳回只更新成功与失败统计，`reliability` 是人工确认成功率。
- 不会自动存整屏截图或把单次偶然命中注册为 Skill，避免知识污染。
- 后续可按可靠性、分辨率和游戏版本由 Router 选择多版本模板。

模板适合已知稳定 UI。布局变化、文字变化或复杂对象可按成本逐级加入 OCR、特征匹配、检测模型，最后才升级 General Agent。

## 顶层通用感知

窗口、按钮、文字、知识匹配的统一输出已实现，见 [general-vision.md](general-vision.md)。现有 vision-scan 保留原有简版模板输出；使用 observe 获取完整结构化结果。
