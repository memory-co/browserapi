# not-models · 那五样根本不跨边界

**一句话**:判据用文件自己那句话就够 —— **没有 `to_json`,就没跨过 JSON
那条边界**。全文 18 个类有 `to_json`,下面这五个一个都没有。

## 1. 五样不跨边界的

| | 多大 | 为什么它不是模型 | 该去哪 |
| --- | --- | --- | --- |
| `RefTable` `Ref` `_not_found` | **67 行 / 3 个方法 / 抛 4 种 `NotFound`** | 有状态、有策略、会抛 —— 它是个**服务** | 新的 `refs.py`(第 2 层) |
| `SessionInfo` | 19 行 | `detail` 是 `dict[str, Any]`,而且**里面装着活的子进程** | `sessions.py` |
| `PageDigest` | 7 行 | 只有 `act.py` 用,从不出门 | `act.py` |
| `Quality` | 5 行 | 只有 `quality.py` 用;出门的是 `QualityChanged`,不是它 | `quality.py` |
| `PackageFamily` | 12 行 | 只有 `install.py` 用 | `install.py` |

### 1.1 `SessionInfo` 那个 `detail`

```python
sess = handle.detail["_xpra"]        # xpra 那个 Popen
sess.proc.poll()                     # 在模型层里 poll 一个子进程
```

`detail: dict[str, Any]` 是个没有形状的袋子,而袋子里装着一个**活的进程对象**。
这是"只有数据,没有行为"的反面 —— 它不是被谁写错了,是"runtime 产出的把柄"
这件事本来就不是数据。

## 2. 那个「除 `exceptions`」的例外

第 2 条规矩写的是"不 import 本项目任何东西(**除 `exceptions`**)"。
那个括号看着像个无害的例外。

它不是。`NotFound` 在整个 `models.py` 里的**全部**用处:

```
_not_found()      ← 一个专门造异常的函数
RefTable.get()    ← 四处 raise
```

**除此之外一处都没有。**

也就是说:

> **`models.py` 之所以需要那个例外,完全是因为它装了不该装的行为。**

把 `RefTable` 和 `_not_found` 搬走之后,第 2 条不再是一句自觉,
而是**结构上做不到** —— 那四个文件一行项目内 import 都没有,
可以直接断言成空集。

**一条规矩要么有东西守着,要么迟早不成立。** 这一条恰好可以变成前者。

## 3. `RefTable` 是怎么长到 67 行的

它不是有人某天决定"把一个服务塞进模型层"。看它现在的样子:

- `assign()` —— 发号,顺手写回 `el.ref`
- `get()` —— 认号,**四种失败分开说**,因为要做的事不一样
- `forget()` —— tab 关了清号,**`next_n` 不回退**

每一条单独看都合理,而且注释里那段"Chromium 会把 `backendNodeId` 复用给
新文档里的节点,于是导航之后拿旧号去点,`getBoxModel` 照样成功,
**点中的是另一个东西,而且不报错**"是这个项目最值钱的实测记录之一。

问题不在这些代码,在于**它们长在这儿的过程中,没有任何一步会红**:

> 加一个字段 → 加一个方法 → 那个方法要报错 → import 一下 `exceptions` →
> 四种失败分开说 → 67 行。

所以搬走它只是收拾现场。真正的修复是
[README §4](README.md#4-拆完之后那三条规矩第一次有东西守着) 那条断言:
**第 0 层的类,方法只许是 `to_json` / `from_json` / dunder。**

## 4. 搬 `RefTable` 之后叫什么

新文件 `refs.py`,第 2 层(和 `locate.py` `act.py` 同层)。

理由:`@e1` 这套号是**定位那一面**的东西 —— `snapshot` 发号、`click @e1`
认号,而 `locate.py` 开头那两条规矩里的第二条讲的就是它
([i](../works/i-agent-surface.md))。它和 `locate` 是一件事的两半,
不该隔着一个层。

## 5. `FrameHeader` 是第六样,但方向相反

它**确实跨边界**(28 字节头,TS 那边要解),所以它不在上面那张表里。
但它该和自己的编解码待在一起 —— 见 [wire §5](wire.md#5-frameheader-并回-framespy)。

## 6. ↔ 别处

| | |
| --- | --- |
| `@e1` 的规矩 | [i](../works/i-agent-surface.md) · [`tests/v2_refs/`](../../../tests/v2_refs/) |
| runtime 产出的把柄 | [h](../works/h-runtime.md) |
| 层怎么分的 | [j §5](../works/j-layout.md#5-依赖方向扁平之后层要靠规矩守) |
