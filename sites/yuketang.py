'''
长江雨课堂适配器（changjiang.yuketang.cn / www.yuketang.cn）。

本文件的所有 JS / 选择器 / 接口都从原 main.py、firstrun.py 原样搬迁，
行为与旧的独立脚本完全一致。改动只在"如何被内核调用"，不在判定逻辑本身。
实测记录见 docs/技术细节.md。
'''
from time import sleep

from .base import SiteAdapter
import firstrun  # 复用它的 _open / UA（纯 HTTP 工具，和站点无关的部分）


class YuketangAdapter(SiteAdapter):
    key = 'yuketang'
    name = '长江雨课堂'
    hosts = ('www.yuketang.cn', 'changjiang.yuketang.cn')
    cookie_label = 'cookie'
    course_url_hint = '浏览器进长江雨课堂 → 打开那门课 → 点「学习内容」→ 复制地址栏'

    # 两套前端：新版(COMMONUI) study-unit / span.leaf-flag；旧版 leaf-detail / icon--shipin
    COMMONUI_HOSTS = ('www.yuketang.cn', 'changjiang.yuketang.cn')
    LOGIN_URL_MARKS = ('pro/portal/home', 'pro/portal', '/login', 'portal/login')

    def __init__(self):
        self.ui_mode = 'auto'   # 由内核从 config 注入
        self.is_commonui = None
        self.implicitly_wait = 10

    # ---- 登录凭据 ----
    def fetch_courses(self, cookie_value: str, host: str):
        return firstrun.fetch_courses_yuketang(cookie_value, host)

    def course_url_of(self, host: str, course_id) -> str:
        return f'{host.rstrip("/")}/v2/web/studentLog/{course_id}'

    # ---- 页面交互 ----
    def is_login_page(self, d) -> bool:
        if any(mark in d.current_url for mark in self.LOGIN_URL_MARKS):
            return True
        if '登录' in (d.title or ''):
            return True
        d.implicitly_wait(0.1)
        try:
            logged_out = bool(d.find_element('class name', 'login-btn'))
        except Exception:
            logged_out = False
        finally:
            d.implicitly_wait(self.implicitly_wait)
        return logged_out

    def decide_ui(self, course_url: str):
        """根据 ui 配置和域名定 UI 版本。返回 True/False/None(待自动探测)。"""
        home = 'https://' + course_url.split('//', 1)[-1].split('/')[0] + '/'
        if self.ui_mode == 'common':
            self.is_commonui = True
        elif self.ui_mode == 'legacy':
            self.is_commonui = False
        elif any(h in home for h in self.COMMONUI_HOSTS):
            self.is_commonui = True
        else:
            self.is_commonui = None
        return self.is_commonui

    def ui_label(self):
        return {True: '新版(common)', False: '旧版(legacy)', None: '待自动探测'}[self.is_commonui]

    def prepare_course_page(self, d, course_url: str):
        """确保小节列表渲染出来。含 UI 自动探测 + 空骨架重载。
        返回小节元素列表（内核 finish1video 直接用）。"""
        from selenium.webdriver.common.by import By
        self.decide_ui(course_url)
        units = self._load_classes(d, course_url)
        return units

    def _click_report_tab(self, d):
        from selenium.webdriver.common.by import By
        try:
            d.execute_script('arguments[0].click()',
                             d.find_element(By.ID, 'tab-student_school_report'))
            return True
        except Exception:
            return False

    def _load_classes(self, d, course_url):
        from selenium.webdriver.common.by import By
        if self.is_commonui is None:
            self._click_report_tab(d)
            sleep(2)
            d.implicitly_wait(0.1)
            self.is_commonui = len(d.find_elements(By.CLASS_NAME, 'study-unit')) > 0
            d.implicitly_wait(self.implicitly_wait)
            print(f'  UI 版本自动判定: {"新版(common)" if self.is_commonui else "旧版(legacy)"}')
            if self.is_commonui:
                return self._load_classes(d, course_url)
            return d.find_elements(By.CLASS_NAME, 'leaf-detail')

        if self.is_commonui:
            units = []
            for attempt in (1, 2, 3):
                self._click_report_tab(d)
                sleep(2)
                units = d.find_elements(By.CLASS_NAME, 'study-unit')
                if not units or d.execute_script(self.UNITS_RENDERED_JS):
                    return units
                print(f'提示: 小节列表出来了但标题还是空的（第 {attempt} 次），重新加载课程页')
                d.get(course_url)
                sleep(4)
            return units
        return d.find_elements(By.CLASS_NAME, 'leaf-detail')

    UNITS_RENDERED_JS = '''
    var us = document.querySelectorAll('.study-unit');
    for (var i = 0; i < us.length && i < 5; i++) {
        var nt = us[i].querySelector('span.name-text');
        if (nt && (nt.textContent || '').trim()) { return true; }
    }
    return false;
    '''

    def units_rendered_js(self):
        return self.UNITS_RENDERED_JS

    # scan_js：mode 由内核按 is_commonui 传 'common'/'legacy'
    SCAN_TARGET_JS = '''
    var mode = arguments[0], played = arguments[1];
    var common = (mode === 'common');
    var units = document.querySelectorAll(common ? '.study-unit' : '.leaf-detail');
    var st = {total: units.length, locked: 0, notVideo: 0, expired: 0, done: 0,
              played: 0, blankTitle: 0, pending: 0};
    var picked = null, pickedTitle = '';
    for (var i = 0; i < units.length; i++) {
        var u = units[i];
        var txt = u.textContent || '';
        if (u.querySelector('i.icon--suo')) { st.locked++; continue; }
        var isVideo;
        if (common) {
            var flag = u.querySelector('span.leaf-flag');
            isVideo = !!(flag && flag.textContent.trim().indexOf('视频') >= 0);
        } else {
            var firstI = u.querySelector('i');
            isVideo = !!(firstI && (firstI.getAttribute('class') || '').indexOf('icon--shipin') >= 0);
        }
        if (!isVideo) { st.notVideo++; continue; }
        if (txt.indexOf('截止') >= 0) { st.expired++; continue; }
        var done = txt.indexOf('已完成') >= 0;
        if (!done) {
            var ct = u.querySelector('.complete-td');
            if (ct) {
                var m = /(\\d+(?:\\.\\d+)?)\\s*%/.exec(ct.textContent || '');
                if (m && parseFloat(m[1]) >= 99.9) { done = true; }
            }
        }
        if (done) { st.done++; continue; }
        var nt = u.querySelector('span.name-text');
        var title = nt ? (nt.textContent || '').trim()
                       : txt.replace(/\\s+/g, ' ').trim().slice(0, 60);
        if (!title) { st.blankTitle++; continue; }
        if (played.indexOf(title) >= 0) { st.played++; continue; }
        if (picked) { st.pending++; continue; }
        picked = u;
        pickedTitle = title;
    }
    return [picked, pickedTitle, st];
    '''

    def scan_js(self):
        return self.SCAN_TARGET_JS

    def scan_mode(self):
        return 'common' if self.is_commonui else 'legacy'

    # 截获 window.open，避免开新标签页导致 close() 卡死
    CAPTURE_VIDEO_URL_JS = '''
    (function () {
        if (!window.__ytOpenPatched) {
            window.__ytOpenPatched = true;
            window.__ytVideoUrl = null;
            window.__ytOpenCalls = 0;
            window.open = function (u, n, f) {
                window.__ytOpenCalls++;
                if (typeof u === 'string' && u) { window.__ytVideoUrl = u; }
                return { closed: false, focus: function () {}, blur: function () {},
                         close: function () {}, document: { write: function () {} },
                         location: { href: u } };
            };
        }
        window.__ytVideoUrl = null;
        var n = 0;
        document.querySelectorAll('a[target="_blank"]').forEach(function (a) {
            a.setAttribute('target', '_self');
            n++;
        });
        return n;
    })();
    '''

    def capture_open_js(self):
        return self.CAPTURE_VIDEO_URL_JS

    def captured_video_url_js(self):
        return 'return window.__ytVideoUrl;'

    # 点开小节元素。新版点 span.name-text 更可靠，旧版直接 click。
    def open_lesson(self, d, element):
        from selenium.webdriver.common.by import By
        if self.is_commonui:
            try:
                target = element.find_element(By.CSS_SELECTOR, 'span.name-text')
            except Exception:
                target = element.find_element(By.TAG_NAME, 'span')
            try:
                target.click()
            except Exception:
                d.execute_script('arguments[0].click()', target)
        else:
            element.click()
