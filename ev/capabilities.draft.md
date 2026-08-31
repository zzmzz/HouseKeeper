# E.V. 能力清单（答案空间）

> 由 scaffold.py 从 HASS 实体自动生成的**草稿**。过一遍：删掉用不到的、改中文名、补分组。
> 「辨析」留空即可 —— bootstrap.py 会让 Claude 自动补。

## 灯光

### light_living_on · 打开客厅灯
何时：进客厅、看电视、离家关灯时说「开/关客厅灯」

### light_living_off · 关闭客厅灯
何时：关掉客厅灯。

### light_wallwash_on · 打开洗墙灯
何时：想要客厅氛围光而不开主灯时说「开洗墙灯」

### light_wallwash_off · 关闭洗墙灯
何时：关掉洗墙灯。

### light_dining_on · 打开餐厅灯
何时：吃饭前后说「开/关餐厅灯」

### light_dining_off · 关闭餐厅灯
何时：关掉餐厅灯。

### light_dining_spot_on · 打开餐厅射灯
何时：餐厅只想要点缀照明时说「开餐厅射灯」

### light_dining_spot_off · 关闭餐厅射灯
何时：关掉餐厅射灯。

### light_kitchen_on · 打开厨房灯
何时：做饭、洗碗时说「开/关厨房灯」

### light_kitchen_off · 关闭厨房灯
何时：关掉厨房灯。

### light_hallway_on · 打开过道灯
何时：夜里走廊过路时说「开过道灯」

### light_hallway_off · 关闭过道灯
何时：关掉过道灯。

### light_entry_on · 打开进门灯
何时：到家进门或出门前说「开/关进门灯」

### light_entry_off · 关闭进门灯
何时：关掉进门灯。

### light_bed_main_on · 打开主卧灯
何时：睡前躺下说「关主卧灯」，早上说「开主卧灯」

### light_bed_main_off · 关闭主卧灯
何时：关掉主卧灯。

### light_bed_second_on · 打开次卧灯
何时：次卧有人住或进去拿东西时说「开/关次卧灯」

### light_bed_second_off · 关闭次卧灯
何时：关掉次卧灯。

### light_dryarea_on · 打开干区灯
何时：洗漱、照镜子时说「开干区灯」

### light_dryarea_off · 关闭干区灯
何时：关掉干区灯。

### light_balcony_on · 打开阳台灯
何时：晾衣服、晚上去阳台时说「开阳台灯」

### light_balcony_off · 关闭阳台灯
何时：关掉阳台灯。

### light_balcony_north_on · 打开北阳台灯
何时：去北阳台洗衣、取东西时说「开北阳台灯」

### light_balcony_north_off · 关闭北阳台灯
何时：关掉北阳台灯。

### light_bath_on · 打开浴室灯
何时：进卫生间洗澡时说「开/关浴室灯」

### light_bath_off · 关闭浴室灯
何时：关掉浴室灯。

## 空调 新风

### ac_living_on · 打开客厅空调
何时：客厅太热太冷时说「开/关客厅空调」

### ac_living_off · 关闭客厅空调
何时：关掉客厅空调。

### ac_bed_main_on · 打开主卧空调
何时：睡前或起床时说「开/关主卧空调」

### ac_bed_main_off · 关闭主卧空调
何时：关掉主卧空调。

### ac_bed_second_on · 打开次卧空调
何时：次卧住人时说「开/关次卧空调」

### ac_bed_second_off · 关闭次卧空调
何时：关掉次卧空调。

### fresh_air_all_on · 打开全屋新风
何时：觉得屋里闷或外面空气差时说「开/关全屋新风」

### fresh_air_all_off · 关闭全屋新风
何时：关掉全屋新风。

### fresh_air_living_on · 打开客厅新风
何时：只想给客厅换气时说「开客厅新风」

### fresh_air_living_off · 关闭客厅新风
何时：关掉客厅新风。

### fresh_air_bed_main_on · 打开主卧新风
何时：主卧睡觉关门后说「开主卧新风」

### fresh_air_bed_main_off · 关闭主卧新风
何时：关掉主卧新风。

### fresh_air_bed_second_on · 打开次卧新风
何时：次卧住人换气时说「开次卧新风」

### fresh_air_bed_second_off · 关闭次卧新风
何时：关掉次卧新风。

### air_purifier_on · 打开空气净化器
何时：空气差、有异味时说「开/关空气净化器」

### air_purifier_off · 关闭空气净化器
何时：关掉空气净化器。

## 窗帘

### curtain_living_on · 拉开客厅窗帘
何时：看电视或早上采光时说「拉上/打开客厅窗帘」

### curtain_living_off · 拉上客厅窗帘
何时：关掉客厅窗帘。

### curtain_bed_main_on · 拉开主卧窗帘
何时：睡前和起床时说「关上/打开主卧窗帘」

### curtain_bed_main_off · 拉上主卧窗帘
何时：关掉主卧窗帘。

## 水 电器

### water_heater_on · 打开热水器
何时：准备洗澡前说「开热水器」

### water_heater_off · 关闭热水器
何时：关掉热水器。

### zero_cold_water_on · 打开零冷水
何时：想让龙头马上出热水时说「开零冷水」

### zero_cold_water_off · 关闭零冷水
何时：关掉零冷水。

### bath_heater_on · 打开浴霸风暖
何时：冬天洗澡前说「开浴霸」暖一下浴室

### bath_heater_off · 关闭浴霸风暖
何时：关掉浴霸风暖。

### bath_vent_on · 打开浴室换气
何时：洗完澡或有异味时说「开浴室换气」

### bath_vent_off · 关闭浴室换气
何时：关掉浴室换气。

### humidifier_living_on · 打开加湿器
何时：干燥、嗓子不舒服时说「开/关加湿器」

### humidifier_living_off · 关闭加湿器
何时：关掉加湿器。

### water_dispenser_on · 打开饮水机
何时：要接热水泡茶时说「开饮水机」

### water_dispenser_off · 关闭饮水机
何时：关掉饮水机。

### dryer_on · 打开干衣机
何时：衣服放进去后说「开干衣机」

### dryer_off · 关闭干衣机
何时：关掉干衣机。

### fish_tank_on · 打开鱼缸
何时：喂鱼、换水或想关掉鱼缸时说「开/关鱼缸」

### fish_tank_off · 关闭鱼缸
何时：关掉鱼缸。

### socket_entry_on · 打开玄关插座
何时：给玄关的电器断电或通电时说「开/关玄关插座」

### socket_entry_off · 关闭玄关插座
何时：关掉玄关插座。

## 摄像头 门禁

### camera_living_on · 打开客厅摄像头
何时：出门时说「开客厅摄像头」，在家不想被拍时说「关掉」

### camera_living_off · 关闭客厅摄像头
何时：关掉客厅摄像头。

### camera_dining_on · 打开餐厅摄像头
何时：离家布防或在家关闭监控时说「开/关餐厅摄像头」

### camera_dining_off · 关闭餐厅摄像头
何时：关掉餐厅摄像头。

### door_lock_on · 打开门禁
何时：有人按门铃或家人到楼下时说「开门」放行
