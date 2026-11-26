'''
主引擎：把浏览器、播放内核、站点适配器串起来的调度循环。
从原 main.py 365-1015 行搬迁，所有"站点专属"调用都改成 site.xxx()。
行为判定口径与原脚本一致（见 docs/技术细节.md）。
'''
import os
from time import sleep, monotonic, strftime

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from .browser import BrowserManager, is_browser_gone, PAGE_LOAD_TIMEOUT
from . import player
import refresh_cookie

VIDEO_READY_TIMEOUT = 20


def ts():
    return strftime('%H:%M:%S')


class Engine:
    def __init__(self, cfg, site, browser_mgr: BrowserManager):
        self.cfg = cfg           # 已解析的配置 dict
        self.site = site
        self.bm = browser_mgr
        self.course_url = cfg['course_url']
        self.cookie = cfg['cookie']
        self.speed = cfg['speed']
        self.home_url = site.home_url(self.course_url)

        self.PLAYED_TITLES = set()
        self.SKIPPED_STALLED = []
        self.ABORTED_NO_CLASSES = False
        self.ABORTED_ERRORS = False
        self.ABORTED_BROWSER = False
        self.ABORTED_NO_PROGRESS = False
        self.LOCKED_VIDEOS = 0

    @property
    def d(self):
        return self.bm.driver

    def log(self, msg):
        print(msg)

    def _get(self, url):
        from selenium.common.exceptions import TimeoutException
        try:
            self.d.get(url)
        except TimeoutException:
            self.log(f'  提示: 打开页面超时（{PAGE_LOAD_TIMEOUT}s），继续尝试使用当前页面')

    def inject_cookie(self):
        self.site.inject_cookie(self.d, self.cookie)

    def goto_course_page(self, allow_qr=True) -> bool:
        self.log(f'{ts()} 打开课程页...')
        # 注入 Cookie 前必须先把浏览器落到目标域：selenium 的 add_cookie
        # 只允许给"当前域及其父域"设 cookie。智慧树/超星的 cookie 多在子域
        # （ai-smart-course-student-pro / mooc1），先访问 home 域会导致注入被拒。
        # 所以先打开课程页（未登录会跳登录页，无妨），在其域下注入，再重开课程页。
        self._get(self.course_url)
        self.inject_cookie()
        self._get(self.course_url)
        sleep(3)
        if not self.site.is_login_page(self.d):
            return True
        if not allow_qr:
            self.log('  重建后仍停在登录页 —— cookie 可能已失效')
            return False

        # Cookie 过期：自动弹可见浏览器走登录桥接，成功后用新 Cookie 重试。
        # 不再依赖老式 login-btn 扫码（智慧树/学习通都没这个按钮，老版在这里直接退出）。
        self.log('Cookie 已失效，需要重新登录。')
        from .relogin import interactive_login
        # 关掉无头浏览器，避免和登录窗口抢资源
        try:
            self.bm.quit()
        except Exception:
            pass
        if not interactive_login(self.course_url, self.cfg['site'], log=self.log):
            self.log('重新登录未完成，本次退出。下次运行会再试。')
            return False
        # 读回新 Cookie + 课程地址，重建浏览器重进课程页
        newcfg = refresh_cookie.read_config(refresh_cookie.config_path())
        g = lambda k: (newcfg.get('Settings', k) or '').strip()
        self.cookie = g('cookie')
        if g('course_url').startswith('http'):
            self.course_url = g('course_url')
        self.bm.start()
        self._get(self.course_url)
        self.inject_cookie()
        self._get(self.course_url)
        sleep(3)
        if self.site.is_login_page(self.d):
            self.log('重新登录后仍停在登录页，放弃本次。')
            return False
        self.log('重新登录成功，继续播放。')
        return True

    def dump_dom(self):
        path = os.path.join(refresh_cookie.app_dir(), '_debug_page_source.html')
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.d.page_source)
            counts = {}
            for el in self.d.find_elements(By.XPATH, '//*[@class]'):
                for c in (el.get_attribute('class') or '').split():
                    counts[c] = counts.get(c, 0) + 1
            top = sorted(counts.items(), key=lambda kv: -kv[1])[:15]
            self.log('  页面 class 采样(出现最多): ' + ', '.join(f'{k}x{v}' for k, v in top))
            self.log(f'  页面源码已保存: {path}')
        except Exception as e:
            self.log(f'  现场落盘失败: {e}')

    def scan_target(self):
        mode = getattr(self.site, 'scan_mode', lambda: '')()
        args = []
        if mode:  # 雨课堂需要 mode 参数；其他站点 scan_js 只用 played
            args.append(mode)
        args.append(list(self.PLAYED_TITLES))
        return self.d.execute_script(self.site.scan_js(), *args)

    def back_to_course_page(self):
        """确保回课程页、不留多余窗口（原 main.py 652-691）。"""
        for _ in range(3):
            handles = self.d.window_handles
            if len(handles) <= 1:
                break
            try:
                self.d.switch_to.window(handles[-1])
                self.d.execute_script('window.onbeforeunload = null;')
            except Exception:
                pass
            if len(self.d.window_handles) <= 1:
                break
            try:
                self.d.close()
            except Exception as e:
                self.log(f'  关闭多余窗口失败（继续）: {type(e).__name__}: {str(e).splitlines()[0][:130]}')
                try:
                    self.d.get('about:blank')
                except Exception:
                    pass
                break
        try:
            self.d.switch_to.window(self.d.window_handles[0])
        except Exception as e:
            self.log(f'  切换回主窗口时出错（继续）: {type(e).__name__}: {e}')
        self._get(self.course_url)
        if len(self.d.window_handles) > 1:
            self.log(f'  注意: 当前仍有 {len(self.d.window_handles)} 个窗口')

    def leave_video_page(self, opened_new_window):
        player.cleanup(self.d, self.site)
        if opened_new_window:
            try:
                if len(self.d.window_handles) > 1:
                    self.d.close()
                self.d.switch_to.window(self.d.window_handles[-1])
            except Exception as e:
                self.log(f'  关闭视频窗口时出错（继续）: {type(e).__name__}: {str(e).splitlines()[0][:130]}')

    def _wait_video_ready(self):
        try:
            WebDriverWait(self.d, VIDEO_READY_TIMEOUT).until(
                lambda x: x.execute_script('return !!document.querySelector("video");'))
            return True
        except Exception:
            return False

    def _play_one(self, title):
        """在当前视频页播放到结束。返回 True=播完/跳过，None=本轮没开起来。"""
        if not self._wait_video_ready():
            self.log(f'{ts()} 警告: 视频页 {VIDEO_READY_TIMEOUT} 秒内没有 video 元素，本轮放弃')
            return None

        player.setup_play_monitor(self.d, log=self.log)
        # 站点额外播放脚本（如超星 iframe 锁倍速）
        extra = self.site.extra_player_js(self.speed)
        if extra:
            try:
                self.d.execute_script(extra)
            except Exception as e:
                self.log(f'  提示: 站点额外播放脚本失败: {type(e).__name__}: {e}')
        # 站点可选择不装倍速锁（如智慧树：按学习时长计时，强锁倍速反而拖慢进度）
        if getattr(self.site, 'use_speed_lock', True):
            player.install_play_lock(self.d, self.speed, self.log)
        else:
            self.log(f'{ts()} 本站按学习时长计时，使用播放器原速（不锁倍速）')

        last_pos = -1.0
        last_t = None
        measured = None
        stalled = 0
        extra_finished = self.site.finished_extra_js()
        while True:
            # 站点弹窗（智慧树弹题等），持续处理
            try:
                self.site.handle_popups(self.d)
            except Exception:
                pass

            # 判据一：时间回退标记
            try:
                if self.d.execute_script('return document.querySelector("#__core_Finished");'):
                    self.log(f'{ts()} 检测到播放结束标记，再等 5 秒')
                    sleep(5)
                    return True
            except Exception:
                pass

            # 判据二：播放器状态 ended / 接近结尾
            try:
                info = self.d.execute_script(
                    'var v = document.querySelector("video");'
                    'if (!v) { return null; }'
                    'return [v.currentTime || 0, v.duration || 0, v.ended ? 1 : 0];')
            except Exception:
                info = None
            if info:
                pos, dur, ended = info
                if ended or (dur and pos >= dur - 0.5):
                    self.log(f'{ts()} 播放已到结尾（{pos:.1f}s / {dur:.1f}s）')
                    sleep(3)
                    return True
                now_t = monotonic()
                if last_t is not None and now_t > last_t and pos > last_pos:
                    measured = (pos - last_pos) / (now_t - last_t)
                last_t = now_t
                # duration 还是 0 = 播放器元数据没加载完，不算卡住（避免开场误判）
                if not dur:
                    stalled = 0
                else:
                    stalled = stalled + 1 if (last_pos >= 0 and pos <= last_pos + 0.05) else 0
                last_pos = pos
                speed_txt = f' | 实测倍速 {measured:.2f}x' if measured else ''
                self.log(f'{ts()} 正在播放视频 | 已播 {pos:.0f}s / 共 {dur:.0f}s{speed_txt}')
            else:
                stalled += 1

            # 判据三：站点额外完成判据
            if extra_finished:
                try:
                    if self.d.execute_script('return (' + extra_finished + ');'):
                        self.log(f'{ts()} 站点判据判定本节已完成')
                        sleep(3)
                        return True
                except Exception:
                    pass

            # 判据四：卡死兜底（约 5 分钟无前进）
            if stalled >= 100:
                self.log(f'{ts()} 警告: 视频 5 分钟没有前进，放弃这一集，跳到下一个')
                self.SKIPPED_STALLED.append(title)
                return True
            sleep(3)

    def finish1video(self):
        """挑一个未完成小节并播完。返回 True=播了一个，False=没得播，None=本轮没进展。"""
        units = self.site.prepare_course_page(self.d, self.course_url)
        if not units:
            self.ABORTED_NO_CLASSES = True
            self.log(f'{ts()} 警告: 页面上没有找到任何小节元素，本次不会播放任何视频')
            self.log(f'  当前 URL: {self.d.current_url}')
            self.log(f'  页面标题: {self.d.title}')
            self.log(f'  常见原因: 课程页没加载完 / 未登录成功 / 该站点 UI 结构与预期不同')
            self.dump_dom()
            return None

        video, title, st = self.scan_target()
        if video is None:
            if st.get('blankTitle'):
                self.log(f'{ts()} 警告: {st["blankTitle"]} 个小节取不到标题，课程页可能没渲染完，本轮放弃重来')
                return None
            self.LOCKED_VIDEOS = st.get('locked', 0)
            self.log(f'{ts()} 没有未完成的视频了（小节 {st.get("total", 0)} 个: 已完成 {st.get("done", 0)}, '
                     f'未开放 {st.get("locked", 0)}, 已过期 {st.get("expired", 0)}, '
                     f'本次已播 {st.get("played", 0)}, 非视频 {st.get("notVideo", 0)}）')
            return False

        self.PLAYED_TITLES.add(title)
        self.log(f'{ts()} 目标: {title}（本次还剩 {1 + st.get("pending", 0)} 个视频待播）')

        # 注入截获 window.open（雨课堂需要；其他站点默认返回 0）
        try:
            retargeted = self.d.execute_script(self.site.capture_open_js())
        except Exception:
            retargeted = 0
        before_handles = self.d.window_handles[:]

        self.site.open_lesson(self.d, video)
        sleep(2)

        new_handles = [h for h in self.d.window_handles if h not in before_handles]
        try:
            video_url = self.d.execute_script(self.site.captured_video_url_js())
        except Exception:
            video_url = None

        opened_new_window = False
        if new_handles:
            self.d.switch_to.window(new_handles[-1])
            opened_new_window = True
            self.log(f'{ts()} 正在播放（新标签页 —— 已改写 {retargeted} 个 target）')
        elif video_url:
            self._get(video_url)
            self.log(f'{ts()} 正在播放（当前标签页直达视频页）')
        else:
            self.log(f'{ts()} 正在播放（站点已在当前页切换）')

        # 站点额外动作：如智慧树新形态课程点开小节后，还要点里面的 mp4 资源
        # 才会加载 video.js。等资源列表渲染（约 3 秒）再执行。
        try:
            if self.site.after_open_lesson(self.d, title):
                self.log(f'{ts()} 已打开本节视频资源')
        except Exception as e:
            self.log(f'  站点额外动作失败（继续尝试播放）: {type(e).__name__}: {e}')

        try:
            result = self._play_one(title)
            return result
        finally:
            self.leave_video_page(opened_new_window)

    def run(self):
        if not self.goto_course_page():
            self.log('未能进入课程页，退出。请检查凭据 / headless 设置。')
            self.bm.quit()
            return 1

        consecutive_errors = 0
        no_progress_rounds = 0
        total_played = 0
        browser_deaths = 0
        force_restart = False

        def reenter(drv):
            return self.goto_course_page(allow_qr=False)

        while True:
            if force_restart or not self.bm.alive():
                force_restart = False
                browser_deaths += 1
                if browser_deaths > self.bm.max_restarts:
                    self.ABORTED_BROWSER = True
                    self.log(f'{ts()} 浏览器连续崩了 {browser_deaths - 1} 次、重建后仍起不来，停止。')
                    break
                if self.bm.restart(reenter):
                    self.log(f'{ts()} 重建完成，接着刷（第 {browser_deaths} 次重建）')
                else:
                    sleep(10)
                continue

            try:
                played = self.finish1video()
                consecutive_errors = 0
                browser_deaths = 0
            except Exception as e:
                if is_browser_gone(e):
                    self.log(f'{ts()} 标签页/浏览器崩溃: {type(e).__name__}: {str(e).splitlines()[0][:120]}')
                    force_restart = True
                    continue
                consecutive_errors += 1
                self.log(f'{ts()} 本轮出错（连续第 {consecutive_errors} 次）: {type(e).__name__}: {e}')
                if consecutive_errors >= 3:
                    self.ABORTED_ERRORS = True
                    self.log('连续 3 轮出错，停止。已播完的进度都已记录，重跑即可接着刷。')
                    break
                sleep(10)
                try:
                    self.back_to_course_page()
                except Exception:
                    pass
                sleep(5)
                continue

            if played is None:
                no_progress_rounds += 1
                self.log(f'{ts()} 本轮没有任何进展（连续第 {no_progress_rounds} 次），回课程页重来')
                if no_progress_rounds >= 3:
                    self.ABORTED_NO_PROGRESS = True
                    self.log('连续 3 轮没有任何进展，停止。这不是"刷完了"，请检查上面的警告。')
                    break
                try:
                    self.back_to_course_page()
                except Exception:
                    pass
                sleep(5)
                continue

            no_progress_rounds = 0
            if not played:
                break
            total_played += 1
            self.log(f'{ts()} —— 已播完 {total_played} 个视频，切下一个 ——')
            self.back_to_course_page()
            sleep(5)

        self.bm.quit()
        self._report(total_played)
        return 0

    def _report(self, total_played):
        if self.ABORTED_NO_CLASSES:
            self.log(f'{ts()} 已中止: 未找到任何小节元素，视频没有被播放，请查看上面的警告信息')
        elif self.ABORTED_ERRORS:
            self.log(f'{ts()} 已中止: 连续出错，任务没有跑完。重跑会接着刷没完成的。')
        elif self.ABORTED_BROWSER:
            self.log(f'{ts()} 已中止: 浏览器反复崩溃，重建也起不来（本次共播出 {total_played} 个）。')
        elif self.ABORTED_NO_PROGRESS:
            self.log(f'{ts()} 已中止: 连续 3 轮没能开始播放任何视频（本次共播出 {total_played} 个）。这不代表刷完了。')
        else:
            if self.LOCKED_VIDEOS:
                self.log(f'{ts()} 本次结束: 没有可播的视频了，但还有 {self.LOCKED_VIDEOS} 个视频处于未开放（带锁）状态（本次共播出 {total_played} 个）')
            else:
                self.log(f'{ts()} 恭喜你！全部播放完毕（本次共播出 {total_played} 个视频）')
            if self.SKIPPED_STALLED:
                self.log(f'注意: 有 {len(self.SKIPPED_STALLED)} 个视频因播放卡住被跳过，重跑会再试:')
                for t in self.SKIPPED_STALLED:
                    self.log(f'  - {t}')
