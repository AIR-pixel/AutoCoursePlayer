# 网课自动播放器

基于 Selenium 的多站点网课视频自动播放工具。**无头后台运行、自动切换下一集、真实倍速**，
已看完的不会重播，中途关掉重跑会接着刷没看完的。

## 支持站点

| 站点 | 域名 | 状态 |
|---|---|---|
| 长江雨课堂 | `changjiang.yuketang.cn` / `www.yuketang.cn` | 稳定（原 1.x 全部功能） |
| 超星学习通 / 泛雅 | `chaoxing.com` 及各校泛雅站点 | 第一版，各校 DOM 差异大，可能需校准 |
| 智慧树 / 知到 | `zhihuishu.com` 各学习页（含 `ai-smart-course-student-pro`） | 已实测适配 2026 新版，倍速上限 1.5x |

站点选择器参考了 [ocsjs/ocsjs](https://github.com/ocsjs/ocsjs)（MIT，4766★，仍在活跃维护）
等开源项目，针对新形态课程页 `ai-smart-course-student-pro.zhihuishu.com` 也做了适配。

## 快速开始

**不用手填任何东西**：第一次运行会弹配置向导 —— 先选站点，再取登录凭据，
然后列出账号下的课程让你挑一门，接着开刷。凭据过期会提示重新获取。

### A. 不想装 Python：用打包好的 exe

从 [Release](https://github.com/AIR-pixel/MultiCourseAutoPlayer/releases/latest) 下载最新版 zip，
解压，双击 exe，按提示选站点、挑课即可。

- **Windows 10 / 11**，需要 **Edge** 或 **Chrome**（一般自带 Edge），驱动自动下载、走本地缓存。
- exe 无代码签名，SmartScreen 提示「未知发布者」时点「更多信息」→「仍要运行」。

### B. 从源码跑

```bash
pip install selenium
python main.py
```

### 配置向导第一步：选站点

```
========================================================
网课自动播放器 - 首次配置
========================================================

请选择要刷课的站点：
  [1] 长江雨课堂  (yuketang)
  [2] 超星学习通 / 泛雅  (chaoxing)
  [3] 智慧树 / 知到  (zhihuishu)

请输入序号（直接回车 = 1）:
```

选完站点后按该站点的方式取凭据、列课程。学习通/智慧树若接口列不出课程，
会让你手动粘课程地址（浏览器打开课程学习页，复制地址栏即可）。

### 智慧树 / 学习通：先登录一次（只需一次）

这两家的登录态读不出来（是 session cookie，不落盘），所以第一次要先登录一次、
让程序把 Cookie 抓下来存好。**存好之后就全自动了**，和雨课堂一样。

```bash
python tools\first_login.py zhihuishu     # 或 chaoxing
```

会**直接打开课程页**（程序会自动跳到登录页，不用你在登录页里找课程）→ 你扫码/账密
登录 → **登录后程序自动检测、自动抓 Cookie 写回 config.ini、自动继续**，不用回来按任何键。
凭据过期时主程序会**自动弹出窗口走这套流程**，一般不用手动跑；想主动刷新时才手动跑。

也可以直接把"藏得深"的课程页网址传给工具：
```bash
python tools\first_login.py "https://ai-smart-course-student-pro.zhihuishu.com/learnPage/.../.../327184?catalogActiveTab=personal" zhihuishu
```

### 手动获取 Cookie（工具用不了时的兜底）

如果上面工具在你机器上跑不通，可以手动抓：

1. 用 **Edge** 打开你的课程页并登录（必须登录成功、能看到视频列表）。
2. 按 `F12` 打开开发者工具 → 顶部切到 **网络（Network）** 标签。
3. 刷新页面（`F5`），在请求列表里随便点一个 `zhihuishu.com` 的请求。
4. 右侧 **标头（Headers）** → 找到 **请求标头（Request Headers）** 里的 `Cookie:` 一行，
   把冒号后面的整段内容复制下来。
5. 打开程序目录下的 `config.ini`，把这段粘到 `cookie = ` 后面保存。

注意：智慧树需要的是完整 Cookie 串（不止一个值），所以一定要复制**整行**，不是单个字段。
雨课堂则只需 `sessionid` 的值。

## 浏览器选择

`browser = auto` 时会**优先用系统默认浏览器**（读 Windows 注册表）。若默认是 Firefox
（本项目的 geckodriver 常下载不到），会自动回退到 **Edge**，再退到 Chrome。也可在
config.ini 里写死 `browser = edge` / `chrome`。
老版本"手动改 headless=false 后默认开 Chrome、没来得及登录就退出"的问题已修复：
现在凭据过期会自动弹 Edge 登录窗口，登录后自动继续。

## 配置项（config.ini）

| 项 | 默认 | 说明 |
|---|---|---|
| `site` | `yuketang` | 站点：`yuketang` / `chaoxing` / `zhihuishu`。清空 = 下次重选 |
| `headless` | `true` | 无窗口运行。挂后台用 `true` |
| `browser` | `auto` | `chrome` / `edge` / `auto` |
| `ui` | `auto` | 雨课堂前端版本，其它站点忽略 |
| `course_url` | — | 课程地址。清空 = 下次重新挑课 |
| `cookie` | — | 凭据。雨课堂 sessionid / 智慧树 arn / 超星整段 Cookie |
| `speed` | `2` | 倍速。站点有更低上限时自动夹住（智慧树 1.5、超星 2） |
| `implicitly_wait` | `10` | 元素查找超时（秒） |

想换站点：把 `site` 清空再运行。想换课程：把 `course_url` 清空再运行。

## 各站点注意事项

- **雨课堂**：无头模式下切窗口会触发防刷暂停，脚本会顶回去，仍推荐无头。已有 2 倍速、
  崩溃重建、误报完成防护等大量实测修复（见技术细节）。
- **智慧树**：官方倍速上限 1.5x，**超过有封号风险**，程序已强制夹住。2026 版新形态课程页
  已实测适配：目录是三级折叠，完成标记是「必学 X/Y」和勾选图标；小节里 PPT 和多个视频
  并存，程序会自动点开未完成的 mp4 资源再播放。首次学习要签「学前必读/承诺书」，
  脚本会尝试点掉；弹窗测验会随机选答关闭。有习惯分要求的课程，每天需规律学习约半小时
  才得分，脚本只保证看完视频，不保证习惯分。
- **超星学习通**：视频常在**跨域 iframe** 里，脚本会尝试进入同源 iframe 锁倍速；
  跨域时可能锁不住（不影响播放与进度上报）。高倍速/夜间大量运行可能导致学习记录
  清空回退，已把上限压到 2x。各学校泛雅站点 DOM 差异大。

## 站点对不上怎么办：`probe_site.py`

某个站点读不到小节、倍速无效时，用探测器 dump 页面结构，拿 class 采样去校准
`sites/` 里的选择器（只读，不点视频、不改配置）：

```bash
python tools/probe_site.py "https://你的课程地址"
```

会打开一个**可见窗口** —— 先登录、点进课程学习页，回控制台按回车，
程序目录下会生成 `_probe_<域名>_<时间>/report.txt` 和完整页面源码。

## 架构

```
core/                 通用内核，与站点无关
  browser.py          浏览器探测/创建/探活/崩溃重建
  player.py           倍速锁/静音/防暂停续播/结束探测
  engine.py           主循环、容错、选课播放调度、日志
sites/                站点适配器，每个站点一个文件
  base.py             SiteAdapter 接口
  yuketang.py / chaoxing.py / zhihuishu.py
  __init__.py         注册表
firstrun.py           配置向导（按站点分派）
refresh_cookie.py     凭据获取 + config 读写 + 输出初始化
```

内核只认 `SiteAdapter` 接口。**新增站点** = 在 `sites/` 加一个文件实现接口 +
在 `sites/__init__.py` 注册一次，内核一行不用改。接口定义见 `sites/base.py`。

## 打包

双击 `build.bat`（或 `python tools/build_exe.py`）。产物在 `dist/`：单文件 exe +
含使用说明的 zip。已发布版本默认拒绝覆盖，加 `--force` 才重打。

## 来源与授权

- 本项目基础来自 [LetMeFly666/YuketangAutoPlayer](https://github.com/LetMeFly666/YuketangAutoPlayer)（雨课堂部分），感谢原作者。
- 智慧树/学习通选择器参考 [ocsjs/ocsjs](https://github.com/ocsjs/ocsjs)（MIT）等开源项目。
- 代码按 **LGPL-2.1** 授权，见 `LICENSE`。

## 免责声明

仅供 Selenium 技术学习与自动化实践。请自行确认用途符合所在学校/平台规定，后果自负。
