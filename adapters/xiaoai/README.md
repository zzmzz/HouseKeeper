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
| `EV_KEEP_MIC` | `1` | 答完自动开麦，可以直接接着说下一句（纠正/追问不用重喊唤醒词） |
| `EV_ROOM` | 空 | **这台音箱在哪个房间**。设了之后，「打开空调」「把灯关了」这类没点名房间的指令会落在本房间的设备上 |

## 就近原则（多音箱场景）

家里放多台音箱时，各自声明所在房间：

```bash
# 主卧那台
EV_ROOM=主卧 EV_SESSION=xiaoai-bed sh /data/ev-client.sh
# 客厅那台
EV_ROOM=客厅 EV_SESSION=xiaoai-living sh /data/ev-client.sh
```

同一句话，结果不同：

| 你说 | 对主卧音箱 | 对客厅音箱 |
|---|---|---|
| 打开空调 | 主卧空调 | 客厅空调 |
| 把灯关了 | 主卧灯 | 客厅灯 |
| **客厅**空调打开 | 客厅空调 | 客厅空调 |

**全部走本地快路径（1-3ms）**。音箱位置是固定常量，不需要大模型推理——
分类器照常输出（默认房间那台），再按房间做一次查表改写即可。

## 踩过的坑

- **音箱是 busybox**：没有 `nohup`、没有 `jq`、`timeout` 语法也不同（要 `-t`）。
  脚本里只用 `sed` 抠 JSON，后台启动用 `(cmd &)`。
- **没有 sftp-server**，`scp` 传不上去，要用 `cat | ssh 'cat >'`。
- **SSH 只认老算法**：连的时候要加 `-o HostKeyAlgorithms=+ssh-rsa`。
- **同一轮对话会重复出现多条识别结果**，脚本用 `dialog_id` 去重。
- **打断要打两次**。小爱是在识别完**之后**才组织回答的，收到文本时立刻打断会打个空，
  等我们拿到答案（~0.2s）它正好开口，两个声音就撞上了。所以说话前必须再打断一次。
  （实测现象：用户以为"卡死了"，其实是两段 TTS 互相打断。）
- **TTS 是异步的，而且没有可靠的"播完"事件**。`text_to_speech` 调用立刻返回；
  `instruction.log` 里的 `FinishSpeakStream` 只表示"流传输完"（1 秒内就出现），
  不是播放完。唯一可靠的信号是 **`mphelper mute_stat`：播放中=1，空闲=0**。
  播完之前 wake_up 没用——语音一结束小爱会自己把麦关掉。
- **⚠️ 千万别用 `pnshelper event 7` 打断说话。** 它是「取消唤醒」序列的**前半截**
  （完整是 7 然后 8）。只发 7 不发 8 会把唤醒状态机卡在半路——
  **实测导致唤醒词彻底失灵，只能手动点麦克风**。
  恢复办法：补发一次完整的 `7` → `sleep 0.2` → `8`。
  打断说话请用 `mediaplayer player_play_operation '{"action":"pause"}'`，
  它只动音频、不碰唤醒状态机。
- **连续对话**：答完用 `pnshelper event_notify '{"src":1,"event":0}'` 静默开麦
  （`src=1` 不出「我在」提示音）。已实测：发完这条后不喊唤醒词直接说话能正常识别。
  这条和 event 7/8 是相反方向，安全。

## 另一个实现

`ev_xiaoai.py` 是基于 open-xiaoai WebSocket 协议的 Python 服务端版本
（音箱端跑官方 Rust client）。功能等价，但需要编译 client，一般用不上。
