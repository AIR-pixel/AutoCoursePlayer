'''
浏览器驱动：探测 / 创建 / 初始化 / 探活 / 崩溃重建。
从原 main.py 160-454 行搬迁，逻辑未变。
'''
import os
from time import sleep

from selenium import webdriver

import refresh_cookie

BROWSER_PATHS = {
    'chrome': [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
    ],
    'edge': [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe'),
    ],
}
BROWSER_NAMES = {'chrome': 'Chrome', 'edge': 'Edge'}

PAGE_LOAD_TIMEOUT = 90


def detect_default_browser():
    """读 Windows 注册表里 http/https 的默认浏览器，返回 'chrome'/'edge'/None。

    Firefox 虽然能被识别（返回 'firefox'），但本项目的 git 环境下载 geckodriver
    常常失败，且它不在 BROWSER_PATHS/驱动链里，所以只把它当作"回退到 Edge"的信号。
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice')
        progid = winreg.QueryValueEx(key, 'ProgId')[0]
        winreg.CloseKey(key)
        p = (progid or '').lower()
        if 'chromehtml' in p:
            return 'chrome'
        if 'msedge' in p:
            return 'edge'
        if 'firefox' in p:
            return 'firefox'   # 会触发回退到 edge
    except Exception:
        pass
    return None

# "浏览器/标签页已经死了"的报错特征
DEAD_SESSION_MARKS = (
    'invalid session id', 'tab crashed', 'not connected to devtools',
    'browser has closed the connection', 'session deleted', 'disconnected',
    'chrome not reachable', 'target closed', 'no such window',
)


def is_browser_gone(exc: BaseException) -> bool:
    text = f'{type(exc).__name__}: {exc}'.lower()
    return any(mark in text for mark in DEAD_SESSION_MARKS)


class BrowserManager:
    """持有 driver，负责它的整个生命周期。"""

    def __init__(self, browser: str, headless: bool, implicitly_wait: int,
                 max_restarts: int = 6, log=print):
        self.browser_pref = browser
        self.headless = headless
        self.implicitly_wait = implicitly_wait
        self.max_restarts = max_restarts
        self.log = log
        self.name = self._detect()
        self.driver = None

    def _detect(self):
        if self.browser_pref in BROWSER_NAMES:
            return self.browser_pref
        # auto：优先系统默认浏览器（读注册表 UserChoice 的 ProgId）。
        # 但 Firefox 的 geckodriver 在部分网络下下载不到，跳过它回退 Edge。
        default = detect_default_browser()
        order = []
        if default and default in BROWSER_NAMES:
            order.append(default)
        order += ['edge', 'chrome']   # Windows 10/11 自带 Edge，优先于 Chrome
        for name in order:
            if any(os.path.exists(p) for p in BROWSER_PATHS[name]):
                return name
        return order[0]

    def create_driver(self):
        extra = [
            '--autoplay-policy=no-user-gesture-required',
            '--disable-blink-features=AutomationControlled',
            '--window-size=1920,1080',
            # 压制渲染进程崩溃（实测详见 docs/技术细节.md 2.5）
            '--disable-accelerated-video-decode',
            '--disable-accelerated-video-encode',
            '--disable-gpu',
            '--disable-gpu-compositing',
            '--disable-software-rasterizer',
            '--disable-dev-shm-usage',
            '--disable-features=CalculateNativeWinOcclusion',
        ]
        if self.headless:
            extra.append('--headless=new')
            extra.append('--mute-audio')
        if self.name == 'edge':
            from selenium.webdriver.edge.options import Options as EdgeOptions
            option = EdgeOptions()
        else:
            option = webdriver.ChromeOptions()
        option.page_load_strategy = 'eager'
        for arg in extra:
            option.add_argument(arg)
        d = webdriver.Edge(options=option) if self.name == 'edge' else webdriver.Chrome(options=option)
        return self.setup_driver(d)

    def setup_driver(self, d):
        if not self.headless:
            d.maximize_window()
        d.implicitly_wait(self.implicitly_wait)
        d.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        return d

    def start(self):
        self.driver = self.create_driver()
        return self.driver

    def alive(self) -> bool:
        try:
            self.driver.window_handles
            return True
        except Exception:
            return False

    def restart(self, reenter_fn) -> bool:
        """丢掉死会话，重建浏览器，再调 reenter_fn(driver) 回到课程页。"""
        self.log('浏览器已退出（标签页崩溃会带走整个进程），正在重建…')
        try:
            self.driver.quit()
        except Exception:
            pass
        sleep(3)
        try:
            self.driver = self.create_driver()
        except Exception as e:
            self.log(f'  重建浏览器失败: {type(e).__name__}: {str(e).splitlines()[0][:120]}')
            return False
        try:
            return reenter_fn(self.driver)
        except Exception as e:
            self.log(f'  重建后回课程页失败: {type(e).__name__}: {str(e).splitlines()[0][:120]}')
            return False

    def quit(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
