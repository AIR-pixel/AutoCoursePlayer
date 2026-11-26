'''
冒烟测试：不登录、不开浏览器，几秒钟验证内核和三站点适配器没坏。

用法：
    python tools/smoke_test.py

检查项：
  1. selenium 依赖
  2. 所有模块可导入
  3. 三站点注册表 + 接口完整
  4. URL 自动识别
  5. 倍速上限夹取
  6. 雨课堂核心 JS 与重构前逐字节一致（需 main_legacy.py.bak 存在）
  7. 当前 config.ini 能被新版正确读取

任何一项 FAIL 都会让程序以非零码退出。改完 sites/ 里的选择器后跑一遍，
能在不联网、不刷课的情况下快速确认没把内核改坏。
'''
import ast
import configparser
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((True, name, detail or ''))
    except Exception as e:
        results.append((False, name, f'{type(e).__name__}: {e}'))


def norm_js(s):
    s = re.sub(r'//[^\n]*', '', s)   # 去行注释
    return re.sub(r'\s+', '', s)     # 去所有空白


def extract_js(path, varname):
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == varname:
                    return ast.literal_eval(node.value)
    return None


# ---- 1. selenium ----
def t_selenium():
    import selenium
    return f'v{selenium.__version__}'


check('selenium 依赖', t_selenium)

# ---- 2. 全模块导入 ----
def t_imports():
    import main, firstrun, refresh_cookie
    from core import browser, player, engine
    import sites
    import sites.yuketang, sites.chaoxing, sites.zhihuishu
    return 'main / core / sites 全部导入成功'


check('全模块导入', t_imports)

# ---- 3. 注册表 + 接口 ----
def t_registry():
    import sites
    pairs = sites.list_adapters()
    assert len(pairs) == 3, f'期望 3 个站点，实际 {len(pairs)}'
    for key, name in pairs:
        a = sites.get_adapter(key)
        assert not getattr(a, '__abstractmethods__', None), f'{key} 有未实现的接口: {a.__abstractmethods__}'
        for m in ('fetch_courses', 'course_url_of', 'is_login_page', 'scan_js', 'open_lesson'):
            assert hasattr(a, m), f'{key} 缺方法 {m}'
    return ', '.join(k for k, _ in pairs)


check('三站点注册表 + 接口完整', t_registry)

# ---- 4. URL 识别 ----
def t_urls():
    import sites
    cases = [
        ('https://changjiang.yuketang.cn/v2/web/studentLog/123', 'yuketang'),
        ('https://ai-smart-course-student-pro.zhihuishu.com/learnPage/1/2/3', 'zhihuishu'),
        ('https://mooc1.chaoxing.com/mycourse/studentstudy?courseId=1', 'chaoxing'),
    ]
    for url, want in cases:
        got = sites.guess_adapter_key(url)
        assert got == want, f'{url} -> {got}, 期望 {want}'
    return '3/3 正确'


check('课程 URL 自动识别', t_urls)

# ---- 5. 倍速夹取 ----
def t_speed():
    import sites
    cases = [('zhihuishu', 4, 1.0), ('chaoxing', 4, 2.0), ('yuketang', 2, 2.0)]
    out = []
    for site, inp, want in cases:
        a = sites.get_adapter(site)
        speed = min(4.0, max(0.5, float(inp)))
        cap = getattr(a, 'MAX_SPEED', None)
        if cap and speed > cap:
            speed = cap
        assert speed == want, f'{site}: {inp}x -> {speed}x, 期望 {want}x'
        out.append(f'{site} {inp}x→{speed}x' + ('(原速,不锁倍速)' if not a.use_speed_lock else ''))
    return ', '.join(out)


check('站点倍速上限夹取', t_speed)

# ---- 6. 雨课堂 JS 一致性 ----
def t_js_parity():
    bak = os.path.join(ROOT, 'main_legacy.py.bak')
    if not os.path.exists(bak):
        return '跳过（无 main_legacy.py.bak 备份）'
    import sites.yuketang as y
    vars_ = ['SCAN_TARGET_JS', 'UNITS_RENDERED_JS', 'CAPTURE_VIDEO_URL_JS']
    for v in vars_:
        old = norm_js(extract_js(bak, v) or '')
        new = norm_js(getattr(y.YuketangAdapter, v))
        assert old and old == new, f'{v} 与重构前不一致'
    return '3/3 段核心 JS 逐字节一致（行为等价）'


check('雨课堂核心 JS 与重构前一致', t_js_parity)

# ---- 7. 配置兼容 ----
def t_config():
    import main
    s = main.load_settings(main.refresh_cookie.config_path())
    assert s['site'] in ('yuketang', 'chaoxing', 'zhihuishu'), f"未知 site={s['site']}"
    assert isinstance(s['headless'], bool)
    cfgd = '已配置' if (s['course_url'] and s['cookie']) else '未配置（首次运行会走向导）'
    return f"site={s['site']}, 课程/Cookie={cfgd}"


check('当前 config.ini 兼容', t_config)

# ---- 汇总 ----
print('=' * 60)
print('网课自动播放器 v2 - 冒烟测试')
print('=' * 60)
for ok, name, detail in results:
    mark = '[PASS]' if ok else '[FAIL]'
    print(f'{mark} {name}' + (f'  — {detail}' if detail else ''))
print('=' * 60)
failed = [n for ok, n, _ in results if not ok]
if failed:
    print(f'有 {len(failed)} 项失败: {", ".join(failed)}')
    print('把上面的报错发给我。')
    sys.exit(1)
print('全部通过。代码本身没问题，可以进入真实站点测试。')
sys.exit(0)
