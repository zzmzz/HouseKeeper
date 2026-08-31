# 把 E.V. 换成你家的

整套流程与「哪个家」无关。**你不用手写能力清单和执行绑定 —— 它们从你家的 HASS 实体自动生成。**

## 1. 配置

`.env`（复制 `.env.example`，权限设 600）：
```
EV_API_URL=<OpenAI 兼容端点>       # 运行时兜底用，要快
EV_API_KEY=<key>
EV_MODEL=<模型名>
EV_HASS_BIN=/path/to/hass-agent/bin/hass
EV_BAIDU_AK=<可选，通勤时长脚本用>
```
离线高阶任务走 `claude -p` 无头模式，用你已有的登录态，**不需要额外 key**。

## 2. 自动生成能力清单（不用手写）

```bash
python3 ev/scaffold.py --max 35
```

它会：
1. 拉你家全部在线可控实体（switch / light / cover / humidifier）
2. **去重** —— 同一物理设备常被多个集成暴露两遍
3. 让 Claude 挑出「日常真会用语音说到的」，起中文名、分组、判断哪些需要二次确认
4. 生成 `capabilities.draft.md`（答案空间）+ `bindings.draft.py`（执行绑定）

**产出是草稿，需要你过一遍**（这一步值得花十分钟）：

- **删掉用不到的** —— 作者家有 480 个开关，日常真会说的不到 10 个；登记太多反而稀释模型注意力
- **但凡会被说到的一定要留** —— 漏登记时模型会拿「最像的」顶上
  （实际事故：说「开主卧空调」结果开了客厅空调）
- **核对中文名和实体对不对得上** —— 名字是回答里点名用的，错了你会不知道它动了哪台设备
- **「辨析」不用写** —— 冷启动会让 Claude 自动补

满意后去掉 `.draft` 后缀即可（或直接 `--overwrite` 就地生成）。

> 补充查询类 / 脚本类 / 场景类能力（如「家里空气怎么样」「去公司要多久」「我要睡了」）
> 目前需手工加进这两个文件，格式照现有的写即可 —— scaffold 只生成设备控制类。

## 3. 冷启动

```bash
python3 ev/bootstrap.py
```

一条命令跑完：体检注册表 → 自动补辨析 → 造考卷 → 造教材 → 训练 →
自动选阈值 → 审计 L1 → 验收。约 15-20 分钟（取决于能力数量）。

## 4. 用起来 + 日常改进

```bash
python3 ev/agent.py            # dry-run，不会真动设备
python3 ev/agent.py --real     # 真实控制

python3 ev/daily.py            # 日常 loop，建议挂夜间定时
python3 make_report.py         # 把任意一次 run 渲染成演示网页
```

## 四种能力类型

`bindings.py` 里的 `kind` 决定怎么执行：

| kind | 干什么 | 关键字段 |
|---|---|---|
| `hass_control` | 调 HASS 服务 | `service` / `entity` / `undo`（反向动作，纠正时撤销用） |
| `hass_query` | 读传感器并组织回答 | `sensors`（标签 → 实体） |
| `script` | 外部接口（地图 / 天气 / 音乐） | `script` |
| `scene` | 多步场景 | `steps` |

高危动作加 `'confirm': True`，执行前要求二次确认（作者用在门禁上）。

## 换一个智能家居平台？

只有 `ev/resources.py` 是 HASS 相关的（读状态、调服务、渲染模板三个函数）。
换成米家 / HomeKit / 自研网关，改这一个文件即可，其余全部不动。
