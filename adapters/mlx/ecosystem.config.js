// pm2 配置：把 MLX 推理服务挂成常驻进程
// 部署： pm2 start ecosystem.config.js && pm2 save
module.exports = {
  apps: [{
    name: "ev-mlx",
    script: "mlx_server.py",
    // 绝对路径！机器上有多个 python3：
    //   /opt/homebrew/bin/python3 -> 3.14（Homebrew，没装 mlx_lm）
    //   /usr/bin/python3 -> 3.9（系统，mlx_lm 装在这）
    // 靠 PATH 猜会选中错的那个，报 ModuleNotFoundError: mlx_lm
    interpreter: "/usr/bin/python3",
    args: "--port 8850 --model mlx-community/Qwen3-0.6B-4bit --adapter adapters-0.6b",
    cwd: "/Users/z/code/ev-mlx",
    env: {
      // mlx_lm 装在用户目录，pm2 的环境里默认找不到
      PATH: "/Users/z/Library/Python/3.9/bin:/usr/bin:/bin:/usr/sbin:/sbin",
      // 不要设 PYTHONPATH！实测会破坏 mlx.core 的 C 扩展加载
      // （报 module 'mlx.core' has no attribute 'float32'）
      // 模型已缓存在本地，别再去连 HF（镜像站会 308 导致失败）
      HF_HUB_OFFLINE: "1",
    },
    autorestart: true,
    max_restarts: 10,
    min_uptime: "30s",        // 模型加载要 2 秒，给足启动时间
    max_memory_restart: "2G", // 正常占 0.43G，涨到 2G 说明泄漏了
    // 用 pm2 默认日志目录（~/.pm2/logs），别自己指定——
    // 实测指到 ~/logs 会失败：那个目录属于 root（以前 sudo 操作留下的）
    merge_logs: true,
    time: true,
  }]
};
