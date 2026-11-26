# 项目架构

一页讲清"代码怎么组织、一次刷课走什么流程"。使用者看 README，维护者看这里。

## 一句话

**内核只认 `SiteAdapter` 接口，站点差异全在 `sites/`；入口只做调度。**
新增一个平台 = 在 `sites/` 加一个文件实现接口 + 注册表加一行，内核一行不用改。

## 目录结构

```
YuketangAutoPlayer/
├─ main.py                 入口：读配置 → 选站点 → 建浏览器 → 跑引擎
│                          开关：--site 选站点 / --cookie 只刷新凭据
├─ firstrun.py             配置向导：选站点 → 取凭据 → 列课程（按适配器分派）
├─ refresh_cookie.py       凭据读写、config.ini 读写、输出编码/停驻
│
├─ core/                   【通用内核】与具体站点无关
│  ├─ browser.py           浏览器探测（读系统默认）/ 创建 / 探活 / 崩溃重建
│  ├─ engine.py            主循环：选课 → 打开 → 播放 → 切集；容错；日志
│  ├─ player.py            倍速锁 / 静音 / 防暂停续播 / 结束探测（原生 video）
│  └─ relogin.py           凭据过期时：开可见浏览器 → 进课程页 → 自动抓 Cookie
│
├─ sites/                  【站点适配器】每个平台一个文件
│  ├─ base.py              SiteAdapter 接口定义 + 通用默认实现
│  ├─ __init__.py          注册表：get_adapter(key) / guess_adapter_key(url)
│  ├─ yuketang.py          雨课堂（新版/旧版两套 DOM）
│  ├─ chaoxing.py          超星学习通（视频在跨域 iframe）
│  └─ zhihuishu.py         智慧树（2026 新形态课程，1x 原速不锁倍速）
│
├─ tools/
│  ├─ build_exe.py         打包：PyInstaller + 完整用户 zip（含 3 个 bat）
│  ├─ smoke_test.py        冒烟测试：不登录/不开浏览器，7 项检查
│  ├─ probe_site.py        站点探测器：dump 页面 class/iframe/video，校准选择器
│  └─ first_login.py       手动刷新凭据（源码方式；打包版用「③」bat）
│
├─ docs/技术细节.md         实测踩坑记录（崩溃、误报、倍速失效…）
├─ config.ini.example      配置项说明样板
└─ dist/                   打包产物（exe + zip）
```

## 一次刷课的调用链

```
用户双击「② 开始刷课.bat」
   └─ exe（main.py）
        ├─ load_settings()          读 config.ini（site/course_url/cookie/speed…）
        ├─ needs_setup()?           缺配置 → firstrun 向导
        ├─ get_adapter(site)        从注册表取站点适配器
        ├─ BrowserManager.start()   建浏览器（auto→系统默认/Firefox 回退 Edge）
        └─ Engine.run()
             ├─ goto_course_page()
             │    ├─ 打开 course_url → 注入 Cookie → 重开
             │    └─ 停在登录页？→ relogin.interactive_login()
             │                        └─ 开可见浏览器 → 用户登录 → 自动抓 Cookie → 写回 config
             └─ 循环 finish1video()
                  ├─ site.prepare_course_page()      渲染/读取小节列表
                  ├─ site.scan_js()                  一次 JS 挑出下一个未完成小节
                  ├─ site.open_lesson()              点开小节
                  ├─ site.after_open_lesson()        点开小节内的视频资源（智慧树需要）
                  ├─ player.setup_play_monitor()     续播/结束探测/防暂停
                  ├─ site.use_speed_lock?            装倍速锁（智慧树跳过，用 1x）
                  └─ 播放循环：ended / 回退 / 站点判据 / 卡死兜底 → 切下一集
```

## 站点适配器接口（sites/base.py）

分四组，内核只通过这些方法接触站点：

| 组 | 方法 | 作用 |
|---|---|---|
| 身份 | `key` `name` `hosts` `home_url` `match_host` | 站点标识、域名匹配 |
| 凭据 | `cookie_dict` `inject_cookie` `fetch_courses` `course_url_of` | 凭据注入、列课程、拼课程地址 |
| 页面 | `is_login_page` `prepare_course_page` `scan_js` `capture_open_js` `after_open_lesson` `handle_popups` | 登录判定、小节扫描、打开视频、弹窗 |
| 播放 | `use_speed_lock` `MAX_SPEED` `extra_player_js` `finished_extra_js` `cleanup_js` | 倍速策略、完成判据、清理 |

## 三个关键设计决策

1. **一次 JS 扫描**（`scan_js`）而不是逐个元素查询：81 个小节从 30 秒降到 0.02 秒；
   用 `textContent` 而非 `.text`（后者会把某些层读成空串，导致已完成被误判重播）。
2. **站点自带倍速锁不一定适用**：雨课堂/超星认原生 `playbackRate`，可以锁；
   智慧树自定义播放器不认，强锁 1.5x 反而让进度变成 0.2x，所以本站用 `use_speed_lock=False` + 1x。
3. **凭据获取分两种**：雨课堂 sessionid 是持久 cookie，读 Firefox 库即得（全自动）；
   智慧树/学习通是 session cookie，只在内存，必须登录一次抓下来（`relogin.py`）。

## 打包交付物（dist/网课自动播放器-vX.zip）

解压后是一个文件夹，含 3 个双击入口（只调 exe，不依赖系统 Python）：

- `① 选择站点.bat` → `exe --site`
- `② 开始刷课.bat` → `exe`
- `③ 手动获取Cookie.bat` → `exe --cookie`

外加 exe、使用说明.txt、LICENSE、作者主页.url。所有 bat 末尾 `pause`，
即使 exe 异常退出也不会"闪一下就没了"；exe 内还有顶层异常兜底打印原因。
