'''
首次登录桥接：用可见浏览器登录一次，程序自动抓取完整 Cookie 存进 config。

为什么需要它：
  雨课堂的 sessionid 是持久 cookie，能从 Firefox 库直接读，所以全自动。
  智慧树/学习通的登录态读不出来（session cookie 只在内存 / 混淆存储），
  只能登录一次、把 Cookie 抓下来存好。存好之后主程序就全自动了。

用法：
    python tools\first_login.py zhihuishu
    python tools\first_login.py chaoxing

流程：
  1. 打开可见 Edge → 目标站点登录页
  2. 你用扫码 / 账号密码登录（程序不碰你的密码）
  3. 登录成功后回这个窗口按回车
  4. 程序抓取当前所有 Cookie，写进 config.ini 的 cookie 字段
  5. 自动打开课程页验证：能不能进、要不要手动粘地址
'''
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import refresh_cookie

refresh_cookie.setup_output()
refresh_cookie.bypass_proxy_for_localhost()

SITES = {
    'zhihuishu': {
        'name': '智慧树 / 知到',
        'login': 'https://login.zhihuishu.com/',
        'target': 'https://ai-smart-course-student-pro.zhihuishu.com/learnPage/',
    },
    'chaoxing': {
        'name': '超星学习通',
        'login': 'https://passport2.chaoxing.com/login',
        'target': 'https://mooc1.chaoxing.com/mycourse/studentstudy',
    },
}


def main():
    key = sys.argv[1].strip().lower() if len(sys.argv) > 1 else ''
    if key not in SITES:
        print('用法: python tools\\first_login.py <zhihuishu|chaoxing>')
        return 1
    info = SITES[key]

    from selenium import webdriver
    from selenium.webdriver.edge.options import Options as EdgeOptions

    print('=' * 60)
    print(f'{info["name"]} - 首次登录（只需这一次）')
    print('=' * 60)
    print('即将打开 Edge 浏览器窗口，请在窗口里扫码或输入账号密码登录。')
    print('程序不会读取、记录你的密码，只抓取登录后的 Cookie。')
    print()

    opt = EdgeOptions()
    opt.add_argument('--start-maximized')
    opt.page_load_strategy = 'eager'
    try:
        d = webdriver.Edge(options=opt)
    except Exception as e:
        print(f'启动 Edge 失败: {type(e).__name__}: {e}')
        return 1

    try:
        d.set_page_load_timeout(60)
        try:
            d.get(info['login'])
        except Exception:
            pass
        input('\n登录完成后，回到这里按回车继续... ')

        # 登录页在 login.zhihuishu.com，但学习页在 ai-smart-course-student-pro。
        # 先访问学习页域，让该域的 Cookie（如 acw_tc / 登录态）分发下来，再抓全量。
        print('正在访问学习页域以收集完整 Cookie...')
        try:
            d.get(info['target'])
        except Exception:
            pass
        import time
        time.sleep(3)

        cookies = d.get_cookies()
        if not cookies:
            print('没抓到任何 Cookie，可能没登录成功。重跑一次。')
            return 1

        # 拼成 "name=value; ..." 头串，同时保留带 domain 的完整结构
        header = '; '.join(f"{c['name']}={c['value']}" for c in cookies)
        full = json.dumps(cookies, ensure_ascii=False)

        cfg_path = refresh_cookie.config_path()
        refresh_cookie.set_config_value(cfg_path, 'site', key)
        refresh_cookie.write_cookie(header, cfg_path)
        refresh_cookie.set_config_value(cfg_path, 'cookies_full', full)
        print(f'\n已写入 config.ini：{len(cookies)} 条 Cookie（内容不回显）')

        # 验证：打开目标页看是否还跳登录
        target = info['target']
        print('正在验证登录态...')
        try:
            d.get(target)
        except Exception:
            pass
        import time
        time.sleep(4)
        url = d.current_url
        is_login = ('login' in url or 'passport' in url or '登录' in (d.title or ''))
        print(f'  当前 URL: {url[:90]}')
        print(f'  验证结果: {"仍跳登录页，Cookie 可能不全或未登录成功" if is_login else "已登录，Cookie 有效"}')

        if not is_login:
            print(f'\n下一步：把当前课程学习页的完整网址粘进 config.ini 的 course_url，')
            print(f'  然后运行 python main.py 即可全自动运行。')
    finally:
        input('\n按回车关闭浏览器... ')
        d.quit()
    return 0


if __name__ == '__main__':
    sys.exit(main())
