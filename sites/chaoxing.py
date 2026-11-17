'''
超星学习通 / 泛雅 适配器。

域名来源：ocsjs/ocsjs cx.ts 的 domains（chaoxing.com / 各学校 edu.cn 泛雅站点）。
选择器来源：ocsjs cx.ts + 常见公开脚本（.clearfix.video / 任务点 / videojs）。

超星的特点（和雨课堂/智慧树都不同，是本适配器的难点）：
  1. 视频播放器在**跨域 iframe** 里（mooc1.xxx/mycourse/...）。
     内核的 document.querySelector('video') 默认只看顶层，够不到 iframe 里的 video。
     → 本适配器在 extra_player_js 里把 iframe 内的 video 也纳入倍速/静音控制
       （同域时可直接操作；跨域时靠 handle_popups 提示用户手动，见 README）。
  2. "任务点(job)"概念：章节列表里每个任务点可能是视频/文档/测验，
     完成标记是 isPassed / 已完成 图标。
  3. 高倍速/夜间大量运行可能导致学习记录清空回退（ocsjs 明确警告），
     所以本适配器把 speed 夹到 2x 并提示风险。

注意：超星各学校泛雅站点 DOM 差异较大，本适配器是通用第一版，
具体学校若选择器不匹配，需用 tools/probe_site.py dump DOM 后微调。
'''
from .base import SiteAdapter
import firstrun

CX_HOSTS = (
    'chaoxing.com', 'xueyinonline.com', 'xuexi365.com',
    'sslibrary.com',
)


class ChaoxingAdapter(SiteAdapter):
    key = 'chaoxing'
    name = '超星学习通 / 泛雅'
    hosts = CX_HOSTS
    cookie_label = 'cookie'
    course_url_hint = '浏览器进学习通 → 打开课程 → 进入章节学习页 → 复制地址栏'
    MAX_SPEED = 2.0  # 高倍速有清空学习记录风险

    def __init__(self):
        self.warned_iframe = False

    # 学校泛雅站点域名五花八门（xxx.edu.cn / xxx.cn），放宽匹配
    def match_host(self, course_url: str) -> bool:
        host = course_url.split('//', 1)[-1].split('/')[0]
        if any(host == h or host.endswith('.' + h) for h in CX_HOSTS):
            return True
        # 学习通课程页 URL 里通常带 /mycourse/ 或 /studentstudy/ 或 mooc1.
        return any(m in course_url for m in ('/mycourse/', '/studentstudy/', 'mooc1.'))

    # ---- 凭据 ----
    def cookie_dict(self, cookie_value: str) -> dict:
        v = (cookie_value or '').strip()
        if ';' in v or '=' in v:
            out = {}
            for part in v.split(';'):
                if '=' in part:
                    k, _, val = part.partition('=')
                    out[k.strip()] = val.strip()
            return out or {'_d': v}
        return {'_d': v}

    def inject_cookie(self, d, cookie_value: str):
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
            d.add_cookie({'name': name, 'value': value, 'path': '/'})

    def fetch_courses(self, cookie_value: str, host: str):
        return firstrun.fetch_courses_chaoxing(cookie_value, host)

    def course_url_of(self, host: str, course_id) -> str:
        if isinstance(course_id, str) and course_id.startswith('http'):
            return course_id
        # 超星课程学习页：/mycourse/studentstudy?...courseId=xxx
        return f'{host.rstrip("/")}/mycourse/studentstudy?courseId={course_id}'

    # ---- 页面交互 ----
    def is_login_page(self, d) -> bool:
        url = d.current_url or ''
        if any(m in url for m in ('/login', 'passport', 'sso', 'cas')):
            return True
        return '登录' in (d.title or '') and '学习通' not in (d.title or '')

    def prepare_course_page(self, d, course_url: str):
        pass

    UNITS_RENDERED_JS = '''
    var us = document.querySelectorAll('.clearfix.video, .job, li[data-id], .task-item');
    return us.length > 0;
    '''
    def units_rendered_js(self):
        return self.UNITS_RENDERED_JS

    # 扫下一个未完成任务点。超星任务点选择器：.clearfix.video / .job / li[data-id]，
    # 完成标记：.isPassed / .complete / 文本含"已完成"。
    SCAN_TARGET_JS = r'''
    var played = arguments[0] || [];
    var sels = ['.clearfix.video', '.job', 'li[data-id]', '.task-item', '.chapter_unit'];
    var units = [];
    for (var s = 0; s < sels.length && units.length === 0; s++) {
        units = Array.prototype.slice.call(document.querySelectorAll(sels[s]));
    }
    var st = {total: units.length, locked: 0, notVideo: 0, expired: 0, done: 0,
              played: 0, blankTitle: 0, pending: 0};
    var picked = null, pickedTitle = '';
    for (var i = 0; i < units.length; i++) {
        var u = units[i];
        var txt = u.textContent || '';
        var cls = u.className || '';
        if (u.querySelector('.isPassed') || u.querySelector('.complete') ||
            cls.indexOf('isPassed') >= 0 || txt.indexOf('已完成') >= 0) {
            st.done++; continue;
        }
        if (u.querySelector('.lock') || cls.indexOf('lock') >= 0) { st.locked++; continue; }
        var title = '';
        var t = u.querySelector('.title, .name, .task-name, p, span');
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
        return ''

    def open_lesson(self, d, element):
        d.execute_script('arguments[0].scrollIntoView(false);', element)
        try:
            element.click()
        except Exception:
            d.execute_script('arguments[0].click()', element)

    # 超星视频在 iframe 里：内核装播放锁（作用于顶层 document）可能够不到真实 video。
    # 这里额外装一段定时器，遍历所有同源 iframe 也把倍速/静音压住。
    def extra_player_js(self, speed: float) -> str:
        return '''
        (function () {
            if (window.__cxFrameLock) { window.__cxFrameSpeed = SPEED; return; }
            window.__cxFrameLock = true;
            window.__cxFrameSpeed = SPEED;
            window.__cxFrameTimer = setInterval(function () {
                var frames = document.querySelectorAll('iframe');
                for (var i = 0; i < frames.length; i++) {
                    try {
                        var fd = frames[i].contentDocument;
                        if (!fd) { continue; }
                        var v = fd.querySelector('video');
                        if (!v) { continue; }
                        if (v.playbackRate < window.__cxFrameSpeed) { v.playbackRate = window.__cxFrameSpeed; }
                        if (!v.muted) { v.muted = true; }
                        if (v.paused) { try { v.play(); } catch (e) {} }
                    } catch (e) {}
                }
            }, 1000);
        })();
        '''.replace('SPEED', str(speed))

    def handle_popups(self, d) -> bool:
        # 超星偶发弹验证码 / 确认框，尽量关掉纯展示型弹窗；验证码需要人工。
        js = '''
        var n = 0;
        document.querySelectorAll('.el-dialog__wrapper, .modal, .dialog').forEach(function (e) {
            var c = e.querySelector('.close, .el-dialog__headerbtn, [class*=close]');
            if (c) { try { c.click(); n++; } catch (err) {} }
        });
        return n;
        '''
        try:
            return bool(d.execute_script(js))
        except Exception:
            return False

    def finished_extra_js(self) -> str:
        return '''
        var v = document.querySelector('video, iframe video');
        if (!v) { return false; }
        return !!(v.ended || (v.duration && v.currentTime >= v.duration - 0.5));
        '''

    def cleanup_js(self) -> str:
        return 'try { clearInterval(window.__cxFrameTimer); } catch (e) {}'
