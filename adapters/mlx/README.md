# 微调小模型（E.V. 的 L2）

跑在 Apple 芯片机器上（MLX）。**一句话进，动作 id 出，约 160ms。**

## 为什么用微调而不是给大模型塞提示词

实测（同一套考卷 169 题，M4 Mac mini 16GB）：

| 方案 | 考卷 | 延迟(中位) | 内存 |
|---|---|---|---|
| 4B + 完整提示词（4168 token） | 100% | **12000ms** ❌ | 3.5GB |
| 0.6B 裸跑 + 极简提示词 | 0% | 594ms | 0.4GB |
| **0.6B 微调后** | **92%** | **158ms** | **0.43GB** |
| 1.7B 微调后 | 91% | 289ms | 1.10GB |

两个反直觉的结论：

1. **瓶颈是提示词不是模型大小。** 4B 准确率满分却要 12 秒 —— 4168 token 的能力清单
   每次都要重新 prefill。微调把能力清单**学进权重**，提示词只剩 48 字符，prefill 几乎归零。
2. **更大的模型反而更差。** 1.7B 准确率更低、延迟翻倍 —— 训练数据只有 1200 多条，
   参数多了 600 步就过拟合（val loss 从 0.475 回升到 0.536）。

> 92% 还是被低估的：14 条错题里有 3 条是 `fresh_air_off` vs `all_fresh_air_off`
> 这种**执行结果完全一样**的重复能力，1 条是考卷答案本身写错了。按实际可用性约 95%。

## 部署（pm2 常驻）

```bash
# Mac mini 上，一次性
mkdir -p ~/code/ev-mlx
# 传 mlx_server.py、ecosystem.config.js、adapters-0.6b/ 过去
cd ~/code/ev-mlx && pm2 start ecosystem.config.js && pm2 save
```

**ecosystem.config.js 里有三个坑，都是实测踩出来的**：

1. **必须用绝对路径指定解释器** `/usr/bin/python3`。
   机器上有两个 python3：Homebrew 的 3.14（PATH 里靠前，没装 mlx_lm）和系统的 3.9（装了）。
   靠 PATH 猜会选中错的，报 `ModuleNotFoundError: mlx_lm`。
2. **不要设 PYTHONPATH**，会破坏 mlx.core 的 C 扩展加载，
   报 `module 'mlx.core' has no attribute 'float32'`。
3. **不要自定义 log 路径**，用 pm2 默认的 `~/.pm2/logs`。
   （这台机器的 `~/logs` 属于 root，写不进去。）

> ⚠️ 这台机器的 pm2 **没有配开机自启**（`launchctl list | grep pm2` 为空），
> 重启后包括 cccodex 在内的所有 pm2 进程都不会自动恢复。
> 要配需要 sudo：`pm2 startup launchd -u z --hp /Users/z` 然后按提示执行那行 sudo 命令。

调试用：
```bash
python3 mlx_server.py --port 8850     # 前台跑
pm2 logs ev-mlx                        # 看日志
```

E.V. 端设环境变量即可启用：
```bash
EV_MLX_URL=http://<mac-mini-ip>:8850 python3 ev_server.py
```

**不设就不启用**，退回内置的 n-gram 分类器。

## 两道保险

- **id 白名单**：模型偶尔会编造不存在的动作 id（0.6B 的真实缺陷，实测 169 题里 3 次）。
  返回值先过一遍能力表，编造的直接丢弃 → 降级给云端大模型。
- **服务不可达短路 60 秒**：MLX 服务挂了自动退回 n-gram，且不会每次请求都干等超时。
  实测降级后仍是 1-2ms 正常工作。

## 重训

加新能力后必须重训，否则模型不认识新 id：

```bash
python3 ev/daily.py --lora      # 日常 loop 里顺带重训
python3 ev/retrain_lora.py      # 单独重训
```

**带晋升门槛**：新 adapter 要在考卷上不比旧的差才换上去，否则回滚（和 n-gram 蒸馏同一套规矩）。
训练一次约 4.5 分钟 / 600 步，峰值内存 2.2GB，产出的 adapter 仅 5.8MB。
