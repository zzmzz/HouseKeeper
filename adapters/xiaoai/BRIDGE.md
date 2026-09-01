# Rust client 版桥接（替代读日志）

比 `ev-client.sh`（读 instruction.log）更早拿到事件，能赶在小爱开口前压住它。
实测端到端 **16ms**（日志版 200-500ms）。

## 为什么要改 open-xiaoai 的源码

官方 gemini 示例的 `on_event` **只打印日志、不转发给 Python**：

```rust
async fn on_event(event: Event) -> Result<(), AppError> {
    crate::pylog!("🔥 收到 Event: {:?}", event);
    Ok(())            // ← 到此为止，Python 侧收不到
}
```

它是纯音频流方案（只暴露 `on_input_data`），要走 `xiaoai_asr` 模式
（复用小爱原生 ASR 的文本）就得自己加转发。改动见 `server.rs.patch`，
照着 `on_stream` 的写法把事件序列化后 `call_fn("on_event", ...)`。

## 部署

**Mac mini（server 侧）**

```bash
# 1. Rust（用户级，不需要 sudo）
#    注意：static.rust-lang.org 直连 TLS 握手失败，必须走镜像
export RUSTUP_DIST_SERVER=https://mirrors.tuna.tsinghua.edu.cn/rustup
export RUSTUP_UPDATE_ROOT=https://mirrors.tuna.tsinghua.edu.cn/rustup/rustup
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path --profile minimal

# 2. crates 镜像（否则拉依赖也卡）
cat > ~/.cargo/config.toml <<'EOF'
[source.crates-io]
replace-with = "tuna"
[source.tuna]
registry = "sparse+https://mirrors.tuna.tsinghua.edu.cn/crates.io-index/"
EOF

# 3. 编译（用 Homebrew python3.14，系统 3.9 一个字不动——mlx 服务依赖它）
cd ~/code/open-xiaoai/examples/gemini
PATH=$HOME/.cargo/bin:/opt/homebrew/bin:$PATH maturin build --release

# 4. 装扩展。注意：机器上 pip 是 21.2.4，装不了这个 wheel，直接解压拷贝
cd /tmp && unzip -o ~/code/open-xiaoai/examples/gemini/target/wheels/*.whl
cp -r open_xiaoai_server ~/code/ev-mlx/libs/

# 5. 起桥接
PYTHONPATH=~/code/ev-mlx/libs EV_URL=http://<ev-server>:8848 EV_ROOM=主卧 \
  /usr/bin/python3 ev_bridge.py
```

**音箱端**

```bash
mkdir -p /data/open-xiaoai
echo 'ws://<mac-mini-ip>:4399' > /data/open-xiaoai/server.txt
curl -sSfL https://gitee.com/idootop/artifacts/releases/download/open-xiaoai-client/init.sh | sh
```

开机自启：`curl -L -o /data/init.sh <同址>/boot.sh` 然后 reboot。

## 编译踩的坑

- `static.rust-lang.org` 和 crates.io 都要走镜像，直连 TLS 握手失败
- `wheel` 是 `cp38-abi3`，兼容 3.8+，所以能用 3.14 编译、拿到 3.9 上跑
- 系统 pip 21.2.4 装不了这个 wheel，**直接解压拷贝模块目录**即可（它是编译好的 .so）
- 转发事件时 `String` 没有 `into_pyobject`，用 `PyString::new(py, &s)`
