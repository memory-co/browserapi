# 03 · 观测与动作协议(核心契约)

这一份是全系统的中心。SDK、API、agentd、轨迹存储、回放器全部围绕它。
**改这里 = 改所有人**,因此本文档的每个字段都要能回答三个问题:
Agent 怎么用它决策?执行器怎么用它定位?回放器怎么把它画出来?

## 1. Observation(观测)

一次 `observe()` 的返回。设计目标:**直接可喂给多模态模型,调用方零解析**。

```jsonc
{
  "observation_id": "obs_01J9X...",
  "session_id": "ses_...",
  "captured_at": "2026-08-07T11:20:31.412Z",
  "page": {
    "url": "https://example.com/checkout",
    "title": "结算",
    "load_state": "networkidle",          // loading | domcontentloaded | networkidle
    "scroll": { "x": 0, "y": 1240, "max_y": 4820 },
    "viewport": { "w": 1280, "h": 800 }
  },
  "screenshot": {
    "ref": "blob://sha256:9f2c...",        // 内容寻址,回放器与模型共用同一张图
    "format": "webp",
    "annotated": true,                     // 已叠加元素编号(Set-of-Mark)
    "redacted": ["#card-number"]           // 被脱敏的区域(见 07)
  },
  "elements": [
    {
      "id": 12,                            // 本次观测内的短索引,给模型用
      "role": "button",                    // AX role
      "name": "提交订单",                  // AX accessible name
      "value": null,
      "bbox": [820, 612, 140, 40],         // 视口坐标 x,y,w,h — 回放器画框用
      "in_viewport": true,
      "enabled": true,
      "affords": ["click", "hover"],       // 该元素支持哪些动作
      "signature": "sig_7c1e...",          // 跨观测稳定引用(见 §3)
      "frame": null,                       // iframe 路径,顶层为 null
      "hint": "form#checkout > 主按钮"     // 人可读定位提示,给回放器和 debug 用
    }
  ],
  "text": {
    "digest": "结算\n收货地址 ...",         // 正文摘要,给纯文本模型或做 RAG
    "truncated": true,
    "full_ref": "blob://sha256:aa31..."
  },
  "tabs": [ { "target_id": "t_1", "title": "结算", "url": "...", "active": true } ],
  "modals": [],                            // 原生 dialog / 明显的模态遮罩
  "downloads": [],
  "notes": ["页面存在 3 个 iframe,其中 1 个跨域不可读"]   // 显式告知观测的盲区
}
```

### 1.1 元素表怎么筛
不能把整棵 AX 树倒给模型(动辄几千节点,又贵又吵)。筛选规则(可配置 profile):

1. **可交互优先**:role ∈ {button, link, textbox, checkbox, radio, combobox, menuitem, tab, slider, ...},
   或有 click 监听器,或 `contenteditable`。
2. **可见性**:有非零 bbox、未被 `display:none`/`visibility:hidden`/零透明度隐藏、未被其他元素完全遮挡。
3. **去噪**:合并只包一层的嵌套可点击容器(取最内层有 name 的);丢弃 name 为空且无 value 的纯装饰元素。
4. **视口策略**:默认包含**整页**可交互元素但标注 `in_viewport`,让模型知道"要滚动才能点"。
   可切 `viewport_only` 模式压缩体积。
5. **上限**:默认 150 个,超出按「视口内 → 距视口距离」排序截断,并在 `notes` 里明说截断了多少。

> §1.1 的规则集是本系统最容易出质量问题的地方,必须**版本化**(`perception_profile: "v1"`),
> 并且轨迹里记录用的哪个版本——否则升级筛选规则后,历史轨迹的元素编号会对不上,回放全废。

### 1.2 标注截图(Set-of-Mark)
在截图上给每个元素画框 + 左上角编号。约定:
- 编号即 `elements[].id`,颜色按 role 分类(可交互=实线,输入类=虚线)。
- 编号标签避让重叠;超密区域降级为"只画框,编号引到边缘"。
- **同时保留未标注原图**(`screenshot.ref` 的兄弟 blob),因为回放时人想看的是真实页面,
  而模型想看的是带标注的。两张图内容寻址后成本可控。

## 2. 动作空间

统一、封闭的动作集。**新增动作需要同时给出回放器渲染方式**(原则 2)。

| 类别 | 动作 | 关键参数 | 回放渲染 |
| --- | --- | --- | --- |
| 导航 | `navigate` | `url`, `wait_until` | 时间线上一个导航节点 |
| | `back` / `forward` / `reload` | — | 同上 |
| 指点 | `click` | `target`, `button`, `click_count`, `modifiers` | 截图上一个点击涟漪 + 元素高亮框 |
| | `hover` | `target` | 元素高亮框(虚线) |
| | `drag` | `from`, `to` | 起止点连线箭头 |
| 键入 | `type` | `target`, `text`\|`text_ref`, `clear_first`, `delay` | 元素高亮 + 输入内容(脱敏后)气泡 |
| | `press_key` | `key`, `modifiers` | 键帽图标 |
| | `clear` | `target` | 元素高亮 |
| 表单 | `select_option` | `target`, `values` | 元素高亮 + 选中项 |
| | `set_checkbox` | `target`, `checked` | 元素高亮 + ✓/✗ |
| | `upload_file` | `target`, `file_id` | 文件名标签 |
| 视图 | `scroll` | `direction`\|`to_target`, `amount` | 截图间的滚动位移动画 |
| | `set_viewport` | `w`, `h` | 画布尺寸变化 |
| 标签 | `tab_new` / `tab_switch` / `tab_close` | `url` / `target_id` | 时间线泳道切换 |
| 等待 | `wait_for` | `condition`(selector/text/url/idle/timeout) | 时间线上一段等待条 |
| 读取 | `observe` | `profile`, `viewport_only` | 生成一个观测节点 |
| | `extract` | `target`, `mode`(text/html/table/attr) | 元素高亮 + 抽取结果面板 |
| | `screenshot` | `full_page`, `target` | 单独一张图 |
| 逃生 | `eval_js` | `expression` | **默认禁用**,启用时在轨迹里高亮标红 |
| | `coordinate_click` | `x`, `y` | 坐标十字准星 |
| 终止 | `done` | `result`, `summary` | Run 结束节点(成功) |
| | `fail` | `reason`, `category` | Run 结束节点(失败) |

### 2.1 关于 `eval_js` 和 `coordinate_click`
两者都是"能力逃生舱":强大,但会把操作路径变得不可解释
(一段 JS 干了什么、一次盲点击点到了谁,回放器都无法还原语义)。
因此:
- 默认关闭,需在会话配置显式开启;
- 使用时轨迹中打 `opaque: true` 标记并在 UI 高亮;
- `coordinate_click` 必须记录当时的截图与坐标,回放时画准星——这是它能被接受的最低要求。

### 2.2 批量提交
一个 Step 里 Agent 常常要连做几步(点输入框 → 输入 → 回车)。API 接受动作数组,
**串行执行、遇错即停**,返回每个动作的独立结果。这既省往返,也让"一次决策 = 一组动作"在轨迹里天然成组。

## 3. 目标定位(Target)

同一个"目标",在不同上下文下有不同的最优表达。协议支持多种,按**稳定性从高到低**:

```jsonc
// 1) 观测索引 —— Agent 决策时的默认方式,只在该观测有效
{ "kind": "element_id", "observation_id": "obs_...", "id": 12 }

// 2) 稳定签名 —— 跨观测、跨会话可复用,适合固化的脚本
{ "kind": "signature", "signature": "sig_7c1e..." }

// 3) 语义描述 —— 人写脚本最自然,由 agentd 解析为唯一元素
{ "kind": "semantic", "role": "button", "name": "提交订单", "nth": 0 }

// 4) 选择器 —— 逃生舱,脆但精确
{ "kind": "selector", "css": "#checkout button.primary" }

// 5) 坐标 —— 最后兜底
{ "kind": "point", "x": 890, "y": 632 }
```

**解析失败的处理**:不静默失败。返回 `target_not_found`,并附带
「当前观测里最接近的 3 个候选 + 它们的 name/role」,这样 Agent 有机会自我纠正,
排查时也能一眼看出是页面变了还是识别错了。

### 3.1 稳定签名怎么算
`signature = sha256(role ‖ normalized_name ‖ dom_path_skeleton ‖ frame_path)`

- `normalized_name`:去空白、去数字变体(`购物车(3)` → `购物车(N)`)。
- `dom_path_skeleton`:从根到该元素的 tag 序列,**去掉 nth-child 索引与自动生成 class**
  (匹配 `^(css-|sc-|jsx-|_[A-Za-z0-9]{5,})` 的 class 视为随机生成,丢弃)。
- 目的不是全局唯一,而是**同一页面同一控件在多次访问间稳定**。冲突时以 `nth` 消歧。

签名是把"某次运行"变成"可复现脚本"的桥梁,也是跨 run 对比路径分叉的对齐键(见 [04](04-trajectory-model.md) §6)。

## 4. ActionResult(动作结果)与 Effect(效果)

```jsonc
{
  "action_id": "act_01J9X...",
  "status": "ok",           // ok | target_not_found | timeout | denied | blocked_by_human | error
  "error": null,
  "started_at": "...", "duration_ms": 412,
  "resolved_target": {
    "signature": "sig_7c1e...", "bbox": [820,612,140,40], "hint": "form#checkout > 主按钮"
  },
  "effect": {
    "navigated": { "from": "/checkout", "to": "/order/9182", "kind": "push_state" },
    "dom_changed": { "added": 34, "removed": 12, "text_delta_chars": 780,
                     "summary": "出现『订单已提交』区块" },
    "network": { "requests": 7, "failed": 0, "slowest_ms": 310,
                 "notable": [ { "method":"POST", "url":"/api/orders", "status":201 } ] },
    "console": [ { "level":"error", "text":"..." } ],
    "dialogs": [], "downloads": [], "new_tabs": [],
    "screenshot_after": "blob://sha256:c81a..."
  }
}
```

### 4.1 Effect 的取舍
- **`network.notable`**:全量 HAR 太大,默认只记录 XHR/fetch 且状态码 ≥400 或路径命中配置的关注前缀。
  全量 HAR 作为**可选开关**(`capture: {har: true}`),用于深度排查。
- **`dom_changed.summary`**:一句人话摘要,由启发式生成(新增的最大文本块 / 消失的表单 / 新出现的 role=alert)。
  它是回放时间线上最有信息量的一列——比"DOM 变了 34 个节点"有用得多。
- **`screenshot_after` 总是采集**,`screenshot_before` 默认不采(用上一步的 after 顶替),
  除非该动作是 Step 的第一个动作。这样存储量约减半而路径依然连续。

## 5. 错误分类

轨迹要能回答"为什么失败",所以错误必须分类而不是一律 `error`:

| 类别 | 含义 | 典型归因 |
| --- | --- | --- |
| `target_not_found` | 定位不到 | Agent 认错元素 / 页面结构变了 |
| `target_not_actionable` | 找到了但不可点/被遮挡/禁用 | 时序问题、遮罩未消 |
| `timeout` | settle 或 wait_for 超时 | 页面慢、条件写错 |
| `navigation_failed` | 导航本身失败 | 网络、DNS、被出网策略拦 |
| `denied` | Policy 拒绝 | 域名不在白名单、动作被禁用 |
| `blocked_by_human` | 人正在接管 | 预期内 |
| `page_crashed` | 渲染进程崩溃 | 内存、页面本身 |
| `session_gone` | 容器不在了 | 被驱逐、OOM |
| `internal` | 其余 | 需要告警 |

前四类是**调用方可自愈**的(重试/换目标/等待);后四类是**平台问题**,应触发告警而非让 Agent 重试。
这个二分在 SDK 里表现为两个异常基类(见 [05](05-python-sdk.md) §6)。

## 6. Schema 治理

- 所有结构以 **JSON Schema** 定义在 `schemas/v1/`,SDK 的 dataclass、server 的 pydantic 模型、
  回放器的 TS 类型**全部由它生成**,禁止手写三份。
- 版本策略:URL 里带 `/v1/`;字段只增不删不改语义;弃用字段保留两个小版本并在响应里带 `deprecations`。
- `perception_profile`、`action_schema_version` 随每条轨迹落库,保证历史轨迹永远可正确回放。
