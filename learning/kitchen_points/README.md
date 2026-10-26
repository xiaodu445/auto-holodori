# 厨房点击点网络：首轮拟合基线

2026-10-22 用户确认12代表帧全部完整；264点、28类。已标complete并导出。
原始标注备份位于人工工作目录backups/before-training-complete-*；训练使用manifest快照，不随GUI改动。

## 模型与训练

MobileNetV3-Small ImageNet预训练前9个特征模块（到stride16），取stride4/8/16，
64通道自顶向下加法融合；类别热力图＋共享2通道偏移，输出stride4。
参数258422；输入ROI缩放为640×352，RGB及ImageNet均值方差标准化。
热力图modified focal loss＋正样本smooth L1偏移；ignore区域屏蔽负样本损失。
点碰撞检测、ROI边界检查、固定seed17；预训练BN统计冻结，参数仍微调。
AdamW lr0.001、cosine到0.00003、batch4、300epochs。
本轮无增强、无随机拆分，仅验证对已标样本的拟合，不能报告泛化性能。
环境复用learning/jump_rope_yolo/.venv，PyTorch2.7.1+cu128、torchvision0.22.1、RTX5060。
预训练来源：https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth（下载校验hash）。

结果目录：runs/baseline-20261022。
- best.pt：权重、类别顺序、预处理配置。
- model.onnx：opset17固定batch1，不含截图/预处理/峰值解码。
- config.json：模型配置；manifest-snapshot.json：本轮标签快照。
- history.jsonl、training-fit.json、summary.json：训练日志及拟合指标。
- fit-*.jpg：训练帧预测；unlabeled-2000/4300.jpg：同局未训练帧的定性预览。
- runtime-verification.json：真实12帧ONNX数值一致性、CPU推理基准。

训练集阈值0.3、同类一对一匹配半径原图12像素：264/264，预测264点。
这不是目标可见区域或真实点击命中验证。未训练4300帧可见把黄瓜错判成手套/面条锅，
并有多处漏检，说明当前基线过拟合，不能自动点击。
下一轮需要旋转/几何增强同步变换点和ignore区域，补充多对局样本及独立验证集。

ONNX约1.00MiB；本机CPU四线程，预热20、测100次，中位8.48ms、P95 9.72ms。
仅模型推理，不含截图、缩放、后处理、输入或动画等待。
真实图最大数值误差：logits约0.00090，offset约0.000027。

## 执行（在D:/Code/Codex）

训练：
Game_agent/learning/jump_rope_yolo/.venv/Scripts/python.exe Game_agent/learning/kitchen_points/train.py --manifest Game_agent/runtime/kitchen/manual-labeling/20261021-212928-866150/dataset/manifest.json --output Game_agent/learning/kitchen_points/runs/新实验名 --weights Game_agent/learning/kitchen_points/weights/mobilenet_v3_small-047dcff4.pth --epochs 300

离线预测：
Game_agent/.conda/python.exe Game_agent/learning/kitchen_points/predict.py --model-dir Game_agent/learning/kitchen_points/runs/baseline-20261022 --video Game_agent/runtime/kitchen/recordings/20261021-212928-866150/screen.avi --frame 4300 --output Game_agent/runtime/kitchen/prediction-4300

predict.py只需OpenCV、NumPy、ONNX Runtime，不需PyTorch，不发送输入。
输出坐标为完整视频/图像像素；score未经校准，不是点击成功概率。
训练测试4项：点偏移/碰撞、忽略区损失屏蔽、解码类别坐标、网络stride；1epoch烟测及300epoch实跑通过。
