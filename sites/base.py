'''
站点适配器基类。

一个站点要接入本程序，只需继承 SiteAdapter 并实现下面这些方法。
内核（core/）只认这个接口，不认识任何具体站点。

接口分四组：
  1. 身份与域名   key / name / hosts / home_url / course_url_hint
  2. 登录凭据     cookie_names / fetch_courses / course_url_of / get_credential
  3. 页面交互     inject_cookie / is_login_page / prepare_course_page / scan_js / capture_open_js
  4. 视频控制     open_lesson / before_play / video_ready / after_finish

方法签名里的 `d` 一律是 selenium driver。为了让内核保持站点无关，
适配器内部需要的 JS 常量、选择器、UI 版本状态都放在各自模块里。
'''
from abc import ABC, abstractmethod


class SiteAdapter(ABC):
    # ---- 1. 身份与域名 ----
    key: str = ''            # config.ini 里的 site 值，如 yuketang / chaoxing
    name: str = ''           # 显示名，如 "长江雨课堂"
    hosts: tuple = ()        # 该站点可能的域名，用于校验 course_url
    course_url_hint: str = ''  # 向导里"手动填地址"的提示文案

    # 网站根地址（带 https:// 和结尾 /）。多数站点从 course_url 取 host 即可，
    # 少数站点 home 与 course 不同域时 override。
    def home_url(self, course_url: str) -> str:
        return 'https://' + course_url.split('//', 1)[-1].split('/')[0] + '/'

    def match_host(self, course_url: str) -> bool:
        host = course_url.split('//', 1)[-1].split('/')[0]
        return any(h == host or host.endswith('.' + h) for h in self.hosts)

    # ---- 2. 登录凭据 ----
    # cookie 注入方式：返回 {name: value}。雨课堂是 {'sessionid': x}，
    # 学习通可能是多个 cookie，智慧树是 arn + 其他。
    def cookie_dict(self, cookie_value: str) -> dict:
        return {'sessionid': cookie_value}

    # 凭据名（写进 config 的字段名，一般就叫 cookie）
    cookie_label: str = 'cookie'

    # 列课程：纯 HTTP，返回 [{'id','title','class_name','teacher','school'}]。
    # cookie_value 是 config 里存的凭据。抛异常 = 凭据失效。
    @abstractmethod
    def fetch_courses(self, cookie_value: str, host: str):
        raise NotImplementedError

    # 由课程 id 拼出可播放的课程页地址
    @abstractmethod
    def course_url_of(self, host: str, course_id) -> str:
        raise NotImplementedError

    # 取凭据：默认走扫码。子类可 override（如读 Firefox cookie 库）。
    def get_credential(self):
        from refresh_cookie import get_sessionid
        return get_sessionid()

    # ---- 3. 页面交互 ----
    # 进课程页前注入 cookie；默认 delete_all + 逐个 add
    def inject_cookie(self, d, cookie_value: str):
        d.delete_all_cookies()
        for name, value in self.cookie_dict(cookie_value).items():
            d.add_cookie({'name': name, 'value': value, 'path': '/'})

    # 从 config 读"完整 Cookie"（first_login.py 抓的带 domain/path 结构）。
    # 返回 list[dict] 或 None。站点若支持，override 本方法实现精确注入。
    def load_full_cookies(self):
        import json
        import refresh_cookie
        try:
            cfg = refresh_cookie.read_config(refresh_cookie.config_path())
            raw = (cfg.get('Settings', 'cookies_full') or '').strip()
            return json.loads(raw) if raw else None
        except Exception:
            return None

    # 是否停在登录页
    @abstractmethod
    def is_login_page(self, d) -> bool:
        raise NotImplementedError

    # 课程页打开后、扫小节前的准备动作（如雨课堂点"学习报告"标签）。
    # 返回 None；子类自己处理等待。
    def prepare_course_page(self, d, course_url: str):
        pass

    # 一次 JS 扫描，挑出"下一个该播的小节"，返回 [元素, 标题, 统计dict]。
    # 统计 dict 至少含 total / done / locked / notVideo / expired / played / pending。
    @abstractmethod
    def scan_js(self) -> str:
        raise NotImplementedError

    # 小节列表渲染完成的判据 JS（返回 boolean），防止读到空骨架
    def units_rendered_js(self) -> str:
        return 'return document.querySelectorAll("video").length > 0 || document.body.innerText.length > 500;'

    # 点标题前注入，用于截获视频页 URL / 改写 target。返回被改写的链接数。
    def capture_open_js(self) -> str:
        return 'return 0;'

    # 从页面里取出截获到的视频 URL（配合 capture_open_js）
    def captured_video_url_js(self) -> str:
        return 'return null;'

    # 点开小节之后、等 <video> 之前，站点可再做一步（如智慧树新形态课程
    # 要点开小节里的 mp4 资源才加载播放器）。返回 True 表示做了额外点击。
    def after_open_lesson(self, d, title: str) -> bool:
        return False

    # 点开一个视频后，内核等待 <video> 出现时顺便要处理的站点特有弹窗
    # （智慧树的承诺书、学习通的任务确认等）。等待期间会被反复调用。
    def handle_popups(self, d) -> bool:
        """返回 True 表示刚才确实点了什么（内核可据此多等一拍）。"""
        return False

    # ---- 4. 视频控制 ----
    # 内核装播放锁后调用；子类可在此加站点特有的续播/静音/弹题关闭逻辑。
    # 传 speed 让子类知道目标倍速。
    def extra_player_js(self, speed: float) -> str:
        return ''

    # 播放结束的额外判据 JS（返回 true = 已结束），叠加在内核的 ended/回退/卡死之上。
    # 留空表示不用。
    def finished_extra_js(self) -> str:
        return ''

    # 播放完成、离开视频页前的清理（清掉子类自己注入的定时器等）
    def cleanup_js(self) -> str:
        return ''
