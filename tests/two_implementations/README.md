# two_implementations

协议有两个实现(Python 和 JS),**光靠各自的测试守不住"两边一致"**。

```
Python 侧(这里) → 写 webmuxjs/client/fixtures/*.json
JS 侧(vitest)  → 读同一份,断言自己编出来一样、解出来也一样
```

**任何一边改了格式,两边一起红。**
这项目在这个坑里栽过 —— `targetId` 的字节序当初是靠人肉发现的。
类型拦不住它,对拍能([j §4.2](../../docs/v2/works/j-layout.md#42-和-python-对拍))。

这里还守着另一条:**浏览器端那份构建产物缺了或者过期了,就红。**
这项目栽过一次 `.js` 没进 wheel —— 不能靠"记得先构建"。
