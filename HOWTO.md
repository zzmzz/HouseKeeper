# 把 E.V. 换成你家的

整套流程与「哪个家」无关。换一个家只要改**两个文件**，然后跑一条命令。

## 1. 写你家的能力清单 `ev/capabilities.md`

这就是大模型看到的答案空间。格式：

```markdown
## 灯光

### light_living_on · 打开客厅灯
何时：客厅暗了、需要照明。
辨析：和 light_living_off 相反，务必区分开/关。
```

- `## 分组` 会变成提示词里的 `【灯光】`，帮模型（和人）建立结构
- `何时` 决定模型什么时候选它
- `辨析` 可以先不写 —— **冷启动会让 Claude 自动补**

> 只登记**日常真会说到**的设备。作者家有 480 个开关，但高频操作的不到 10 个；
> 全登记反而稀释模型注意力。**但凡会被说到的一定要登记** —— 漏登记时模型
> 会拿"最像的"顶上（见事故记录：说「开主卧空调」开了客厅空调）。

## 2. 写执行绑定 `ev/bindings.py`

id → 怎么干。id 必须和 md 一一对应，加载时会校验，漏了直接报错。

```python
'light_living_on': {
    'kind': 'hass_control',
    'service': 'switch.turn_on',
    'entity': 'switch.xxx',      # 你家的真实 entity_id
    'device': '客厅灯',           # 回答里点名用
    'reply': '客厅灯开了',
    'undo': 'light_living_off',  # 反向动作，纠正时用来撤销
},
```

四种 kind：
| kind | 干什么 | 关键字段 |
|---|---|---|
| `hass_control` | 调 HASS 服务 | service / entity / undo |
| `hass_query` | 读传感器并组织回答 | sensors |
| `script` | 外部接口（地图/天气/音乐） | script |
| `scene` | 多步场景 | steps |

高危动作加 `'confirm': True`，执行前会要求二次确认（作者用在门禁上）。

## 3. 配置

`.env`（权限 600）：
```
EV_API_URL=<OpenAI 兼容端点>
EV_API_KEY=<key>
EV_MODEL=<模型名>
```
离线任务走 `claude -p` 无头模式，用你已有的登录态，不需要额外 key。

`ev/resources.py` 里改 HASS 路径、家/公司地址、音乐播放器实体。

## 4. 冷启动

```bash
python3 ev/bootstrap.py
```

一条命令跑完：体检注册表 → 自动补辨析 → 造考卷 → 造教材 → 训练 →
自动选阈值 → 审计 L1 → 验收。约 15-20 分钟（取决于能力数量）。

## 5. 用起来 + 日常改进

```bash
python3 ev/agent.py            # dry-run，不会真动设备
python3 ev/agent.py --real     # 真实控制

python3 ev/daily.py            # 日常 loop，建议挂夜间定时
```

## 换一个智能家居平台？

只有 `ev/resources.py` 是 HASS 相关的（三个函数：读状态、调服务、渲染模板）。
换成米家/HomeKit/自研网关，改这一个文件即可，其余全部不动。
