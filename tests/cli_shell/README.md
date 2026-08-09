# cli_shell — CLI 是照着 tmux 长的

## 这个场景在测什么

CLI 是 lib 的一个用户,和你的代码平级。这个场景锁的是它对 shell 脚本的承诺:

1. **退出码是接口**,不是随手写的数字:找不到、定位失败、runtime 不可用各是各的码。
2. **`new` 幂等** —— 像 `tmux new -A -s`。
3. **注册表里的文件只是线索,活没活要现探。** 死的要列出来并告诉人怎么清。
4. **定位失败要在终端里列出候选** —— 人下一步就靠它。
5. `--json` 出的是原始形状,给脚本用。

## 不在这测什么

- 库的语义 —— 在 [`session_identity/`](../session_identity/)。
- `install` —— 在 [`installing/`](../installing/)。
