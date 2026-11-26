'''
首次登录 / 手动刷新 Cookie：直接打开课程页，登录后自动抓取完整 Cookie。

用法：
    python tools\first_login.py                    # 用 config 里已有的 course_url
    python tools\first_login.py <课程页完整网址>    # 指定课程页（推荐，藏得深的页直接贴进来）

说明：
  - 直接打开课程页，它会自动跳登录页；你登录后浏览器跳回课程页，
    程序**自动检测**并抓取 Cookie，不用回来按回车。
  - 程序不碰你的账号密码。
  - Cookie 过期后主程序也会自动调用这套逻辑，一般不用手动跑；
    手动跑用于：第一次配置、或想主动刷新凭据。
'''
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import refresh_cookie
from core import relogin

refresh_cookie.setup_output()
refresh_cookie.bypass_proxy_for_localhost()

SITE_KEYS = ('yuketang', 'chaoxing', 'zhihuishu')


def main():
    args = sys.argv[1:]
    course_url = None
    site_key = None
    for a in args:
        if a.strip().lower() in SITE_KEYS:
            site_key = a.strip().lower()
        elif a.startswith('http'):
            course_url = a

    cfg = refresh_cookie.read_config(refresh_cookie.config_path())
    get = lambda k: (cfg.get('Settings', k) or '').strip()

    if not course_url:
        course_url = get('course_url')
    if not course_url.startswith('http'):
        print('用法: python tools\\first_login.py [课程页完整网址] [站点]')
        print('  例: python tools\\first_login.py "https://ai-smart-course-student-pro.zhihuishu.com/learnPage/.../..." zhihuishu')
        print('\n当前 config.ini 里没有可用的 course_url，请把课程页网址作为参数传入。')
        return 1
    if not site_key:
        site_key = get('site') or 'yuketang'

    print(f'课程页: {course_url[:90]}')
    ok = relogin.interactive_login(course_url, site_key, log=print)
    if ok:
        print('\n完成。现在可以运行 python main.py 全自动刷课了。')
        return 0
    print('\n未完成登录，可重新运行本命令。')
    return 1


if __name__ == '__main__':
    sys.exit(main())
