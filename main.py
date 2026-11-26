'''
网课自动播放器 - 多站点调度入口。

职责很薄：读配置 → 选站点适配器 → 建浏览器 → 交给通用引擎。
所有站点专属逻辑在 sites/，所有通用逻辑在 core/。

支持站点见 sites/__init__.py。
'''
from time import sleep
import sys

import refresh_cookie

refresh_cookie.setup_output()

import sites
from core.browser import BrowserManager, BROWSER_NAMES
from core.engine import Engine, ts


def load_settings(path):
    cfg = refresh_cookie.read_config(path)
    get = lambda k, d='': (cfg.get('Settings', k, fallback=d) or '').strip()

    def text(k, d=''):
        try:
            return (cfg.get('Settings', k) or '').strip()
        except Exception:
            return d

    return {
        'site': get('site', 'yuketang'),
        'headless': cfg.getboolean('Settings', 'headless', fallback=True),
        'browser': get('browser', 'auto').lower(),
        'ui': get('ui', 'auto').lower(),
        'course_url': text('course_url'),
        'cookie': text('cookie'),
        'speed': cfg.getfloat('Settings', 'speed', fallback=2.0),
        'implicitly_wait': cfg.getint('Settings', 'implicitly_wait', fallback=10),
        '_cfg': cfg,
    }


def needs_setup(settings) -> bool:
    return not (settings['course_url'].startswith('https://') and settings['cookie'])


def main():
    refresh_cookie.bypass_proxy_for_localhost()
    path = refresh_cookie.config_path()

    settings = load_settings(path)
    # --site：强制重新选站点（换平台用）。等价于双击「选择站点.bat」
    force_site = '--site' in sys.argv
    if force_site or needs_setup(settings):
        if not firstrun_ensure_ready(path, force_reselect=force_site):
            print('\n配置未完成，退出。')
            refresh_cookie.pause_exit(1)
            return 1
        settings = load_settings(path)

    try:
        adapter = sites.get_adapter(settings['site'])
    except ValueError as e:
        print(f'\n配置错误: {e}')
        refresh_cookie.pause_exit(1)
        return 1

    # UI 模式 / 等待时间等适配器的额外配置
    if hasattr(adapter, 'ui_mode'):
        adapter.ui_mode = settings['ui']
    if hasattr(adapter, 'implicitly_wait'):
        adapter.implicitly_wait = settings['implicitly_wait']

    speed = min(4.0, max(0.5, settings['speed']))
    # 各站点倍速上限（智慧树 1.5 / 超星 2），超了会明确提示并夹住
    cap = getattr(adapter, 'MAX_SPEED', None)
    if cap and speed > cap:
        print(f'提示: {adapter.name} 建议倍速不超过 {cap}x，已把 {speed}x 调整为 {cap}x')
        speed = cap

    print('\n配置信息:')
    print(f'  站点: {adapter.name}')
    print(f'  无窗口模式: {settings["headless"]}')
    print(f'  播放倍速: {speed}x')
    print(f'  课程URL: {settings["course_url"][:60]}')
    print('  Cookie已配置: ✓')
    print('=' * 50 + '\n')

    bm = BrowserManager(
        browser=settings['browser'],
        headless=settings['headless'],
        implicitly_wait=settings['implicitly_wait'],
    )
    print(f'{ts()} 启动浏览器（{BROWSER_NAMES[bm.name]}，{"无窗口" if bm.headless else "有窗口"}）...')
    try:
        bm.start()
    except Exception as e:
        print(f'启动浏览器失败: {type(e).__name__}: {e}')
        print('  本机需要安装 Edge 或 Chrome。')
        refresh_cookie.pause_exit(1)
        return 1
    print(f'{ts()} 浏览器就绪')

    settings['speed'] = speed
    engine = Engine(settings, adapter, bm)
    try:
        code = engine.run()
    except KeyboardInterrupt:
        print('\n已手动中断。')
        bm.quit()
        code = 0
    sleep(2)
    refresh_cookie.pause_exit(code)
    return code


def firstrun_ensure_ready(path, force_reselect=False):
    import firstrun
    return firstrun.ensure_ready(path, force_reselect=force_reselect)


if __name__ == '__main__':
    sys.exit(main())
