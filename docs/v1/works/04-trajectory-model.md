# 04 · 操作路径:轨迹模型与可见性

> 这是"让智能体的操作路径都能看到"的落地文档。
> 立场:**轨迹不是日志的副产品,而是系统的主产品之一。** 动作 API 的形状要服从轨迹的需要,不是反过来。

## 1. 四层模型

```
Run  ── 一次有始有终的任务(“预订 8/20 北京→上海机票”)
 ├── Step ── Agent 的一次决策周期
 │    ├── Observation   决策前它看到了什么
 │    ├── Reasoning     它想了什么(调用方可选上报)
 │    ├── Action[]      它决定做什么
 │    └── Effect[]      实际发生了什么
 ├── Step ...
 ├── HumanSpan ── 人接管的一段区间(与 Step 同处一条时间线)
 └── Outcome ── done / failed / aborted / timeout,含结构化结果
```

选择 Step 作为主单位而不是 Action,是因为**Agent 的失败几乎总是决策失败,不是执行失败**。
把"看到什么 → 想了什么 → 做了什么 → 变成什么样"绑成一个不可分的四元组,
排查时才能直接指着某一步说"这里它判断错了"。

## 2. 数据结构

```jsonc
// Run
{
  "run_id": "run_01J9X...",
  "session_id": "ses_...",
  "tenant_id": "t_...",
  "goal": "预订 8/20 北京→上海机票,经济舱,上午出发",
  "agent": { "name": "travel-agent", "version": "v3.2.1", "model": "claude-opus-5" },
  "labels": { "env": "prod", "ticket": "OPS-2211" },
  "status": "failed",
  "outcome": {
    "kind": "failed",
    "category": "wrong_element",        // 见 §4 失败归因
    "message": "在第 12 步点击了『取消订单』",
    "result": null
  },
  "started_at": "...", "ended_at": "...", "duration_ms": 84120,
  "step_count": 14,
  "counters": { "actions": 31, "observations": 14, "errors": 2, "human_spans": 0 },
  "cost": { "screenshots": 28, "blob_bytes": 6412880 },
  "schema": { "action": "v1", "perception_profile": "v1" }
}

// Step
{
  "run_id": "run_...", "step_index": 12, "step_id": "stp_...",
  "started_at": "...", "duration_ms": 3120,
  "observation": { "$ref": "obs_..." },          // 完整结构见 03 §1
  "reasoning": {                                  // 全部可选,由调用方上报
    "thought": "购物车里已有一张票,现在需要确认支付",
    "plan": ["点击确认支付", "填写手机号", "提交"],
    "candidates": [ { "action": "click", "target_id": 8, "score": 0.62 } ],
    "model_call": { "model": "claude-opus-5", "input_tokens": 4210, "output_tokens": 180,
                    "latency_ms": 1840 }
  },
  "actions": [ /* 见 03 §2 */ ],
  "results": [ /* 见 03 §4 */ ],
  "status": "ok",
  "annotations": [ { "by": "reviewer@x", "kind": "error_here",
                     "text": "此处应点『确认支付』", "at": "..." } ]
}

// HumanSpan
{
  "run_id": "run_...", "span_id": "hsp_...", "after_step": 12,
  "actor": { "user": "ops@x", "reason": "验证码" },
  "started_at": "...", "ended_at": "...",
  "observed": {                                   // 人操作期间由 agentd 被动采集
    "navigations": ["/verify", "/checkout"],
    "form_submits": 1,
    "screenshots": ["blob://...", "blob://..."],  // 按 2s 或页面变化采样
    "video": "blob://...webm"                     // 可选:该区间的屏幕录像
  }
}
```

**`reasoning` 字段是本设计与普通自动化留痕的分水岭。** browserapi 不产生思考,
但它提供一个**思考与后果对齐的存放位置**——只有把 thought 和它引发的 effect 放在同一个 Step 里,
"操作路径"才是可解释的,否则只是一串点击记录。

## 3. 三种可见性

同一份轨迹,三种消费方式。三者共用同一批 blob,不重复存储。

### 3.1 Live —— 实时看
两条通道并行,回放器 UI 上下并置:

| 通道 | 内容 | 传输 |
| --- | --- | --- |
| **画面** | KasmVNC 实时桌面,真人视角 | 控制面签发一次性 token,浏览器直连容器 6901 |
| **事件** | 结构化事件流:每一步的 thought / action / effect | WS `/v1/runs/{rid}/events` |

看到的效果:**左边是浏览器在动,右边是"它现在在想什么、点了哪儿、结果如何"在滚动。**
这是 kasm 基座带来的、纯 headless 方案做不到的东西。

事件类型:
```
run.started        step.started      step.reasoning     action.dispatched
action.result      page.navigated    page.dialog        network.blocked
human.takeover     human.released    step.finished      run.finished
session.unhealthy
```
每个事件带 `seq`(单调递增)与 `run_id`,断线后按 `?after_seq=` 续传。

### 3.2 Replay —— 回放
纯静态资产即可播放(截图序列 + 轨迹 JSON),**不依赖容器还活着**。播放器布局:

```
┌───────────────────────────────────────┬──────────────────────────┐
│  截图(带元素框 + 本步动作高亮)        │  Step 12 / 14            │
│                                       │  ┌──────────────────────┐│
│      ┌──────────┐                     │  │ 💭 想: 需要确认支付  ││
│      │ 提交订单 │ ◄── 点击涟漪        │  ├──────────────────────┤│
│      └──────────┘                     │  │ ▶ click #8 "取消订单"││
│                                       │  │   ✓ 412ms            ││
│                                       │  ├──────────────────────┤│
│                                       │  │ ⚡ 导航 → /cancel     ││
│                                       │  │ ⚡ POST /api/cancel   ││
│                                       │  │ ⚡ DOM: 出现"已取消"  ││
│                                       │  └──────────────────────┘│
├───────────────────────────────────────┴──────────────────────────┤
│ ●──●──●──●──●──●──●──●──●──●──●──●──✕──●   [1x] ⏮ ⏯ ⏭  🔗分享  │
│ 1  2  3  4  5  6  7  8  9 10 11 12 13 14                          │
│                        └─ 人接管区间 ─┘                            │
└──────────────────────────────────────────────────────────────────┘
```

关键交互:
- 时间线上 **失败步标红、人接管区间加底色、`opaque` 动作(eval_js/坐标点击)加警示条**。
- 点任一步 → 左侧切到该步的观测截图,并叠加**本步动作的目标框与点击点**。
- 悬停元素框 → 显示 `role/name/signature`,可一键复制成定位表达式。
- **切换"Agent 视角 / 人类视角"**:前者显示带编号的标注图(它当时看到的),后者显示原图。
  这个切换非常关键——绝大多数"它为什么点错"的答案,在标注图上一眼就能看见。
- 支持在任意步**加批注**(`annotations`),批注可导出为评测标注。

### 3.3 Audit / Export —— 结构化审计
- `GET /v1/runs/{rid}?include=full` 返回完整轨迹 JSON。
- **导出格式**:
  - `bapi/v1`(原生 JSONL,一行一 Step,自带 blob 清单)
  - `otel`(每个 Run 一个 trace,Step 为 span,action 为子 span;属性对齐 GenAI 语义约定,便于进现有 APM)
  - `har`(仅网络层,给传统排查工具)
  - `bundle.zip`(轨迹 JSON + 全部 blob + 独立回放器 HTML,离线可看,用于给外部方提供操作证据)
- 保留策略与脱敏在 [07](07-security-and-ops.md)。

## 4. 失败归因

`outcome.category` 是一个**闭集**,让失败可统计、可做看板:

| 归因 | 含义 | 判定来源 |
| --- | --- | --- |
| `wrong_element` | 点/填了错的元素 | 通常靠人工或规则标注,非自动 |
| `element_not_found` | 找不到目标 | `target_not_found` 连续出现 |
| `page_changed` | 页面结构变化导致脚本失效 | 签名匹配率骤降 |
| `blocked` | 被验证码 / 风控 / 登录墙挡住 | 页面特征规则 |
| `permission_denied` | 被出网或动作策略拦 | `denied` |
| `timeout` | 整体或单步超时 | 超时统计 |
| `infra` | 容器/浏览器崩溃 | `page_crashed` / `session_gone` |
| `agent_gave_up` | Agent 主动 `fail` | 显式 |
| `wrong_result` | 流程走完但结果不对 | 外部校验回写 |

`wrong_result` 允许**事后回写**:任务当时"成功"了,几天后发现订错了,可以 `PATCH` 轨迹的 outcome
并附证据。轨迹因此是可修订的、带审计链的记录,而非只写一次的日志。

## 5. 轨迹的第二用途:不只是排查

同一份数据顺带解决三件事:

1. **评测集**:把一批 run 打上"期望结果"后即成 benchmark;新版本 Agent 重跑,
   按 §6 的路径对比自动指出行为差异。
2. **回归基线**:同一 goal 的历史成功路径可作为参考路径;偏离超过阈值触发关注。
3. **可复现脚本**:一条成功轨迹里的 action 序列 + `signature` 定位,可**降级导出成确定性脚本**
   (`run.to_script()`),把"每次都花 LLM token 试探"变成"稳定路径跑脚本,失败才回退到 Agent"。
   这条对生产成本影响很大,应作为 v1.1 的重点。

## 6. 路径对比(diff)

对比两条 run 的操作路径,输出**分叉点**:

```
run_A (v3.1, 成功)          run_B (v3.2, 失败)
 1 navigate /search    ═══   1 navigate /search
 2 type #kw "北京→上海" ═══   2 type #kw "北京→上海"
 3 click sig_a1(搜索)   ═══   3 click sig_a1(搜索)
 4 click sig_b7(上午)   ─┬─   4 click sig_c2(最低价)   ◄── 分叉点
 5 click sig_d4(预订)    │    5 click sig_d4(预订)
 ...                     │    6 fail: 座位无票
```
对齐键用 `signature`(而非元素编号,编号每次都变)。这让"新版本是从哪一步开始跑偏的"变成一个可点开的定位,
而不是两份日志肉眼比对。

## 7. 存储与成本

| 数据 | 存放 | 量级估算(单 run 14 步) |
| --- | --- | --- |
| Run/Step/Action 元数据 | PostgreSQL | ~50 KB |
| 截图(webp q75,1280×800) | 对象存储,sha256 内容寻址 | 标注图+原图 ≈ 28 × 120 KB ≈ 3.4 MB |
| DOM 快照(可选,gzip) | 对象存储 | ~200 KB/步,默认**只在失败步存** |
| HAR(可选) | 对象存储 | 默认关 |
| 屏幕录像(可选) | 对象存储 | 仅 human span 或显式开启 |

控制成本的三个开关:
1. **采样档位**:`capture_level: minimal | standard | forensic`
   (minimal 只存动作元数据与失败步截图;standard 如上表;forensic 全开含 HAR 与录像)。
   生产默认 `standard`,批量任务可降到 `minimal` 并对失败 run **自动重跑一次 forensic**。
2. **内容寻址去重**:静止页面的连续截图天然同 hash,不重复存。
3. **分级保留**:详见 [07](07-security-and-ops.md) §5。

## 8. 写入路径的可靠性

轨迹最有价值的部分往往是**崩溃前的最后几步**,而那正是最容易丢的。因此:

- agentd 先写本地 `spool`(append-only),再异步上传;上传成功才删。
- `step.finished` 是**同步 flush 点**:该步的 blob 与元数据确认落地后事件才发出。
  单步多花 10–30ms,换取"轨迹里不会出现半步"。
- 容器 `draining` 状态必须等 spool 排空(见 [02](02-container-runtime.md) §6)。
- 控制面不可达超过阈值时,agentd **降级为只写本地并在轨迹里标记 `degraded_window`**,
  绝不静默丢弃——回放时明确显示"这段时间的记录可能不完整"比假装完整要好得多。
