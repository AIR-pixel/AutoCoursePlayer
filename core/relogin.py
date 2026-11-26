'''
登录桥接：打开可见浏览器，直接进入课程页，等用户登录后自动抓取完整 Cookie。

设计要点（针对实测踩过的坑）：
  1. 直接打开 course_url（课程页），它会自动跳登录页 —— 用户不用在裸登录页里
     找那个"藏得很深"的课程。登录成功后浏览器自己跳回课程页。
  2. **自动轮询检测登录成功**，不依赖用户按回车 —— 老版就是等回车/等不到就退出，
     用户"还没来得及登录，程序自己退出完了"。现在登录成功后程序自动继续。
  3. 登录成功后访问一次学习页域让子域 Cookie 下发，再抓全量（带 domain/path）。
  4. 写回 config.ini 的 cookie + cookies_full，之后主程序全自动。

被两处调用：
  - tools/first_login.py（用户手动跑）
  - core/engine.py（cookie 过期时自动触发）
'''
import json
import time

import refresh_cookie

LOGIN_MARKS = ('login.zhihuishu', 'passport', '/login', 'sso', 'cas')


def _is_login_page(d) -> bool:
    url = (d.current_url or '').lower()
    title = d.title or ''
    if any(m in url for m in LOGIN_MARKS):
        return True
    if '登录' in title and '课程' not in title and '学习' not in title:
        return True
    return False


def interactive_login(course_url: str, site_key: str, timeout: int = 300,
                      log=print) -> bool:
    """打开可见浏览器 → 进课程页 → 等登录 → 自动抓 Cookie 写回 config。

    返回 True 表示拿到 Cookie 并写入成功。
    """
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options as EdgeOptions

    log('=' * 56)
    log('需要重新登录（会自动打开一个浏览器窗口）')
    log('=' * 56)
    log('即将打开浏览器并直接进入你的课程页。')
    log('页面会自动跳到登录页 —— 请在窗口里扫码或输入账号密码。')
    log('登录成功后程序会**自动继续**，不用回来按任何键。')
    log(f'（最多等待 {timeout // 60} 分钟）')
    log('')

    opt = EdgeOptions()
    opt.add_argument('--start-maximized')
    opt.page_load_strategy = 'eager'
    try:
        d = webdriver.Edge(options=opt)
    except Exception as e:
        log(f'启动 Edge 失败: {type(e).__name__}: {e}')
        return False

    got_cookies = None
    try:
        d.set_page_load_timeout(60)
        # 关键：直接打开课程页（不是裸登录页），它自己会跳登录；登录后跳回课程页
        try:
            d.get(course_url)
        except Exception:
            pass
        time.sleep(3)

        log('请在浏览器窗口里登录（登录后本窗口会自动继续，无需操作）...')
        deadline = time.monotonic() + timeout
        last_tick = 0
        while time.monotonic() < deadline:
            if not _is_login_page(d):
                # 离开登录页了，再等几秒确认稳定 + 让子域 Cookie 下发
                time.sleep(3)
                if not _is_login_page(d):
                    log('检测到登录成功，正在收集 Cookie...')
                    break
            elapsed = int(time.monotonic() - (deadline - timeout))
            if elapsed // 30 > last_tick:
                last_tick = elapsed // 30
                log(f'  等待登录中... {elapsed}s')
            time.sleep(2)
        else:
            log(f'等待登录超时（{timeout}s），未自动完成。')
            return False

        # 再访问一次课程页，确保学习页域的 Cookie（acw_tc 等）都下发
        try:
            d.get(course_url)
        except Exception:
            pass
        time.sleep(3)

        cookies = d.get_cookies()
        if not cookies:
            log('没抓到 Cookie，可能没登录成功。')
            return False
        got_cookies = cookies
        log(f'抓到 {len(cookies)} 条 Cookie（内容不回显）')
    finally:
        # 无论成功失败都关窗口；成功提示独立于登录窗口
        try:
            d.quit()
        except Exception:
            pass

    if not got_cookies:
        return False

    # 写回 config
    header = '; '.join(f"{c['name']}={c['value']}" for c in got_cookies)
    full = json.dumps(got_cookies, ensure_ascii=False)
    cfg_path = refresh_cookie.config_path()
    refresh_cookie.set_config_value(cfg_path, 'site', site_key)
    refresh_cookie.write_cookie(header, cfg_path)
    refresh_cookie.set_config_value(cfg_path, 'cookies_full', full)
    # 把这次的课程页地址也存下来（用户可能换了章节）
    refresh_cookie.set_config_value(cfg_path, 'course_url', course_url)
    log(f'已写入 config.ini，课程地址已更新。')
    return True
