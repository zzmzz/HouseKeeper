# -*- coding: utf-8 -*-
"""执行绑定：id -> 怎么干（HASS 服务/实体、传感器、脚本、场景步骤、回话、反向动作）。
语义描述（何时用/辨析）在 capabilities.md，那份是给大模型看的答案空间。"""

KIND_CONTROL='hass_control'; KIND_QUERY='hass_query'; KIND_SCRIPT='script'; KIND_SCENE='scene'

BINDINGS = {
 "lights_state": {"kind":"hass_query","state_query":True,"filter":["灯","浴霸"],"label":"灯"},
 "all_lights_off": {"kind":"scene","steps":["light_living_off","light_bed_off","kitchen_off",
    "dry_area_off","entry_off","hallway_off","dining_off","wall_wash_off","bath_heater_off"],
    "reply":"所有灯都关了","device":"全屋灯"},
 "all_ac_on": {"kind":"scene","steps":["ac_on","ac_bed_on","ac_second_on"],
    "reply":"三台空调都开了","device":"客厅/主卧/次卧空调","undo":"all_ac_off"},
 "all_ac_off": {"kind":"scene","steps":["ac_off","ac_bed_off","ac_second_off"],
    "reply":"三台空调都关了","device":"客厅/主卧/次卧空调","undo":"all_ac_on"},
 "all_fresh_air_off": {"kind":"scene","steps":["fresh_air_off"],
    "reply":"新风关了","device":"全屋新风"},
 "volume_up": {"kind":"script","script":"volume_up","device":"音箱音量"},
 "volume_down": {"kind":"script","script":"volume_down","device":"音箱音量"},
 "music_pause": {"kind":"script","script":"music_pause","device":"音箱"},
 "music_next": {"kind":"script","script":"music_next","device":"音箱"},
 "ac_temp_unsupported": {"kind":"script","script":"ac_temp_unsupported","device":"空调"},

 "light_living_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.lumi_acn017_8c9b_right_switch_service",
  "reply": "客厅灯开了",
  "device": "客厅灯",
  "undo": "light_living_off"
 },
 "light_living_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.lumi_acn017_8c9b_right_switch_service",
  "reply": "客厅灯关了",
  "device": "客厅灯",
  "undo": "light_living_on"
 },
 "light_bed_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.lumi_acn016_057b_switch",
  "reply": "主卧灯开了",
  "device": "主卧灯",
  "undo": "light_bed_off"
 },
 "light_bed_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.lumi_acn016_057b_switch",
  "reply": "主卧灯关了",
  "device": "主卧灯",
  "undo": "light_bed_on"
 },
 "kitchen_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.lumi_acn017_7e5c_left_switch_service",
  "reply": "厨房灯开了",
  "device": "厨房灯",
  "undo": "kitchen_off"
 },
 "kitchen_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.lumi_acn017_7e5c_left_switch_service",
  "reply": "厨房灯关了",
  "device": "厨房灯",
  "undo": "kitchen_on"
 },
 "dry_area_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.lumi_acn016_7d1c_switch",
  "reply": "干区灯开了",
  "device": "干区灯",
  "undo": "dry_area_off"
 },
 "dry_area_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.lumi_acn016_7d1c_switch",
  "reply": "干区灯关了",
  "device": "干区灯",
  "undo": "dry_area_on"
 },
 "entry_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.lumi_acn018_8c45_right_switch_service",
  "reply": "进门灯开了",
  "device": "进门灯",
  "undo": "entry_off"
 },
 "entry_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.lumi_acn018_8c45_right_switch_service",
  "reply": "进门灯关了",
  "device": "进门灯",
  "undo": "entry_on"
 },
 "hallway_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.lumi_acn018_8c45_middle_switch_service",
  "reply": "过道灯开了",
  "device": "过道灯",
  "undo": "hallway_off"
 },
 "hallway_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.lumi_acn018_8c45_middle_switch_service",
  "reply": "过道灯关了",
  "device": "过道灯",
  "undo": "hallway_on"
 },
 "bath_heater_on": {
  "kind": "hass_control",
  "service": "light.turn_on",
  "entity": "light.yeelink_v5_7a82_light_bath_heater",
  "reply": "浴霸开了",
  "device": "浴霸",
  "undo": "bath_heater_off"
 },
 "bath_heater_off": {
  "kind": "hass_control",
  "service": "light.turn_off",
  "entity": "light.yeelink_v5_7a82_light_bath_heater",
  "reply": "浴霸关了",
  "device": "浴霸",
  "undo": "bath_heater_on"
 },
 "dining_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.lumi_acn018_8c45_left_switch_service",
  "reply": "餐厅灯开了",
  "device": "餐厅灯",
  "undo": "dining_off"
 },
 "dining_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.lumi_acn018_8c45_left_switch_service",
  "reply": "餐厅灯关了",
  "device": "餐厅灯",
  "undo": "dining_on"
 },
 "ac_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.ke_ting_kong_diao",
  "reply": "客厅空调开了",
  "device": "客厅空调",
  "undo": "ac_off"
 },
 "ac_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.ke_ting_kong_diao",
  "reply": "空调关了",
  "device": "客厅空调",
  "undo": "ac_on"
 },
 "ac_bed_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.zhu_wo_kong_diao_kai_guan_2",
  "reply": "主卧空调开了",
  "device": "主卧空调",
  "undo": "ac_bed_off"
 },
 "ac_bed_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.zhu_wo_kong_diao_kai_guan_2",
  "reply": "主卧空调关了",
  "device": "主卧空调",
  "undo": "ac_bed_on"
 },
 "ac_second_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.ci_wo_kong_diao",
  "reply": "次卧空调开了",
  "device": "次卧空调",
  "undo": "ac_second_off"
 },
 "ac_second_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.ci_wo_kong_diao",
  "reply": "次卧空调关了",
  "device": "次卧空调",
  "undo": "ac_second_on"
 },
 "fresh_air_living_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.zhu_wo_xin_feng",
  "reply": "客厅新风开了",
  "device": "客厅新风"
 },
 "fresh_air_bed_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.zhu_wo_xin_feng_2",
  "reply": "主卧新风开了",
  "device": "主卧新风"
 },
 "fresh_air_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.xin_feng",
  "reply": "全屋新风关了",
  "device": "全屋新风",
  "undo": "fresh_air_on"
 },
 "fresh_air_second_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.ci_wo_xin_feng",
  "reply": "次卧新风开了",
  "device": "次卧新风"
 },
 "wall_wash_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.lumi_cn_1000838659_acn017_on_p_2_1",
  "reply": "洗墙灯开了",
  "device": "洗墙灯",
  "undo": "wall_wash_off"
 },
 "wall_wash_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.lumi_cn_1000838659_acn017_on_p_2_1",
  "reply": "洗墙灯关了",
  "device": "洗墙灯",
  "undo": "wall_wash_on"
 },
 "water_heater_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.re_shui_qi",
  "reply": "热水器开了",
  "device": "热水器",
  "undo": "water_heater_off"
 },
 "water_heater_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.re_shui_qi",
  "reply": "热水器关了",
  "device": "热水器",
  "undo": "water_heater_on"
 },
 "zero_cold_water_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.ling_leng_shui_kai_guan",
  "reply": "零冷水开了",
  "device": "零冷水",
  "undo": "zero_cold_water_off"
 },
 "zero_cold_water_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.ling_leng_shui_kai_guan",
  "reply": "零冷水关了",
  "device": "零冷水",
  "undo": "zero_cold_water_on"
 },
 "camera_living_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.chuangmi_cn_268116121_ipc021_on_p_2_1",
  "reply": "客厅摄像头关了",
  "device": "客厅摄像头",
  "undo": "camera_living_on"
 },
 "camera_living_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.chuangmi_cn_268116121_ipc021_on_p_2_1",
  "reply": "客厅摄像头开了",
  "device": "客厅摄像头",
  "undo": "camera_living_off"
 },
 "camera_dining_off": {
  "kind": "hass_control",
  "service": "switch.turn_off",
  "entity": "switch.chuangmi_cn_1022697889_021a04_on_p_2_1",
  "reply": "餐厅摄像头关了",
  "device": "餐厅摄像头",
  "undo": "camera_dining_on"
 },
 "camera_dining_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.chuangmi_cn_1022697889_021a04_on_p_2_1",
  "reply": "餐厅摄像头开了",
  "device": "餐厅摄像头",
  "undo": "camera_dining_off"
 },
 "camera_all_off": {
  "kind": "scene",
  "steps": [
   "camera_living_off",
   "camera_dining_off"
  ],
  "reply": "摄像头都关了"
 },
 "bed_curtain_open": {
  "kind": "hass_control",
  "service": "cover.open_cover",
  "entity": "cover.lumi_mcn005_7a69_curtain",
  "reply": "主卧布帘拉开了",
  "device": "主卧布帘",
  "undo": "bed_curtain_close"
 },
 "bed_curtain_close": {
  "kind": "hass_control",
  "service": "cover.close_cover",
  "entity": "cover.lumi_mcn005_7a69_curtain",
  "reply": "主卧布帘拉上了",
  "device": "主卧布帘",
  "undo": "bed_curtain_open"
 },
 "door_unlock": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.sonoff_100160b7b2",
  "reply": "门开了",
  "confirm": True,
  "device": "门禁"
 },
 "humidifier_on": {
  "kind": "hass_control",
  "service": "humidifier.turn_on",
  "entity": "humidifier.leshow_cn_592414455_jsq3",
  "reply": "加湿器开了",
  "device": "加湿器",
  "undo": "humidifier_off"
 },
 "humidifier_off": {
  "kind": "hass_control",
  "service": "humidifier.turn_off",
  "entity": "humidifier.leshow_cn_592414455_jsq3",
  "reply": "加湿器关了",
  "device": "加湿器",
  "undo": "humidifier_on"
 },
 "fresh_air_on": {
  "kind": "hass_control",
  "service": "switch.turn_on",
  "entity": "switch.xin_feng",
  "reply": "全屋新风开了",
  "device": "全屋新风",
  "undo": "fresh_air_off"
 },
 "curtain_open": {
  "kind": "hass_control",
  "service": "cover.open_cover",
  "entity": "cover.lumi_hmcn02_69ac_curtain",
  "reply": "客厅纱帘拉开了",
  "device": "客厅纱帘",
  "undo": "curtain_close"
 },
 "curtain_close": {
  "kind": "hass_control",
  "service": "cover.close_cover",
  "entity": "cover.lumi_hmcn02_69ac_curtain",
  "reply": "窗帘拉上了",
  "device": "客厅纱帘",
  "undo": "curtain_open"
 },
 "air_quality": {
  "kind": "hass_query",
  "sensors": [
   [
    "客厅温度",
    "sensor.miaomiaoce_t2_d817_temperature"
   ],
   [
    "客厅湿度",
    "sensor.miaomiaoce_t2_d817_relative_humidity"
   ],
   [
    "主卧温度",
    "sensor.miaomiaoce_t2_18c0_temperature"
   ],
   [
    "主卧湿度",
    "sensor.miaomiaoce_t2_18c0_relative_humidity"
   ],
   [
    "PM2.5",
    "sensor.heweather_pm25"
   ]
  ],
  "outdoor": True
 },
 "temperature": {
  "kind": "hass_query",
  "sensors": [
   [
    "客厅",
    "sensor.miaomiaoce_t2_d817_temperature"
   ],
   [
    "主卧",
    "sensor.miaomiaoce_t2_18c0_temperature"
   ]
  ]
 },
 "humidity": {
  "kind": "hass_query",
  "sensors": [
   [
    "客厅",
    "sensor.miaomiaoce_t2_d817_relative_humidity"
   ],
   [
    "主卧",
    "sensor.miaomiaoce_t2_18c0_relative_humidity"
   ]
  ]
 },
 "device_state": {
  "kind": "hass_query",
  "state_query": True
 },
 "who_home": {
  "kind": "hass_query",
  "sensors": [
   [
    "子沫",
    "person.ziiimo"
   ],
   [
    "小羽",
    "person.jhy"
   ]
  ]
 },
 "commute_eta": {
  "kind": "script",
  "script": "commute"
 },
 "weather": {
  "kind": "script",
  "script": "weather"
 },
 "music_play": {
  "kind": "script",
  "script": "music"
 },
 "scene_sleep": {
  "kind": "scene",
  "steps": [
   "light_living_off",
   "dining_off",
   "hallway_off",
   "entry_off",
   "curtain_close"
  ],
  "reply": "晚安，都关好了"
 },
 "scene_home": {
  "kind": "scene",
  "steps": [
   "entry_on",
   "hallway_on"
  ],
  "reply": "欢迎回家"
 }
}