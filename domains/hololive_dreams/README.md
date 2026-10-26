# Domain: hololive_dreams

本目录只存 `hololive_dreams` 的专属资源。通用模型/API 配置位于项目顶层 `config/`，通用 CV 与屏幕捕获代码位于 `src/modular_agent/perception/`。

## 本地组件与识别接口

模型目录已有强欲之牌入口树，通用启动树在顶层agent模块。用户已确认链式调用成功。现有组件保持full识别；指定目标/区域和独立开关见 ../../docs/general-vision.md，供后续状态化优化。启动经验在 ../../knowledge/global/hololive_dreams_startup.md。
