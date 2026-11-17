'''
播放内核：倍速锁 / 静音 / 防暂停续播 / 结束探测。
全部作用于 HTMLMediaElement.prototype 或现查现用的 <video>，与站点无关。
从原 main.py 469-550、830-915 行搬迁，逻辑未变。
'''

# 倍速锁：给 playbackRate 装 setter，吞掉"往低调"的写入（否则播放器每 250ms 复位一次）。
# 装在原型上，播放器卸载重建 <video> 也不怕。定时器给新元素补刀。
PLAYER_LOCK_JS = '''
(function (cfg) {
    if (!window.__coreLock) {
        var desc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'playbackRate');
        if (!desc || !desc.set) { return 'no-native-setter'; }
        window.__coreDesc = desc;
        window.__coreSpeed = 0;
        window.__coreMute = false;
        window.__coreBlocked = 0;
        Object.defineProperty(HTMLMediaElement.prototype, 'playbackRate', {
            configurable: true,
            enumerable: desc.enumerable,
            get: function () { return desc.get.call(this); },
            set: function (v) {
                if (window.__coreSpeed && v < window.__coreSpeed) {
                    window.__coreBlocked++;
                    return;
                }
                return desc.set.call(this, v);
            }
        });
        window.__coreLock = true;
        window.__coreTimer = setInterval(function () {
            var v = document.querySelector('video');
            if (!v) { return; }
            try {
                if (window.__coreSpeed && v.playbackRate < window.__coreSpeed) { v.playbackRate = window.__coreSpeed; }
                if (window.__coreMute && !v.muted) { v.muted = true; }
            } catch (e) {}
        }, 1000);
    }
    window.__coreSpeed = cfg.speed;
    window.__coreMute = cfg.mute;
    var v = document.querySelector('video');
    if (v && v.playbackRate < cfg.speed) { try { v.playbackRate = cfg.speed; } catch (e) {} }
    return 'ok';
})(arguments[0]);
'''

# 开场补播：播放器可能晚几秒才自动播
RESUME_JS = '''
window.__coreResumeTimer = setInterval(function () {
  var v = document.querySelector("video");
  if (v && v.paused) { try { v.play(); } catch (e) {} }
}, 200);
setTimeout(function () { clearInterval(window.__coreResumeTimer); }, 5000);
'''

# 结束探测：currentTime 回退就插一个标记（播放器循环时命中）
FINISH_WATCH_JS = '''
window.__coreLastPos = 0;
window.__coreFinishTimer = setInterval(function () {
  var v = document.querySelector("video");
  if (!v) { return; }
  if (v.currentTime < window.__coreLastPos) {
    var m = document.createElement("span");
    m.setAttribute("id", "__core_Finished");
    document.body.appendChild(m);
  }
  window.__coreLastPos = v.currentTime;
}, 200);
'''

# 暂停即续播：挂 document 捕获阶段，pause 不冒泡但捕获能收到
ANTI_PAUSE_JS = '''
document.addEventListener("pause", function (e) {
  try {
    if (!window.__coreDone && e.target && e.target.tagName === "VIDEO") { e.target.play(); }
  } catch (err) {}
}, true);
'''

# 离开视频页前拆干净自己注入的东西
CLEANUP_JS = '''
window.__coreDone = true;
try { clearInterval(window.__coreTimer); } catch (e) {}
try { clearInterval(window.__coreResumeTimer); } catch (e) {}
try { clearInterval(window.__coreFinishTimer); } catch (e) {}
try { window.onbeforeunload = null; } catch (e) {}
'''


def install_play_lock(d, speed, log=print):
    """装播放锁 + 倍速校验。返回是否成功。"""
    try:
        r = d.execute_script(PLAYER_LOCK_JS, {'speed': speed, 'mute': True})
    except Exception as e:
        log(f'警告: 安装播放锁失败（不影响播放与切集）: {type(e).__name__}: {e}')
        return False
    if r == 'no-native-setter':
        log('警告: playbackRate 没有原生 setter，无法锁倍速（不影响播放与切集）')
        return False
    now = None
    for _ in range(6):
        import time
        time.sleep(1)
        try:
            now = d.execute_script('var v = document.querySelector("video"); return v ? v.playbackRate : null;')
        except Exception as e:
            log(f'警告: 校验倍速时出错: {type(e).__name__}: {e}')
            return False
        if now and now >= speed - 0.01:
            blocked = d.execute_script('return window.__coreBlocked || 0;') or 0
            log(f'已锁定播放速度: {now}x（已拦截播放器复位 {blocked} 次；UI 可能仍显示原倍速，属正常）')
            return True
    if now is None:
        log('警告: 暂时取不到 video 元素；播放锁已挂上，视频一出现会自动生效')
    else:
        log(f'警告: 倍速没锁住，当前 {now}x（不影响播放与切集，但会按原速跑）')
    return False


def setup_play_monitor(d, log=print):
    """装好开场补播、结束探测、暂停续播。

    站点弹窗处理（handle_popups）和站点专属结束判据（finished_extra_js）
    由引擎在播放循环里按轮调用，不在这里注入。
    """
    d.execute_script(RESUME_JS)
    d.execute_script(FINISH_WATCH_JS)
    d.execute_script(ANTI_PAUSE_JS)


def cleanup(d, site=None):
    """离开视频页前拆掉所有注入。"""
    js = CLEANUP_JS
    if site:
        extra = site.cleanup_js()
        if extra:
            js += '\n' + extra
    try:
        d.execute_script(js)
    except Exception:
        pass
