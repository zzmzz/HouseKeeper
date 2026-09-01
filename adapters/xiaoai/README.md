# 小爱音箱 Pro 适配器

把 E.V. 接到小爱音箱（LX06 / OH2P，需已刷 open-xiaoai 固件开 SSH）。

## 思路：不碰音频，也不用装 open-xiaoai 的 client

小爱原生的 ASR 和 TTS 都好用，我们只接管中间的「理解 + 执行」。

```
小爱麦克风 ─► 原生 ASR ─► 写进 /tmp/mico_aivs_lab/instruction.log
                                    │
                        ev-client.sh │ tail + grep（跑在音箱上，纯 shell）
                                    ▼
                              curl ─► E.V. HTTP 服务
                                    │
              ┌─────────────────────┴──────────────────┐
              │ handled=true                handled=false
              ▼                                        ▼
    ubus mibrain text_to_speech          ubus mibrain ai_service
       （原生 TTS 念回答）                （交回原来的小爱处理）
```

**为什么不用 open-xiaoai 的 Rust client**：那需要交叉编译 aarch64 二进制、
或在服务端装 Rust + maturin + Python 3.12 编译 `open_xiaoai_server` 扩展。
而识别结果本来就落在 `instruction.log` 里，音箱上又有 `curl` 和 `ubus` ——
一个 80 行的 shell 脚本就够了，**零编译、零依赖、随时能改**。

## 部署

**1. 服务端（任意常开机器）**

```bash
python3 ev_server.py            # dry-run
python3 ev_server.py --real     # 真实控制设备
```

**2. 音箱端**

```bash
# 把脚本传上去（音箱没有 sftp-server，用管道）
cat ev-client.sh | ssh -o HostKeyAlgorithms=+ssh-rsa root@<音箱IP> \
  'cat > /data/ev-client.sh && chmod +x /data/ev-client.sh'

# 启动（音箱上没有 nohup，用子 shell）
ssh root@<音箱IP>
export EV_URL=http://<服务端IP>:8848
(sh /data/ev-client.sh > /tmp/ev-client.log 2>&1 &)
```

**3. 验证**（不用真喊，注入一条识别结果即可）

```bash
echo '{"header":{"dialog_id":"t1","name":"RecognizeResult","namespace":"SpeechRecognizer"},
"payload":{"is_final":true,"results":[{"text":"现在适合开窗吗"}]}}' >> /tmp/mico_aivs_lab/instruction.log
tail -f /tmp/ev-client.log
```

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `EV_URL` | `http://192.168.8.202:8848` | E.V. 服务地址 |
| `EV_PREFIX` | 空 | 设了就只处理以它开头的话；留空=接管全部语音 |
| `EV_SESSION` | `xiaoai` | 会话名，多个语音端各自独立（纠正/确认不串） |

## 踩过的坑

- **音箱是 busybox**：没有 `nohup`、没有 `jq`、`timeout` 语法也不同（要 `-t`）。
  脚本里只用 `sed` 抠 JSON，后台启动用 `(cmd &)`。
- **没有 sftp-server**，`scp` 传不上去，要用 `cat | ssh 'cat >'`。
- **SSH 只认老算法**：连的时候要加 `-o HostKeyAlgorithms=+ssh-rsa`。
- **同一轮对话会重复出现多条识别结果**，脚本用 `dialog_id` 去重。
- **先打断小爱自己的回答**（`pnshelper event_notify src=3,event=7`），否则两个声音重叠。

## 另一个实现

`ev_xiaoai.py` 是基于 open-xiaoai WebSocket 协议的 Python 服务端版本
（音箱端跑官方 Rust client）。功能等价，但需要编译 client，一般用不上。
