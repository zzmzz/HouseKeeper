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
STATE="/tmp/ev_last_dialog"

echo "[E.V.] 客户端启动 -> $EV_URL"
echo "[E.V.] $([ -n "$PREFIX" ] && echo "仅处理「$PREFIX」开头" || echo "接管全部语音")"
[ -n "$ROOM" ] && echo "[E.V.] 本机位于：$ROOM（笼统指令默认落在这个房间）"

# 说话（原生 TTS）
speak() {
  ubus call mibrain text_to_speech "{\"text\":\"$1\",\"save\":0}" >/dev/null 2>&1
}
# 交回原来的小爱
hand_back() {
  ubus call mibrain ai_service "{\"nlp\":1,\"nlp_text\":\"$1\"}" >/dev/null 2>&1
}
# 打断小爱自己的回答，避免和我们的回答重叠
stop_native() {
  ubus call pnshelper event_notify '{"src":3,"event":7}' >/dev/null 2>&1
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
  stop_native

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
    speak "$reply"
  else
    # 不交回小爱了——做不到就如实说，缺什么能力由 daily loop 的缺口队列去补
    echo "[E.V.] 做不到：$reply"
    speak "${reply:-这个我还做不了}"
  fi
done
