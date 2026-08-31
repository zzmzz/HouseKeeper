# E.V. 能力清单（答案空间）

> 这份文件**就是大模型看到的可选动作**。改这里 = 改模型的判断依据，不用动代码。
> 「辨析」是踩坑踩出来的，每条 ★ 对应一次真实事故——出了新问题就往这里加。
> 执行绑定（entity/service）在 `bindings.py`，两边的 id 必须一一对应，加载时会校验。

## 灯光

### light_living_on · 打开客厅灯
何时：客厅暗了、需要照明。
辨析：和 light_living_off 相反，务必区分开/关。

### light_living_off · 关闭客厅灯
何时：客厅灯开着要关掉。出现'关''关掉''别开了''不用开'等关闭意图。
辨析：和 light_living_on 字面像但意图相反。

### light_bed_on · 打开主卧灯
何时：主卧/卧室需要照明。
辨析：只针对卧室，别和客厅混。

### light_bed_off · 关闭主卧灯
何时：主卧灯要关掉。
辨析：和 light_bed_on 相反。

### kitchen_on · 打开厨房灯
何时：厨房需要照明、要做饭。
辨析：★别和 dining_on 混：做饭、灶台那边=厨房 kitchen_on，吃饭桌那边=餐厅 dining_on；同时注意别和 kitchen_off 开关反了。

### kitchen_off · 关闭厨房灯
何时：厨房灯要关掉。
辨析：和 kitchen_on 相反。

### dry_area_on · 打开干区灯
何时：卫生间干区（洗手台那边）要照明。
辨析：★干区灯只是洗手台照明：要取暖/洗澡前是 bath_heater_on，卫生间湿区没有独立灯；说『过道灯』是 hallway_on。

### dry_area_off · 关闭干区灯
何时：干区灯要关掉。
辨析：和 dry_area_on 相反。

### entry_on · 打开进门灯
何时：玄关/进门处要照明。
辨析：★『开门』是门禁 door_unlock，不是开进门灯；玄关灯只管照明。刚回家要一整套则是 scene_home。

### entry_off · 关闭进门灯
何时：进门灯要关掉。
辨析：★玄关和过道是两个键：门口/进门处=entry_off，走廊=hallway_off，别互相顶替。

### hallway_on · 打开过道灯
何时：过道要照明。
辨析：★和 entry_on 最易混：进门玄关那盏=entry_on，屋里走廊那盏=hallway_on。

### hallway_off · 关闭过道灯
何时：过道灯要关掉。
辨析：★关过道灯，不是关进门灯 entry_off；也别和 hallway_on 反了。

### bath_heater_on · 打开浴霸
何时：洗澡/洗漱前开浴霸。家里用得最频繁的设备之一。
辨析：★浴霸是取暖+照明，烧热水是 water_heater_on，洗手台照明是 dry_area_on——洗澡前常常三个都提到，按用户说的那个字面走。

### bath_heater_off · 关闭浴霸
何时：浴霸关掉。
辨析：★关浴霸≠关热水器 water_heater_off，别顺手把热水关掉。

### dining_on · 打开餐厅灯
何时：餐厅要照明、吃饭。
辨析：★餐厅灯：厨房是 kitchen_on，客厅是 light_living_on，三个房间别串。

### dining_off · 关闭餐厅灯
何时：餐厅灯关掉。
辨析：★关餐厅灯，不是 kitchen_off；也别和 dining_on 反了。

### wall_wash_on · 打开洗墙灯
何时：客厅那排洗墙灯（墙上的射灯带）。
辨析：★洗墙灯和客厅灯是同一面板的两个键，不是一个灯！用户说『客厅灯』是 light_living_on，说『洗墙灯』才是这个。

### wall_wash_off · 关闭洗墙灯
何时：关洗墙灯。
辨析：★别和客厅灯混。

### camera_dining_off · 关闭餐厅摄像头
何时：关餐厅摄像头。
辨析：★只关餐厅这一个：客厅是 camera_living_off，说『都关了/别拍了』才是 camera_all_off。

### camera_dining_on · 打开餐厅摄像头
何时：开餐厅摄像头。
辨析：★是摄像头不是灯（餐厅灯=dining_on）；客厅摄像头是 camera_living_on。

## 空调 / 新风

### ac_on · 打开空调（制冷降温）
何时：主人觉得热、闷、想凉快。夏天说『有点热』『好闷』『凉快一下』都是这个——开空调制冷。
辨析：★这是【客厅】空调。用户点名主卧/次卧要用 ac_bed_on / ac_second_on。★也不是 ac_warmer：『热』=降温=开空调，嫌冷要调温才是 ac_warmer。

### ac_off · 关闭空调
何时：不用空调了、关掉。
辨析：★这是【客厅】空调的关：主卧 ac_bed_off，次卧 ac_second_off；『关灯关空调睡了』这类一次多件事走 scene_sleep。

### ac_bed_on · 打开主卧空调
何时：要开主卧/卧室的空调。
辨析：★注意区分是哪个房间的空调：客厅=ac_on，主卧=ac_bed_on，次卧=ac_second_on。

### ac_bed_off · 关闭主卧空调
何时：关主卧空调。
辨析：★只关主卧：客厅=ac_off，次卧=ac_second_off，关错房间比不关更糟。

### ac_second_on · 打开次卧空调
何时：要开次卧的空调。
辨析：★次卧专用：用户只说『卧室』默认主卧 ac_bed_on，不点名房间是客厅 ac_on。

### ac_second_off · 关闭次卧空调
何时：关次卧空调。
辨析：★只关次卧，别关成主卧 ac_bed_off 或客厅 ac_off。

### fresh_air_living_on · 打开客厅新风
何时：只开客厅的新风。
辨析：★全屋新风=fresh_air_on，客厅=fresh_air_living_on，主卧=fresh_air_bed_on。

### fresh_air_bed_on · 打开主卧新风
何时：只开主卧的新风。
辨析：★只开主卧新风：全屋 fresh_air_on、客厅 fresh_air_living_on、次卧 fresh_air_second_on，四者按点名的房间选。

### fresh_air_off · 关闭全屋新风
何时：关新风。
辨析：★新风只有这一个总关、没有分房间的关；也别和关空调 ac_off 混，新风是换气不是制冷。

### fresh_air_second_on · 打开次卧新风
何时：只开次卧的新风。
辨析：★分清房间：全屋/客厅/主卧/次卧各有各的新风。

### fresh_air_on · 打开新风
何时：要求换气、通风、开新风。
辨析：★问『空气好不好/适合开窗吗』是 air_quality（询问）；说『换换气』才是执行。

## 窗帘

### bed_curtain_open · 拉开主卧布帘
何时：拉开主卧的布帘/窗帘。
辨析：★客厅的是 curtain_open。

### bed_curtain_close · 拉上主卧布帘
何时：拉上主卧的布帘/窗帘。
辨析：★主卧布帘：客厅那道纱帘是 curtain_close；如果同时还要关灯/空调就是 scene_sleep。

### curtain_open · 拉开客厅纱帘
何时：拉开客厅的纱帘。注意家里客厅布帘、主卧纱帘目前离线，只有客厅纱帘和主卧布帘能控。
辨析：★同时还要关灯/调空调那是 scene_sleep。

### curtain_close · 拉上客厅纱帘
何时：要求关窗帘、拉上。
辨析：★客厅纱帘：主卧是 bed_curtain_close；『关灯拉窗帘睡觉』这类多动作走 scene_sleep。

## 水 / 电器

### water_heater_on · 打开热水器
何时：烧热水、洗澡前开热水器。
辨析：★热水器≠浴霸。浴霸是取暖照明(bath_heater_on)，热水器是烧水。

### water_heater_off · 关闭热水器
何时：关热水器。
辨析：★热水器是烧水的总开关：浴霸是 bath_heater_off，热水循环是 zero_cold_water_off，三个别混。

### zero_cold_water_on · 打开零冷水
何时：开零冷水循环，让热水立刻出。
辨析：★和热水器主开关是两回事。

### zero_cold_water_off · 关闭零冷水
何时：关零冷水。
辨析：★只停循环、热水器仍开着：要断热水器本身是 water_heater_off。

### humidifier_on · 打开加湿器
何时：明确要求加湿、太干了要开加湿器——是执行动作。
辨析：★只是『问』湿度多少是 air_quality，不是开加湿器。

## 摄像头 / 门禁

### camera_living_off · 关闭客厅摄像头
何时：在家不想被拍，关客厅摄像头。
辨析：★只关客厅这一个：说『监控都关了/全部别拍』才是 camera_all_off，餐厅是 camera_dining_off。

### camera_living_on · 打开客厅摄像头
何时：重新打开客厅摄像头。
辨析：★只开客厅：餐厅是 camera_dining_on；『把摄像头都打开』没有对应能力，别拿 camera_all_off 反推。

### camera_all_off · 关闭所有摄像头
何时：『监控都关了』『别拍了』——一次关掉全部摄像头。
辨析：★只在出现『所有/都/全部』时用：点名某个房间要走 camera_living_off 或 camera_dining_off。

### door_unlock · 开门（门禁）
何时：给门开一下、开门禁放人进来。开了之后会自动回锁。
辨析：★『开门』是门禁，不是开进门灯(entry_on)。

## 查询

### air_quality · 查询家里空气/环境情况
何时：在『询问、了解』空气或环境好不好。『空气怎么样』『闷不闷』『适合开窗吗』『PM2.5多少』。
辨析：★这是查询、不是执行。问湿度≠开加湿器；问闷不闷≠开空调。

### temperature · 查询室内温度
何时：问家里/某个房间多少度、冷不冷热不热（询问语气）。
辨析：★问温度是查询；说『有点热』要降温是 ac_on。

### humidity · 查询室内湿度
何时：问湿度多少、干不干（询问语气）。
辨析：★问湿度是查询；要求加湿是 humidifier_on。

### device_state · 查设备当前开着还是关着
何时：问某个设备/灯现在的状态：『客厅灯开着吗』『空调开了没』『哪些灯还亮着』『家里还有什么没关』。
辨析：★这是查状态，不是控制。问『开着吗』别去开它。

### who_home · 查询家里有没有人 / 谁在家
何时：问谁在家、有没有人、某人到家没。
辨析：★问的是人：『谁在家/有人吗/他到家没』是这个；问设备开着没是 device_state。

## 脚本

### commute_eta · 算现在去公司要多久
何时：问通勤时间、路况、到单位/公司要多久。
辨析：★问的是路上耗时/路况：问外面天气、下不下雨、外面多少度是 weather。

### weather · 查天气
何时：问今天/现在天气怎么样、下不下雨、外面多少度。
辨析：★问『室内』温度是 temperature；问『外面/天气』才是这个。

### music_play · 播放音乐
何时：想听歌、放音乐、来点背景音乐。
辨析：★单纯想听歌就用它：只有『我回来了』式的一整套才是 scene_home，别把点歌当场景触发。

## 场景

### scene_sleep · 睡觉场景
何时：要睡觉了，一句话触发一整套。『睡了』『休息了』『关灯睡觉』，或一次点名多件事（关灯+拉窗帘+空调）。
辨析：★一次要求多个动作时优先归这里，别只挑其中一个。

### scene_home · 回家场景
何时：刚进门、回家了。
辨析：★整套回家流程：只要求给门开一下是 door_unlock，只要玄关亮灯是 entry_on，别用场景覆盖单一动作。
