# browserapi v1 设计稿

把 `kasm/chrome` 从"给人用的流式浏览器容器"扩展成**服务化浏览器操作体**(Browser Operator):
一个既能被 Python 代码直接驱动、也能作为 HTTP/WS 服务被多租户调用的浏览器执行单元,
并且**智能体在里面做过的每一步都可被实时观看、事后回放、结构化审计**。

## 一句话定位

> 不是"又一个浏览器自动化库",而是**给 Agent 用的、自带取证能力的浏览器运行时**。
> 差异点:人能实时看见并随时抢方向盘(KasmVNC),Agent 的每一步都有观测-动作-效果三元组留痕。

## 阅读顺序

| 文档 | 内容 | 读者 |
| --- | --- | --- |
| [00-goals-and-scope.md](00-goals-and-scope.md) | 目标 / 非目标 / 场景 / 术语 | 全体 |
| [01-architecture.md](01-architecture.md) | 总体架构、部署形态、组件职责 | 全体 |
| [02-container-runtime.md](02-container-runtime.md) | kasm/chrome 基座改造、容器内 `agentd` | 实现 |
| [03-action-protocol.md](03-action-protocol.md) | **核心契约**:观测模型 + 动作空间 + 定位策略 | 全体 |
| [04-trajectory-model.md](04-trajectory-model.md) | **核心诉求**:操作路径的记录、直播、回放、审计 | 全体 |
| [05-python-sdk.md](05-python-sdk.md) | Python lib 模式 API | 使用方 |
| [06-api-service.md](06-api-service.md) | API service 模式(REST/WS) | 使用方 / 集成 |
| [07-security-and-ops.md](07-security-and-ops.md) | 隔离、凭证、出网管控、容量与回收 | 运维 / 安全 |
| [08-roadmap-and-adr.md](08-roadmap-and-adr.md) | 里程碑、决策记录、开放问题 | 全体 |

## 状态

设计稿(work in progress),尚未实现。文中所有代码/JSON 均为**设计示意**,不是已存在的接口。
涉及 `kasmweb/chrome` 镜像内部路径与环境变量的部分,标注为「基线假设」,实现前需按锁定的镜像 tag 复核。

## 三条贯穿全文的设计原则

1. **一套协议,两种外壳。** lib 与 service 共用同一份动作/观测/轨迹 schema,lib 默认是 service 的客户端。
2. **可观测优先于可编程。** 任何新增动作,必须先回答"它在回放时长什么样",再回答"它的函数签名是什么"。
3. **人是最后的兜底通道。** 任何 Agent 能做的事,人都能在同一个会话里接管着做完,且接管本身也进轨迹。
