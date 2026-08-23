# modules · 按「一件事」分,不按「一层」分

**一句话**:今天每个大文件内部**都已经按同一组域切过一遍了**,
只是没人把它们对齐 —— 所以改一件事要在六个文件里各改一小块。

> **设计稿,还没落地。** 它取代了原来那份 `docs/v2/models/`:
> 那份想把 `models.py` 按"跨哪种边界"拆开,而**`models` 根本不是一件事**,
> 按它拆只是把同一个错误排得整齐一点。

## 1. 量到了什么

### 1.1 一次改动平均动 6.2 个文件

扁平化之后 26 个提交碰过 `webmuxd/`,平均每次动 **6.2 个文件**。
最常一起改的那些,相关度高得不像"偶然":

```
processes ↔ sessions   0.62      rrweb ↔ screen        0.67
processes ↔ screen     0.67      processes ↔ xpra      0.67
models    ↔ serve      0.60      act   ↔ api           0.60
```

这些不是随机耦合。`processes` / `sessions` / `xpra` / `screen` 四个是
**"起 VNC 那条腿"这一件事**;`rrweb` / `screen` 是 **"DOM 那条腿"**;
`models` / `serve` 是**"下行消息"**;`act` / `api` 是**"做一下"**。

**层把每一件事切成了三四片。**

### 1.2 而且每个大文件内部,切法是同一套

```
sessions.py  1211 行   Session(639) + ProcessRuntime(211) + RemoteRuntime(52) + Server(132)
serve.py      899 行   h_tab_* / h_act,h_snapshot / h_log* / h_pending,h_download* / h_view,h_xpra,h_rrweb
api.py       1016 行   Tab(310) + Session(159) + Webmuxd(100) + Mirror(196)
cli.py       1046 行   cmd_tabs… / cmd_click… / cmd_log… / cmd_new,cmd_ls…
```

四个文件,**四份同样的分组**:tab、页面里做事、流水、画面、session、server。

> 这就是 6.2 的来源。改"tab"这一件事要动:
> `models`(形状)+ `tabs`(表)+ `sessions`(接线)+ `serve`(handler)+
> `api`(`Tab` 类)+ `cli`(命令) = **六个文件,每个动一小块**。
>
> 0.18.0 那次改"前台是谁",实际动了 `tabs` `sessions` `sidecar` `exceptions` `cli`
> —— **一个概念,五个文件。**

### 1.3 `models.py` 是 15/25 个模块的共同依赖

它被 25 个模块里的 15 个 import。**一个被大半个项目 import 的模块,
说明它不是一件事** —— 它是"所有事的一部分"被抽出来堆在了一起。

## 2. 所以主轴换成域,层降级成一条规矩

- **层**管的是"谁能 import 谁" —— 防循环、防底层认识上层
- **域**管的是"一件事的代码在不在一起"

今天有层、没有域。**两者不冲突**:域是主轴,层变成域之间的一条单向规矩。

### 2.1 先回答上一次为什么要摊平

[j §7](../works/j-layout.md) 记着:摊平之后暴露出的真问题是**反向依赖** ——
`runtime/` 要起 xpra、要找浏览器,而这两样一个在第 2 层一个在第 5 层。
原话是"**子目录一直在替这些遮丑**"。

那句话是对的,但它是对**按角色分的子目录**说的:`core/` `view/` `runtime/` `serve/`。
`runtime/` import `xpra.py` 之所以是反向依赖,**恰恰因为"起 VNC 那条腿"
这一个域被切在了 `runtime/` 和 `view/` 两边**。

> 摊平是对那次的正确修复。而摊平之后暴露出来的真实耦合(§1.1),
> 形状就是域。

判据可以说得更硬一点:

> **打开一个目录,能不能回答"改这件事要动哪儿"。**
> `core/` 回答不了,`tab/` 回答得了。

## 3. 域一览

| 域 | 一句话 | 今天散在 |
| --- | --- | --- |
| [browser](browser.md) | 弄来一个能连的 Chromium | `processes` `cdp` `config` `sessions` 的 Runtime 那段 |
| [install](browser.md#4-install-是同一个域的另一半) | 探、下、装、记 | `install` `config` `models` 的 Fact 那几个 |
| [tab](tab.md) | 那张表 + 前台是谁 | `tabs` `models.TabInfo` `sessions` 的前台那段 |
| [page](page.md) | 在一页里找东西、做事、看结果 | `act` `locate` `capture` `models` 的 Element/Snapshot/Ref |
| [native](page.md#5-native-是同一个域的边角) | 浏览器自己弹的那五类 | `browser_ui` `models.Pending/Download` |
| [channel](channel.md) | 画面出去、输入进来 | `screen` `jpg` `xpra` `rrweb` `frames` `quality` `input` `cursor` `sidecar` |
| [session](session.md) | 一个 session 的一生 | `sessions.Session` `log` `logfmt` |
| [server](server.md) | 一个口 | `serve` `sessions.Server` |
| [face](server.md#3-两个面) | 给代码的和给人的 | `api` `cli` |

底座(谁都能用,不属于任何域):`exceptions.py`。

## 4. 依赖:域之间只许往下

```
        face        api / cli —— **只认形状,不认实现**
          ↓
        server      一个口
          ↓
        session     把下面全接起来
          ↓
    ┌─────┴─────┬──────────┐
  channel      page      native
    └─────┬─────┴──────────┘
          ↓
         tab
          ↓
       browser        install
          ↓
       exceptions
```

五条规矩,每条一句断言([moving §4](moving.md#4-怎么守住)):

1. **域之间只许往下 import**
2. **`face` 只许 import 各域的 `shape.py`**,不许 import 机器
3. **`shape.py` 一行 import 都没有**(连 `exceptions` 都不许)
4. **只有 `*/http.py` 认识 aiohttp**
5. **每个域一句话** —— 目录里那份 `README.md` 第一行

## 5. 形状怎么办 —— `models.py` 的那份保证一条不丢

`models.py` 今天买到两样东西,拆域之后**都还在,而且第一次能逐域断言**:

| 它买到的 | 按域分之后 |
| --- | --- |
| **一个概念一处定义**(同一个 tab 记录不会服务端一份、SDK 一份) | `TabInfo` 仍然只有一处,只是搬到了 `tab/shape.py` |
| **给人用的两个面只认形状,不认实现** | 规矩 2 + 3:`face` 只许 import `*/shape.py`,而那些文件一行 import 都没有 |

而它今天**没有**买到的:

- "只有数据,没有行为"这句话**一处代码都没守着** ——
  所以 `RefTable` 长到了 67 行(有状态、抛四种异常),
  而 `SessionInfo.detail` 里装着一个**活的子进程**
- 那条"不 import 本项目任何东西(除 `exceptions`)"里的例外,
  **唯一的原因**就是 `RefTable` 和 `_not_found` —— 除此之外一处都没用到

拆成 `*/shape.py` 之后,规矩 3(一行 import 都没有)把这两件一起挡了:
**`RefTable` 想留在 `shape.py` 里,它 import `exceptions` 那一行就会红。**

## 6. 这个目录

| | |
| --- | --- |
| [browser](browser.md) | 弄来一个能连的 Chromium,以及装它 |
| [tab](tab.md) | 那张表 |
| [page](page.md) | 在一页里做事 |
| [channel](channel.md) | 画面出去、输入进来 |
| [session](session.md) | 一个 session 的一生 |
| [server](server.md) | 一个口,和两个面 |
| [moving](moving.md) | 从今天这 26 个文件怎么走过去,以及它会疼在哪 |
