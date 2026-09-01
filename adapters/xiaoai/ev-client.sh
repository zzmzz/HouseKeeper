#!/bin/sh
# E.V. 小爱音箱轻量客户端 —— 直接跑在音箱上，零编译零依赖
#
# 原理：小爱把语音识别结果写进 /tmp/mico_aivs_lab/instruction.log，
#       我们 tail 这个文件、把识别到的文本 curl 给 E.V.、拿回答用原生 TTS 念出来。
#       不归 E.V. 管的（问天气/讲笑话/放歌）交回小爱自己处理。
#
# 相比装 open-xiaoai 的 Rust client：不用交叉编译、不占内存、随时能改。
#
# 用法（音箱上）：
#     EV_URL=http://192.168.8.202:8848 sh /data/ev-client.sh &
# 开机自启：写进 /data/ev-boot.sh 并挂到 rc.local

EV_URL="${EV_URL:-http://192.168.8.202:8848}"
LOG="/tmp/mico_aivs_lab/instruction.log"
SESSION="${EV_SESSION:-xiaoai}"
# 这台音箱在哪个房间。决定「打开空调」这种没点名房间的指令落在哪台设备上。
ROOM="${EV_ROOM:-}"
# 设了就只处理以它开头的话；留空 = 接管全部语音
PREFIX="${EV_PREFIX:-}"
# 回答完是否自动开麦（连续对话，不用每轮重喊唤醒词）。1=开启
# ⚠️ 默认关闭：开麦后麦克风会持续收音，环境噪音会被识别成碎片文本，
#    可能陷入「答完开麦 -> 收到噪音 -> 又答 -> 又开麦」的循环。
#    要用请显式 EV_KEEP_MIC=1，并配合上面的过短过滤。
KEEP_MIC="${EV_KEEP_MIC:-0}"
STATE="/tmp/ev_last_dialog"

echo "[E.V.] 客户端启动 -> $EV_URL"
echo "[E.V.] $([ -n "$PREFIX" ] && echo "仅处理「$PREFIX」开头" || echo "接管全部语音")"
[ -n "$ROOM" ] && echo "[E.V.] 本机位于：$ROOM（笼统指令默认落在这个房间）"
[ "$KEEP_MIC" = "1" ] && echo "[E.V.] 连续对话已开：答完自动开麦，不用重喊唤醒词"

# 说话（原生 TTS）
speak() {
  ubus call mibrain text_to_speech "{\"text\":\"$1\",\"save\":0}" >/dev/null 2>&1
}
# 交回原来的小爱
hand_back() {
  ubus call mibrain ai_service "{\"nlp\":1,\"nlp_text\":\"$1\"}" >/dev/null 2>&1
}
# 打断小爱自己的回答。
#
# ⚠️ 血泪教训：不要用 pnshelper event 7！
# 它是「取消唤醒」序列的**前半截**（完整是 7 然后 8）。只发 7 不发 8，
# 会把唤醒状态机卡在半路——实测导致**唤醒词彻底失灵**，只能手动点麦克风。
# 恢复办法：补发一次完整的 7 + 8。
#
# 改用 mediaplayer 直接停播，只影响音频、不碰唤醒状态机。
stop_native() {
  ubus call mediaplayer player_play_operation '{"action":"pause"}' >/dev/null 2>&1
}

# 静默唤醒：开麦但不出「我在」提示音，用户可以直接接着说下一句。
# ✅ 已实测验证：发完这条后不喊唤醒词直接说话，能正常识别。
# 注意和 event 7/8（取消唤醒）是完全不同的方向，这条不会破坏唤醒状态机。
wake_up() {
  ubus call pnshelper event_notify '{"src":1,"event":0}' >/dev/null 2>&1
}

# 等 TTS 真的播完。
# 坑：text_to_speech 是**异步**的，调用立刻返回；instruction.log 里的
# FinishSpeakStream 也只表示"流传输完"（1 秒内就出现），不是"播放完"。
# 唯一可靠的信号是 mphelper mute_stat：播放中=1，空闲=0。
# 播完之前就 wake_up 没用——语音一结束小爱会自己把麦关掉。
wait_speak_done() {
  i=0
  while [ $i -lt 16 ]; do            # 最多等 8 秒（超时就放弃开麦，不卡住主循环）
    sleep 0.5
    st=$(mphelper mute_stat 2>/dev/null | tr -d " \n")
    case "$st" in *0*) return 0 ;; esac
    i=$((i+1))
  done
}

tail -F "$LOG" 2>/dev/null | while read -r line; do
  # 只要最终识别结果
  echo "$line" | grep -q '"name":"RecognizeResult"' || continue
  echo "$line" | grep -q '"is_final":true' || continue

  # 抠出文本（busybox 环境没有 jq，用 sed）
  text=$(echo "$line" | sed -n 's/.*"text"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
  [ -z "$text" ] && continue
  # 开麦后麦克风会捕捉环境噪音，识别出「没」「了」这类碎片。
  # 太短的一律忽略，否则会陷入「答完开麦 -> 收到噪音 -> 又答 -> 又开麦」的死循环。
  # 注意：不能用 case "$text" in ?|??) —— shell 的 ? 匹配的是**字节**，
  # 一个中文字符是 3 字节，`?` 永远匹配不上。用字节长度判断。
  BYTES=$(printf %s "$text" | wc -c)
  if [ "$BYTES" -le 6 ]; then          # <= 2 个中文字
    echo "[E.V.] 忽略过短识别：$text"
    continue
  fi

  # 同一轮对话只处理一次
  dialog=$(echo "$line" | sed -n 's/.*"dialog_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
  [ "$dialog" = "$(cat $STATE 2>/dev/null)" ] && continue
  echo "$dialog" > "$STATE"

  spoken="$text"
  if [ -n "$PREFIX" ]; then
    case "$text" in
      "$PREFIX"*) spoken=$(echo "$text" | sed "s/^$PREFIX//") ;;
      *) continue ;;                      # 没带前缀，不插手
    esac
  fi

  echo "[E.V.] 听到：$spoken"
  # 抢在小爱开口之前打断。它在 is_final 之后**立刻**就 StartAnswer 并 Speak
  # （IoT 指令走云端直连，比我们快），我们要等 E.V. 返回（~500ms）才打断的话，
  # 它两句都说完了——实测出现过「正在打开窗帘。」「设备已经关啦」和我们的回答三段抢播。
  # 所以这里连打三次、间隔 0.15 秒，覆盖它开口的那个窗口。
  stop_native; sleep 0.15; stop_native; sleep 0.15; stop_native

  resp=$(curl -s -m 20 -X POST "$EV_URL/ask" \
    -H "Content-Type: application/json" \
    -d "{\"text\":\"$spoken\",\"session\":\"$SESSION\",\"room\":\"$ROOM\"}" 2>/dev/null)

  if [ -z "$resp" ]; then
    echo "[E.V.] 服务无响应"
    speak "后台没反应，等下再试"; continue
  fi

  handled=$(echo "$resp" | sed -n 's/.*"handled"[[:space:]]*:[[:space:]]*\([a-z]*\).*/\1/p' | head -1)
  reply=$(echo "$resp" | sed -n 's/.*"reply"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)

  if [ "$handled" = "true" ]; then
    echo "[E.V.] 回答：$reply"
    # 第二次打断：小爱是在识别完之后才组织回答的，
    # 上面那次打断时它还没开口，等我们拿到答案（~0.2s）它正好开始说，
    # 两个声音会抢——所以说话前必须再掐一次。
    stop_native
    sleep 0.3
    speak "$reply"
    # 说完重新开麦，用户可以直接接着说（纠正、追问都不用再喊唤醒词）
    [ "$KEEP_MIC" = "1" ] && { wait_speak_done; sleep 0.3; wake_up; }
  else
    # 不交回小爱了——做不到就如实说，缺什么能力由 daily loop 的缺口队列去补
    echo "[E.V.] 做不到：$reply"
    speak "${reply:-这个我还做不了}"
    [ "$KEEP_MIC" = "1" ] && { wait_speak_done; sleep 0.3; wake_up; }
  fi
done
