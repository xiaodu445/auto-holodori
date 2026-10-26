# B / B2：整绳直接拟合路线

共用文件jump_rope_whole.py；默认whole_shape_model=false是v2，--whole-rope --whole-shape单独选择v3。两者均只判断，直接API/CLI拒绝live、experimental-live、test-space。

v2：41个参数曲线点、5阶正弦残差、两端姿势模板/位置先验；当前边缘与运动支持拟合、光流位移先作平滑形变再加连续性检查。无完整支持时可短时利用局部片段；120ms之后恢复搜索，重新取得需3帧一致候选，track_id增加。缺点是端点会估错、候选可黏背景、恢复频繁。

v3：6个有界形状/端点参数，实际参考弧形；灰度亮/暗细条特征、静止亮度范围过滤及角色身体核心位置先验排除。批量计算候选视觉证据。并未强于v2，默认关闭。

参数：jump_rope_config.json.whole_continuity（速度6、加速度90、位置噪声0.008，归一化二维单位）。形状/位置容差仍是实验值。端点模板source=measured是姿势模板估计，slot_prior不是实际握绳位置。whole_point_states的绿色只表示当前位置附近有当前支持，橙色历史推算、灰色未知；motion_phase是屏幕升降，不是3D前后危险阶段。

对照：v2回放979/4010接受拟合、164次获取；v3为672/4010、149次。样本/阈值不同，不可当准确率。v3在20秒黄色样帧贴合、55秒拒绝错误背景，但14秒误差更大、32秒掉落遮挡仍丢失。报告whole-v2-report.json、whole-shape-report.json；视频whole-rope-continuity.avi、whole-rope-shape.avi。v3单独识别均值16.68ms/p95 21.50ms，不含采集预览，未达稳定60FPS。

当前保留意义：提供直接画面测量、候选/片段及端点误差诊断；可供C重新定位或验证固定轨迹覆盖。切换思路不会删除本路线。运行入口见上级README。
