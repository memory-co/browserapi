# 06 · API service 模式

REST(控制与动作)+ WS(事件流)+ 直连通道(画面)。所有结构体见 [03](03-action-protocol.md) / [04](04-trajectory-model.md)。

## 1. 约定

- Base:`https://{host}/v1`
- 认证:`Authorization: Bearer <api_key>`(长期,租户级)。SDK/前端拿短期 `session_token`(scope 到单个 session)。
- 幂等:所有 `POST` 接受 `Idempotency-Key` 头,24h 窗口内重放返回原结果。
  **对 `POST /actions` 尤其重要**——网络重试导致的重复点击是真实事故来源。
- 错误体统一:
  ```json
  { "error": { "code": "target_not_found", "message": "...",
               "details": { "candidates": [...] }, "request_id": "req_..." } }
  ```
- 分页:`?cursor=&limit=`,返回 `next_cursor`。

## 2. 会话

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/sessions` | 创建会话(分配容器) |
| `GET` | `/sessions/{sid}` | 状态、容器健康、当前 URL |
| `GET` | `/sessions` | 列表(按 label/状态过滤) |
| `POST` | `/sessions/{sid}/reset` | 清状态复用(不销毁容器) |
| `POST` | `/sessions/{sid}/keepalive` | 续期 idle 计时 |
| `DELETE` | `/sessions/{sid}` | 销毁(触发 draining) |

```jsonc
// POST /sessions
{
  "profile_id": "shop-account-1",          // 复用登录态;同 profile 互斥
  "viewport": { "w": 1280, "h": 800 },
  "locale": "zh-CN", "timezone": "Asia/Shanghai",
  "proxy": "http://egress.internal:3128",
  "policy": {
    "allow_domains": ["*.example.com", "cdn.example.net"],
    "deny_actions": ["eval_js"],
    "redact_selectors": ["#card-number", "input[type=password]"]
  },
  "capture_level": "standard",             // minimal | standard | forensic
  "idle_timeout_s": 1800,
  "labels": { "team": "growth" }
}
// → 201
{
  "session_id": "ses_01J9X...",
  "status": "ready",
  "live": { "url": "https://bapi.internal/live/ses_01J9X...?t=<one-time>",
            "expires_at": "..." },
  "session_token": "st_...",               // 给前端/SDK,scope 到本会话
  "expires_at": "..."
}
```

## 3. 观测与动作

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/sessions/{sid}/observation` | 生成观测。`?profile=v1&viewport_only=true&annotate=true` |
| `POST` | `/sessions/{sid}/actions` | 执行动作数组(串行,遇错即停) |
| `GET` | `/sessions/{sid}/page` | 轻量当前状态(url/title/tabs),不截图不算观测 |
| `POST` | `/sessions/{sid}/files` | 上传文件供 `upload_file` 使用 → `file_id` |
| `GET` | `/sessions/{sid}/downloads/{fid}` | 取回下载文件 |
| `GET`/`POST` | `/sessions/{sid}/state` | 导出/导入 cookie 与 storage |

```jsonc
// POST /sessions/{sid}/actions
{
  "run_id": "run_...",           // 可选:归属某个 run
  "step_index": 12,              // 可选:归属某一步
  "actions": [
    { "type": "click", "target": { "kind": "element_id",
        "observation_id": "obs_...", "id": 12 } },
    { "type": "type",  "target": { "kind": "semantic", "role": "textbox", "name": "优惠码" },
      "text": "SAVE20" },
    { "type": "press_key", "key": "Enter" }
  ],
  "settle": { "strategy": "network_idle", "timeout_ms": 5000 }
}
// → 200 : { "results": [ /* ActionResult × 3,见 03 §4 */ ] }
```

**`text_ref` 凭证注入**:`{"type":"type","text_ref":"secret://vault/shop/pwd"}`。
密文由控制面在派发前解引用并直送 agentd,**请求日志、轨迹、回放中一律显示 `••••••`**。

## 4. Run(操作路径)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/sessions/{sid}/runs` | 开一个 run |
| `POST` | `/runs/{rid}/steps` | 开一步(带 observation 与 reasoning) |
| `PATCH` | `/runs/{rid}/steps/{n}` | 补充/关闭该步 |
| `POST` | `/runs/{rid}/finish` | 结束 run(outcome) |
| `GET` | `/runs/{rid}` | 轨迹。`?include=summary\|steps\|full` |
| `GET` | `/runs/{rid}/steps/{n}` | 单步详情 |
| `GET` | `/runs` | 检索:`?agent=&status=&label=&since=&category=` |
| `PATCH` | `/runs/{rid}/outcome` | **事后回写**结论(如 `wrong_result`) |
| `POST` | `/runs/{rid}/steps/{n}/annotations` | 加批注(评测标注) |
| `GET` | `/runs/{rid}/export` | `?format=bapi\|otel\|har\|bundle` |
| `GET` | `/runs/{rid}/replay` | 回放器页面(或回放包 URL) |
| `GET` | `/runs/diff?a={rid}&b={rid}` | 路径对比,返回分叉点([04 §6](04-trajectory-model.md)) |
| `POST` | `/runs/{rid}/to_script` | 降级导出为确定性脚本(v1.1) |

```jsonc
// POST /runs/{rid}/steps
{
  "step_index": 12,
  "observation_id": "obs_...",
  "reasoning": {
    "thought": "购物车里已有一张票,现在需要确认支付",
    "plan": ["点击确认支付", "填写手机号"],
    "model_call": { "model": "claude-opus-5", "input_tokens": 4210,
                    "output_tokens": 180, "latency_ms": 1840 }
  }
}
```
> `reasoning` 全部可选。不传也能用,只是回放时少了最有价值的一列——这一点值得在文档里对使用方说明白。

## 5. 事件流(WS)

```
WS /v1/runs/{rid}/events?after_seq=0
WS /v1/sessions/{sid}/events?after_seq=0
```
```jsonc
{ "seq": 418, "at": "...", "type": "action.result", "run_id": "run_...", "step_index": 12,
  "data": { "action_id": "act_...", "status": "ok", "duration_ms": 412,
            "effect": { "navigated": { "to": "/cancel" } } } }
```
- 服务端每 15s 发 `ping`;客户端断线后带 `after_seq` 续传,**服务端保留最近 10 分钟事件**。
- 大字段(截图)只发 `blob://` 引用,不内联,避免把事件流撑爆。

## 6. 画面与接管

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/sessions/{sid}/live-token` | 签发一次性画面 token(默认 5 min,可设只读) |
| `GET` | `/live/{sid}?t=` | 画面页面(内嵌 KasmVNC 客户端) |
| `POST` | `/sessions/{sid}/control` | 切换 `agent` / `human` / `shared` |

```jsonc
// POST /sessions/{sid}/control
{ "mode": "human", "actor": "ops@example.com", "reason": "验证码", "max_duration_s": 600 }
```
切到 `human` 后:
- Agent 的动作请求返回 `blocked_by_human`(HTTP 409),不排队、不静默丢弃;
- agentd 开始被动采集人的操作痕迹,生成 `HumanSpan`([04 §2](04-trajectory-model.md));
- 超过 `max_duration_s` 自动交还,防止会话被人长期占住。

`shared` 模式(人与 Agent 同时可操作)**v1 不做**:并发输入的语义与留痕都很难做对,收益不明确。

## 7. 平台

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/healthz` `/readyz` | 探针 |
| `GET` | `/capacity` | 容器池水位、可用槽位、排队深度 |
| `GET` | `/profiles` | 已有 profile 及占用状态 |
| `GET` | `/schemas/v1/{name}.json` | JSON Schema 自描述 |
| `GET` | `/openapi.json` | OpenAPI 3.1 |

## 8. 限流与背压

- 租户级:并发会话数、每分钟动作数、每日 blob 字节数。超限返回 `429` + `Retry-After`。
- **容量不足时创建会话返回 `202 + queued`**,带 `queue_position` 与轮询地址,而不是直接失败——
  批量任务场景下排队远比报错有用。
- 单会话动作串行:同一 session 的并发 `POST /actions` 返回 `409 session_busy`
  (与 SDK 的会话锁语义一致)。

## 9. Webhook

```jsonc
// 订阅 run 结束,便于外部系统消费失败
{ "event": "run.finished", "run_id": "run_...", "status": "failed",
  "outcome": { "category": "wrong_element", "message": "..." },
  "replay_url": "https://bapi.internal/runs/run_.../replay" }
```
签名用 HMAC-SHA256(`X-Bapi-Signature`),失败按指数退避重投 24h。
**`replay_url` 放进 webhook 是刻意的**:让失败告警天然带着"点开就能看它当时干了什么"的入口。
