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
KEEP_MIC="${EV_KEEP_MIC:-1}"
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
# 打断小爱自己的回答，避免和我们的回答重叠。
# 注意：event 7 实际是「取消唤醒」序列的一半，副作用是**会把麦克风关掉**——
# 所以说完话必须配一次 wake_up 把麦开回来，否则用户每轮都要重新喊唤醒词。
stop_native() {
  ubus call pnshelper event_notify '{"src":3,"event":7}' >/dev/null 2>&1
}

# 静默唤醒：开麦但不出「我在」提示音，用户可以直接接着说下一句
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
  while [ $i -lt 30 ]; do            # 最多等 15 秒
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
  stop_native          # 第一次：尽早掐掉小爱的思考

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
