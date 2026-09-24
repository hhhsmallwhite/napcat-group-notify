# napcat-group-notify

基于 [NapCat](https://github.com/NapNeko/NapCatQQ)（OneBot 11 协议端）的 **QQ 群成员定向私聊通知工具**：给名单上的群成员逐个发送私聊提醒，支持按姓名自动匹配群名片、随机间隔防风控、失败熔断、通路测试。

> 已在真实环境完整跑通：按 109 人名单匹配班级群成员，23 条群临时会话全部发送成功、零失败。

## 适用场景

| 场景 | 说明 |
|---|---|
| 班级通知 | 班长/老师提醒未交材料：注册报到、奖学金材料、学费缴纳、问卷统计 |
| 群管理提醒 | 提醒未完成接龙/打卡/问卷的成员，避免刷屏 @全体 |
| 活动组织 | 报名截止提醒、会议/值班/集合时间提醒 |
| 社群运营 | 按名单逐个触达，每人收到独立私聊而非群消息 |

**为什么不用群公告？** 群公告无法保证触达；逐个私聊能让「未完成的人」精确收到提醒，且不打扰已完成的人。

**为什么不用 QQ 官方机器人？** 官方机器人拿不到群成员列表、无法主动给未交互过的用户发私聊（主动消息有硬配额 304049/304050）。要按名单触达群成员，只能走 OneBot 协议端。

**为什么不用群发助手？** QQ 没有面向群成员的批量私聊功能；手动复制粘贴名单逐个发既慢又容易漏。

## 工作原理

```
名单(names.txt) ──► match_names.py ──► 姓名↔群名片匹配 ──► 待发送清单
                                                              │
                 send_messages.py ◄── config.json ◄───────────┘
                        │
                        ▼  OneBot 11 HTTP (127.0.0.1:3000)
                 NapCat（QQ 无头注入，OneBot 11 实现）
                        │
                        ▼  群临时会话（send_msg + private + group_id）
                 每个群成员收到独立私聊
```

- **匹配**：`get_group_member_list` 拉群名片，与名单精确匹配；编辑距离 ≤1 的近似对只提示、需人工裁决，绝不自动扩大发送范围
- **发送**：对非好友必须走「群临时会话」——`send_msg` + `message_type=private` + `group_id`，只能纯文字（图片必失败）
- **防风控**：随机间隔 20~40 秒、纯文字、连续失败 3 条立即熔断、逐条落盘结果

## 快速开始

### 0. 准备

- Windows + Python 3.10+
- 一台跑 [NapCat](https://napneko.github.io/) 的机器（Shell 版），且通知用 QQ 号已在目标群里
- NapCat 对 QQ NT 版本是**精确白名单**（构建号差一位都不行），部署前先确认你的 NapCat 版本支持哪个 QQ 版本

```bash
pip install numpy Pillow
cp config.example.json config.json   # 按注释填写：群号、测试QQ、消息文本、NapCat 目录
```

### 1. 开启 OneBot HTTP（登录后执行一次）

```bash
python scripts/napcat_webui.py enable-http
```

### 2. 登录通知用 QQ 号

推荐用自带面板（自动刷新二维码，永不过期）：

```bash
python scripts/qr_server.py --shell <NapCat目录>
# 浏览器打开 http://127.0.0.1:8899，手机 QQ 扫码 → 手机上点「确认登录」
```

> 最常见的假「二维码过期」：其实已经扫上了，只是手机上没点「确认登录」。
> 排查永远看 `python scripts/napcat_webui.py status` 里的 `loginPhase`。

### 3. 匹配名单

```bash
python scripts/match_names.py --list-groups   # 先找群号，写进 config.json
python scripts/match_names.py                 # 匹配，输出命中/未命中/疑似错字三档
```

### 4. 测试 → 发送

```bash
python scripts/send_messages.py --list   # 过目清单
python scripts/send_messages.py --test   # 发 1 条给自己人，确认收到
python scripts/send_messages.py --go     # 正式发送（随机间隔，失败熔断）
```

## 脚本一览

| 脚本 | 用途 |
|---|---|
| `scripts/match_names.py` | 名单 ↔ 群名片匹配，三档结果 + 疑似 OCR 错字提示 |
| `scripts/send_messages.py` | 批量群临时会话发送（--list / --test / --go） |
| `scripts/qr_server.py` | 登录面板：二维码自动刷新 + 实时登录阶段 |
| `scripts/napcat_webui.py` | NapCat WebUI API 客户端（status / ob11 / enable-http） |
| `scripts/bspatch.py` | 纯 Python BSDIFF40 实现（numpy 加速） |
| `scripts/apply_qq_update.py` | 应用 QQ 增量热更新包到副本（解决版本白名单问题） |

`docs/guide.md` 有从零搭建的完整细节（含 QQ 版本对齐、登录排查、12+ 个实测坑）。

## 重要已知坑（节选）

| 坑 | 解法 |
|---|---|
| NapCat 对 QQ 版本硬白名单、无回退 | 先查白名单再定 QQ 版本；可用热更新包把副本升上去（`apply_qq_update.py`） |
| 对非好友私聊失败 | 必须用 `send_msg` + `message_type=private` + `group_id`（群临时会话） |
| 临时会话发图片必失败 | 只发纯文字 |
| NapCat WebUI 全部 API 是 POST | 用 GET 一律 404 "Cannot GET" |
| `OB11Config/SetConfig` 报 config is empty | payload 必须是 `{"config": "<JSON字符串>"}`（先序列化再包一层） |
| 扫码后卡住不动 | 手机上没点「确认登录」，用 `CheckLoginStatus` 看 `loginPhase` |
| 重启后要重新扫码 | 新登录账号凭据未必持久化，属预期行为 |

## 风险与免责（务必阅读）

1. **本项目不修改、不逆向 QQ/NapCat 的任何代码**，只是调用 NapCat 暴露的 OneBot 11 与 WebUI 接口。
2. NapCat 走非官方协议，**违反《QQ 软件许可及服务协议》**。腾讯风控可能识别并限制账号：轻则临时限制发消息，重则冻结。**请自担风险，勿用主力账号高频操作。**
3. 本工具仅用于**向自己的群成员发送正当通知**。不得用于骚扰、广告、诈骗或任何违反法律法规与平台规则的用途，后果由使用者自负。
4. 请尊重群成员隐私：名单、匹配结果、发送记录不要公开传播。
5. 本项目与腾讯、NapCat 官方均无关联。项目按「现状」提供，不附带任何担保，详见 [LICENSE](LICENSE)。

## License

[MIT](LICENSE)
