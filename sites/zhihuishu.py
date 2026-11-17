'''
智慧树 / 知到 适配器。

选择器来源：ocsjs/ocsjs (MIT, 4766★) packages/scripts/src/projects/zhs.ts
及 utils/zhs.configs.ts（2026-11 核对，仍活跃维护）。

智慧树有多种学习页，ocsjs 用不同处理器区分。本适配器覆盖主流的几类：
  - 共享课 studyvideoh5.zhihuishu.com / studyplush5 / studywisdomh5
  - 新形态课程 smartcoursestudent.zhihuishu.com
    / ai-smart-course-student-pro.zhihuishu.com   ← 用户提供的网址属于这类
  - 智慧课程/AI 教学空间 fusioncourseh5 / wisdom-mooc

重要：智慧树官方倍速上限 1.5x，超过有封号风险（ocsjs 明确警告）。
本适配器会把内核传入的 speed 夹到 1.5。

智慧树是 SPA 且一页内切小节（不像雨课堂开新标签页），所以：
  - capture_open_js / captured_video_url_js 用默认空实现（无需截获 window.open）
  - open_lesson 直接点击小节元素，在当前页切换
  - finished_extra_js 提供"进度 100%"判据
  - handle_popups 处理弹窗测验 / 承诺书 / 习惯分提示
'''
from .base import SiteAdapter
import firstrun

# 智慧树所有已知学习页域名（来自 ocsjs zhs.configs.ts 的 stopTime/switchMode 说明）
ZHS_HOSTS = (
    'zhihuishu.com',
    'studyvideoh5.zhihuishu.com',
    'studyplush5.zhihuishu.com',
    'studywisdomh5.zhihuishu.com',
    'smartcoursestudent.zhihuishu.com',
    'ai-smart-course-student-pro.zhihuishu.com',
    'fusioncourseh5.zhihuishu.com',
    'wisdom-mooc.zhihuishu.com',
)


class ZhihuishuAdapter(SiteAdapter):
    key = 'zhihuishu'
    name = '智慧树 / 知到'
    hosts = ZHS_HOSTS
    cookie_label = 'cookie'
    course_url_hint = '浏览器进智慧树 → 打开课程学习页 → 复制地址栏（形如 .../learnPage/...）'
    MAX_SPEED = 1.5  # 官方上限，超过有封号风险

    def __init__(self):
        self.popup_clicked = False

    # ---- 身份 ----
    def match_host(self, course_url: str) -> bool:
        host = course_url.split('//', 1)[-1].split('/')[0]
        return host.endswith('zhihuishu.com')

    # ---- 凭据 ----
    def cookie_dict(self, cookie_value: str) -> dict:
        v = (cookie_value or '').strip()
        if '=' in v and not v.startswith('{'):
            name, _, val = v.partition('=')
            return {name.strip(): val.strip()}
        return {'arn': v}

    def inject_cookie(self, d, cookie_value: str):
        """优先用 first_login.py 抓的完整 Cookie（带 domain/path）逐条注入；
        没有则用 cookie_dict 的简化方式。"""
        full = self.load_full_cookies()
        if full:
            injected = 0
            for c in full:
                ck = {'name': c['name'], 'value': c['value']}
                if c.get('domain'):
                    ck['domain'] = c['domain']
                if c.get('path'):
                    ck['path'] = c['path']
                try:
                    d.add_cookie(ck)
                    injected += 1
                except Exception:
                    pass
            if injected:
                print(f'  注入完整 Cookie {injected} 条')
                return
        d.delete_all_cookies()
        for name, value in self.cookie_dict(cookie_value).items():
            d.add_cookie({'name': name, 'value': value, 'path': '/', 'domain': '.zhihuishu.com'})

    def fetch_courses(self, cookie_value: str, host: str):
        return firstrun.fetch_courses_zhihuishu(cookie_value, host)

    def course_url_of(self, host: str, course_id) -> str:
        # 智慧树课程页形态多，列课时直接返回接口给的 URL；这里兜底
        if isinstance(course_id, str) and course_id.startswith('http'):
            return course_id
        return f'{host.rstrip("/")}/learnPage/{course_id}'

    # ---- 页面交互 ----
    def is_login_page(self, d) -> bool:
        url = d.current_url or ''
        title = d.title or ''
        if any(m in url for m in ('/login', 'passport', 'sso')):
            return True
        if '登录' in title and '智慧树' not in title:
            return True
        # 学习页正常渲染时有 video 或章节列表；都没有且 URL 不在 learnPage 上，多半没登录
        return ('learnPage' not in url and 'study' not in url
                and 'h5' not in url and 'fusioncourse' not in url)

    def prepare_course_page(self, d, course_url: str):
        # 智慧树是 SPA，小节列表随页面渲染出来。等叶子小节出现，
        # 返回元素列表给内核判空（内核靠返回值判断"有没有小节"，不能返回 None）。
        import time
        from selenium.webdriver.common.by import By
        units = []
        for _ in range(8):
            units = d.find_elements(By.CSS_SELECTOR, '.section-item-collapse-info')
            if units:
                break
            time.sleep(1)
        # 其它智慧树版本的小节容器兜底
        if not units:
            for sel in ('.clearfix.video', '.child-main', '.chapter-content-second', '.source-icon'):
                units = d.find_elements(By.CSS_SELECTOR, sel)
                if units:
                    break
        return units

    UNITS_RENDERED_JS = '''
    var v = document.querySelectorAll(
        '.section-item-collapse-info, .clearfix.video, .resources-item, ' +
        '.child-main, .chapter-content-second, .source-icon');
    return v.length > 0;
    '''

    def units_rendered_js(self):
        return self.UNITS_RENDERED_JS

    # 扫下一个未完成小节。
    # 新形态课程(2026 实测)：三级折叠，叶子是 .section-item-collapse-info，
    #   完成 = 有 .checked-img 勾图标，或 .progress-text 显示"必学 X/Y" 且 X>=Y
    # 其余选择器保留给共享课/新形态旧版/新共享课/新智慧/Hike 各版。
    # 返回 [元素, 标题, 统计]
    SCAN_TARGET_JS = r'''
    var played = arguments[0] || [];
    var selectors = [
        '.section-item-collapse-info',              // 新形态课程 2026 版（实测）
        '.clearfix.video',                          // 共享课 / 新形态旧版
        '.resources-item',                          // resource-box 模式
        '.child-main',                              // 新共享课
        '.chapter-content .chapter-content-second', // 新智慧
        '.source-icon'                              // 教学空间 Hike
    ];
    var units = [];
    for (var s = 0; s < selectors.length && units.length === 0; s++) {
        units = Array.prototype.slice.call(document.querySelectorAll(selectors[s]));
    }
    if (units.length && units[0].matches && units[0].matches('.source-icon')) {
        units = units.map(function (el) { return el.parentElement.parentElement; });
    }
    var st = {total: units.length, locked: 0, notVideo: 0, expired: 0, done: 0,
              played: 0, blankTitle: 0, pending: 0};
    var picked = null, pickedTitle = '';
    for (var i = 0; i < units.length; i++) {
        var u = units[i];
        var txt = u.textContent || '';
        // ---- 完成判定 ----
        var done = false;
        // 新形态 2026：勾选图标
        if (u.querySelector('.checked-img')) { done = true; }
        // 新形态 2026：progress-text "必学 X/Y"
        var bxt = (u.querySelector('.progress-text') || {}).textContent || '';
        var bm = bxt.replace(/\s/g, '').match(/(\d+)\/(\d+)/);
        if (bm && parseInt(bm[1]) >= parseInt(bm[2])) { done = true; }
        // 其它版本
        if (u.querySelector('.time_icofinish') || u.querySelector('.finish-icon') ||
            u.querySelector('.isFinish') || u.querySelector('i.select')) { done = true; }
        var ptxt = (u.querySelector('.progress-num') || {}).textContent || '';
        if (ptxt.replace(/\s/g, '') === '100%') { done = true; }
        if (done) { st.done++; continue; }

        var title = '';
        var t = u.querySelector('.section-item-collapse-title, .title-text, .catalogue_title, .file-name, .resource-text, .name');
        if (t) { title = (t.textContent || '').trim(); }
        if (!title) { title = txt.replace(/\s+/g, ' ').trim().slice(0, 60); }
        if (!title) { st.blankTitle++; continue; }
        if (played.indexOf(title) >= 0) { st.played++; continue; }
        if (picked) { st.pending++; continue; }
        picked = u; pickedTitle = title;
    }
    return [picked, pickedTitle, st];
    '''

    def scan_js(self):
        return self.SCAN_TARGET_JS

    def scan_mode(self):
        return ''  # 智慧树 scan_js 不需要 mode 参数；内核处理

    # 当前页点小节切换（智慧树不开新标签页）
    def open_lesson(self, d, element):
        d.execute_script('arguments[0].scrollIntoView(false);', element)
        # 新形态 2026：叶子是 .section-item-collapse-info，点里面的 title 才进入资源页
        target = element
        try:
            t = element.querySelector('.section-item-collapse-title')
            if t:
                target = t
        except Exception:
            pass
        try:
            d.execute_script('arguments[0].click()', target)
        except Exception:
            try:
                target.click()
            except Exception:
                d.execute_script('arguments[0].click()', element)

    # 点开小节后，新形态课程页默认显示 PPT（.video-player-wrapper 是 display:none）。
    # 必须点小节里的 mp4 资源项（.video-info），video.js 才会挂载 <video>。
    # 优先点未完成的（无 .finished-icon）；全完成了就点第一个 mp4。
    def after_open_lesson(self, d, title: str) -> bool:
        import time
        # 等资源列表渲染
        for _ in range(6):
            n = d.execute_script(
                'return document.querySelectorAll(".video-info").length;') or 0
            if n:
                break
            time.sleep(1)
        js = r'''
        var items = document.querySelectorAll('.video-info');
        var first = null;
        for (var i = 0; i < items.length; i++) {
            var e = items[i];
            var t = (e.querySelector('.video-title') || {}).textContent || '';
            if (t.indexOf('.mp4') < 0 && t.indexOf('视频') < 0) { continue; }
            if (!first) { first = e; }
            if (!e.querySelector('.finished-icon')) {
                e.click();
                return 'unfinished:' + t.trim().slice(0, 30);
            }
        }
        if (first) {
            first.click();
            return 'first:' + ((first.querySelector('.video-title') || {}).textContent || '').trim().slice(0, 30);
        }
        return null;
        '''
        try:
            r = d.execute_script(js)
            time.sleep(2)
            if r:
                print(f'  打开视频资源: {r}')
                return True
        except Exception:
            pass
        return False

    # ---- 弹窗 / 承诺书 / 习惯分 ----
    POPUP_JS = r'''
    var clicked = 0;
    // 通知弹窗（各版类名）
    document.querySelectorAll('.el-dialog__wrapper, .el-overlay').forEach(function (e) {
        if (e.style.display !== 'none') { e.remove(); clicked++; }
    });
    // 学前必读 / 承诺书：找到含"同意/已知晓/开始学习"的按钮点掉
    var btnSel = 'button, .btn, .el-button, a';
    var agrees = ['同意', '已知晓', '我已阅读', '开始学习', '确认'];
    document.querySelectorAll(btnSel).forEach(function (b) {
        var t = (b.textContent || '').trim();
        for (var i = 0; i < agrees.length; i++) {
            if (t.indexOf(agrees[i]) >= 0) { try { b.click(); clicked++; } catch (e) {} break; }
        }
    });
    // 习惯分提示弹窗
    var habit = document.querySelector('.study-time-warn, .habit-dialog');
    if (habit) {
        var c = habit.querySelector('.close, .btn, button');
        if (c) { try { c.click(); clicked++; } catch (e) {} }
    }
    return clicked;
    '''

    def handle_popups(self, d) -> bool:
        try:
            n = d.execute_script(self.POPUP_JS) or 0
            if n:
                self.popup_clicked = True
            return bool(n)
        except Exception:
            return False

    # ---- 结束判据：进度 100% 也算完成 ----
    def finished_extra_js(self) -> str:
        return r'''
        var pn = document.querySelector('.progress-num');
        return !!(pn && (pn.textContent || '').replace(/\s/g,'') === '100%');
        '''

    def cleanup_js(self) -> str:
        return 'try { window.onbeforeunload = null; } catch (e) {}'
