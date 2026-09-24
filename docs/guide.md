# 从零搭建指南

> 面向没有部署经验的读者。本指南不含任何真实账号信息；所有 `<尖括号>` 处替换为你的实际值。

## 1. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│  名单（names.txt，一行一个姓名）+ 通知文本（config.json）        │
└──────────────┬──────────────────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────────────────┐
│  [匹配层] scripts/match_names.py                              │
│  get_group_member_list 拉群名片 → 与名单精确匹配               │
│  输出三档：精确命中 / 名单未命中（含疑似OCR错字）/ 群内多出      │
└──────────────┬──────────────────────────────────────────────┘
               ▼  OneBot 11 HTTP  http://127.0.0.1:3000
┌─────────────────────────────────────────────────────────────┐
│  [协议层] NapCat（QQ 无头注入，OneBot 11 实现）                 │
│  NapCatWinBootMain.exe → 注入 QQ.exe（无界面运行）              │
└──────────────┬──────────────────────────────────────────────┘
               ↕ WebUI 管理接口 http://127.0.0.1:6099（登录/配置）
┌─────────────────────────────────────────────────────────────┐
│  [客户端层] QQ NT（版本必须在 NapCat 白名单内）                  │
└─────────────────────────────────────────────────────────────┘
```

## 2. 部署 NapCat

- 用 **Shell 版**（NapCat.Shell.zip），不要用 OneKey 一键包（其内置 QQ 下载地址经常 404）
- **先查 NapCat 支持的 QQ 版本，再准备对应版本 QQ**——顺序不能反
- NapCat 对 QQ NT 版本是**精确构建号白名单、没有任何回退**。查看方法：在 NapCat 的
  `napcat.mjs` 里搜 `9\.9\.\d+-\d+` 模式，可见形如 `"9.9.33-52230-x64": {send, recv}`
  的表；版本对不上会直接报错 `PacketBackend 不支持当前QQ版本架构`

### QQ 版本不在白名单里怎么办（按优先级）

1. **热更新包方案**：QQ 会把升级包下载到 `<QQ目录>/versions/<旧版>-<新版>.zip` 但常常
   从不应用（`versions/config.json` 里 `readyVersion` 为空即是信号）。如果这个「新版」
   恰好在白名单里，用 `apply_qq_update.py` 把它打到**副本**上（零下载）：
   ```bash
   python scripts/apply_qq_update.py --zip "<QQ目录>/versions/旧-新.zip" \
       --src "<当前QQ目录>" --dst "<副本目录>"
   ```
   全程只读源目录；每个产物都会与补丁包内的 size/md5 校验。
2. 浏览器从 im.qq.com 下载新版（命令行直链下载会被反爬拦，返回 403）。

### 启动器

NapCat 官方 `launcher.bat` 靠注册表 `HKLM\...\Uninstall\QQ` 定位 QQ——**便携/绿色版
没有这个键，必然失败**。需要自写 bat（写死 QQ 路径）：

```bat
set "QQPATH=<副本目录>\QQ.exe"
set "NAPCAT_LOAD_PATH=<shell目录>\loadNapCat.js"
set "NAPCAT_INJECT_PATH=<shell目录>\NapCatWinBootHook.dll"
set "NAPCAT_LAUNCHER_PATH=<shell目录>\NapCatWinBootMain.exe"

echo (async () =^> {await import("file:///<shell目录>/napcat.mjs")})() > "%NAPCAT_LOAD_PATH%"
"%NAPCAT_LAUNCHER_PATH%" "%QQPATH%" "%NAPCAT_INJECT_PATH%" %*
```

**两条硬要求**：
- 必须**管理员运行**（注入 hook DLL 需要提权；可用 `net session` 自检后
  `Start-Process -Verb RunAs` 自动提权）
- bat 文件必须**纯 ASCII**（中文注释在 cmd 代码页切换时乱码；`%~dp0` 尾部反斜杠会吃引号）

## 3. 登录（最容易卡住的一步）

推荐 `qr_server.py` 面板（自动刷新二维码 + 实时登录阶段），排查时用
`napcat_webui.py status` 看状态机：

| loginPhase | 含义 | 处理 |
|---|---|---|
| `waiting_qrcode` | 还没扫 | 对面板二维码重新扫 |
| `qrcode_scanned` + `qrLoginAccepted:false` | **扫了但手机没点确认** | 手机上点「确认登录」——这是最常见的假「二维码过期」 |
| `ready` + `isLogin:true` | 成功 | 可以配置 OneBot 了 |

其他要点：

- NapCat 刷新几次二维码后会**主动放弃**（进程活着但不再生成新码），判断依据是
  `cache/qrcode.png` 的 mtime 不再变化——用面板的 `RefreshQRcode` 接口主动刷新即可
- 报「当前账号已登录，无法重复登录」：该号同时登在 QQ 客户端上（同端互斥）。
  这类错误常是**瞬时的**，重试可能自己过；或把客户端上的同号退出
- 二维码只有 147×147，直接扫很难识别：用 Pillow `Image.NEAREST` 放大 8 倍补白边
  （面板已内置）；LANCZOS 会把模块边缘插糊，不要用
- 新登录账号的凭据**未必持久化**：重启 NapCat/电脑后可能需要重新扫码，属预期行为

## 4. 开启 OneBot HTTP

登录成功后（且只有登录成功后）才能写 OB11 配置：

```bash
python scripts/napcat_webui.py enable-http
```

要点：`SetConfig` 的 payload 必须是 `{"config": json.dumps(cfg)}`——先把配置整体
序列化成字符串再包一层，直接传对象报 `config is empty`。成功后 NapCat 落地
`config/onebot11_<uin>.json`（持久化，重启后自动生效），验证：

```bash
curl -X POST http://127.0.0.1:3000/get_login_info -H "Content-Type: application/json" -d "{}"
```

## 5. 名单匹配与 OCR 复核

- 名单放 `names.txt`（一行一个真实姓名），与**群名片**精确匹配
- 让群成员把群名片改成真实姓名是成本最低的匹配手段；改完记得 `no_cache:true` 重拉
- **截图 OCR 必有错字**（形近字实测错误率 3/109）：把存疑单元格单独裁出、放大 6-8 倍
  （LANCZOS）再逐字核对，别直接信整图阅读
- 编辑距离 ≤1 的近似对全部列出来**人工裁决**；确认是同一人的写进 `config.json` 的
  `alias` 表（`[{"name": "名单写法", "user_id": QQ号}]`）
- 群里有成员没写群名片 → 让其补群名片，或从发送范围排除
- 名单规模和群人数是否匹配先对一下：名单往往是全年级的，班群只有几十人，
  交集才需要发

## 6. 发送与风控自律

```bash
python scripts/send_messages.py --list   # 过目清单
python scripts/send_messages.py --test   # 发 1 条给自己人验证通路
python scripts/send_messages.py --go     # 正式发送
```

四条纪律，缺一不可：

1. **`--test` 先行**——临时会话通路受群设置影响（群主可关闭、成员可拒绝陌生人），
   测通了再发
2. **随机间隔 20~40 秒**——固定/过短间隔是机器人典型特征；几十条的消息预计要
   20~60 分钟，赶时间就提前开始
3. **失败即停**——连续 3 条失败立即熔断；任何风控类错误都不要重试硬闯
4. **纯文字**——临时会话发图片必失败（NapCat 已知问题），链接/文件是风控重灾区

单次建议 ≤ 30 条。发送完成后关闭 NapCat 进程，不要让非官方客户端长期挂在线上。

## 7. 环境坑速查

| 坑 | 解法 |
|---|---|
| WebUI API 用 GET 全 404 | NapCat WebUI **全部 API 一律 POST**，封装客户端别套 REST 惯例 |
| bat 中文乱码 | bat 写纯 ASCII，写完校验无非 ASCII 字节 |
| Python 3.13 装不上 bsdiff4 | 无官方 wheel，用本仓库的纯 Python 实现（`bspatch.py`） |
| Pillow/opencv 装不上 | 国内镜像可能缺 3.13 轮子，走官方 PyPI 源 |
| 群成员列表看不到刚改的群名片 | `get_group_member_list` 加 `no_cache: true` |
