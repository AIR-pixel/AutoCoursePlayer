'''
首次配置向导（多站点版）。

流程：
  第 0 步  选站点（yuketang / chaoxing / zhihuishu）
  第 1 步  拿登录凭据（各站点不同；雨课堂优先读 Firefox cookie）
  第 2 步  调该站点接口列课程，挑一门写进 config.ini

列课程走纯 HTTP（零点几秒），不值得为它开浏览器。
"凭据还有没有效"也用它判定：列得出来就是有效的。

底下三个 fetch_courses_xxx 是各站点的课程列表实现，被 sites/ 适配器调用。
这些接口来自各站点公开的前端 API / 开源项目（ocsjs 等），可能随站点改版失效。
'''
import json
import urllib.parse
import urllib.request

import refresh_cookie

HTTP_TIMEOUT = 12
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')


def host_of(url: str) -> str:
    if not url.startswith('http'):
        return url
    return 'https://' + url.split('//', 1)[-1].split('/')[0] + '/'


def _open(url, headers, timeout=HTTP_TIMEOUT):
    """先按系统/环境代理请求，失败再直连试一次。"""
    last = None
    for opener in (urllib.request.build_opener(),
                   urllib.request.build_opener(urllib.request.ProxyHandler({}))):
        try:
            return opener.open(urllib.request.Request(url, headers=headers), timeout=timeout)
        except Exception as e:
            last = e
    raise last


def _get_json(url, headers):
    with _open(url, headers) as resp:
        return json.loads(resp.read().decode('utf-8', 'replace'))


# ---------------- 各站点课程列表 ----------------

def fetch_courses_yuketang(sessionid: str, host: str):
    """长江雨课堂。接口 /v2/api/web/courses/list?identity=2。"""
    host = host.rstrip('/') + '/'
    headers = {
        'Cookie': f'sessionid={sessionid}',
        'Accept': 'application/json, text/plain, */*',
        'User-Agent': UA,
        'Referer': host + 'v2/web/index',
    }
    data = _get_json(host + 'v2/api/web/courses/list?identity=2', headers)
    if data.get('errcode'):
        raise RuntimeError(f"接口返回 errcode={data.get('errcode')}: {data.get('errmsg')}")
    courses = []
    for c in (data.get('data') or {}).get('list') or []:
        course = c.get('course') or {}
        if not c.get('classroom_id'):
            continue
        courses.append({
            'id': c['classroom_id'],
            'title': course.get('name') or c.get('name') or '(无标题课程)',
            'class_name': c.get('name') or '',
            'teacher': (c.get('teacher') or {}).get('name') or '',
            'school': course.get('university_name') or '',
        })
    return courses


def fetch_courses_zhihuishu(cookie_value: str, host: str):
    """智慧树。尝试从公开接口列课；失败时返回空让向导走手动输入。

    智慧树的课程列表接口需登录态且形态多样（共享课/新形态/智慧课程各不同），
    裸 arn 未必够。这里尽力尝试，实在不行不阻塞用户手动粘课程地址。
    """
    host = host.rstrip('/') + '/'
    arn = (cookie_value or '').strip()
    if '=' in arn:
        arn = arn.split('=', 1)[1].strip()
    headers = {
        'Cookie': f'arn={arn}',
        'Accept': 'application/json, text/plain, */*',
        'User-Agent': UA,
        'Referer': host,
    }
    # 智慧树常见的课程列表接口（不同学习页可能不同，逐个试）
    api_candidates = [
        'https://www.zhihuishu.com/portal/al-api/share/getMyCourse',
        'https://www.zhihuishu.com/gateway/portal/course/stu/courseList',
    ]
    last = None
    for api in api_candidates:
        try:
            data = _get_json(api, headers)
            rows = None
            for key in ('result', 'data', 'list'):
                v = data
                for k in key.split('.'):
                    v = (v or {}).get(k) if isinstance(v, dict) else None
                if isinstance(v, list):
                    rows = v
                    break
            if not rows:
                continue
            courses = []
            for c in rows:
                cid = c.get('courseId') or c.get('id') or c.get('course_id')
                if not cid:
                    continue
                courses.append({
                    'id': str(cid),
                    'title': c.get('name') or c.get('courseName') or '(无标题课程)',
                    'class_name': c.get('className') or '',
                    'teacher': c.get('teacherName') or '',
                    'school': c.get('universityName') or '',
                    'url': c.get('url') or '',
                })
            if courses:
                return courses
        except Exception as e:
            last = e
    # 列不出来不算致命 —— 让向导走"手动粘地址"
    return []


def fetch_courses_chaoxing(cookie_value: str, host: str):
    """超星学习通。课程列表接口需要 _d + UID，形态复杂。

    同样尽力尝试，失败返回空走手动输入。超星用户一般直接从浏览器粘课程地址。
    """
    host = host.rstrip('/') + '/'
    headers = {
        'Cookie': cookie_value if ('=' in (cookie_value or '')) else f'_d={cookie_value}',
        'Accept': 'application/json, text/plain, */*',
        'User-Agent': UA,
        'Referer': host,
    }
    api_candidates = [
        'https://mooc1.chaoxing.com/mycourse/studentcourse?ajax=1',
        'https://mooc1.chaoxing.com/mycourse/studentstudy?ajax=1',
    ]
    for api in api_candidates:
        try:
            data = _get_json(api, headers)
            rows = data if isinstance(data, list) else (data.get('data') or [])
            courses = []
            for c in rows if isinstance(rows, list) else []:
                if not isinstance(c, dict):
                    continue
                cid = c.get('courseId') or c.get('id')
                if not cid:
                    continue
                courses.append({
                    'id': str(cid),
                    'title': c.get('name') or c.get('courseName') or '(无标题课程)',
                    'class_name': c.get('className') or '',
                    'teacher': c.get('teacherName') or '',
                    'school': '',
                    'url': c.get('url') or '',
                })
            if courses:
                return courses
        except Exception:
            continue
    return []


# ---------------- 向导交互 ----------------

def _ask(prompt: str, default: str = '') -> str:
    try:
        return input(prompt).strip() or default
    except EOFError:
        return default


def choose_site():
    import sites
    pairs = sites.list_adapters()
    print('\n请选择要刷课的站点：')
    for i, (key, name) in enumerate(pairs, 1):
        print(f'  [{i}] {name}  ({key})')
    while True:
        ans = _ask('\n请输入序号（直接回车 = 1）: ', '1')
        if ans.isdigit() and 1 <= int(ans) <= len(pairs):
            return pairs[int(ans) - 1][0]
        print('  输入无效，请重新输入')


def choose_course(courses, adapter):
    print('\n可选的课程：')
    for i, c in enumerate(courses, 1):
        print(f'  [{i}] {c["title"]}')
        detail = ' · '.join(x for x in (
            f'教学班 {c["class_name"]}' if c['class_name'] else '',
            f'教师 {c["teacher"]}' if c['teacher'] else '',
            c['school'],
        ) if x)
        if detail:
            print(f'      {detail}')
    print('  [0] 手动输入课程地址')

    while True:
        ans = _ask('\n请输入序号（直接回车 = 1）: ', '1')
        if ans.isdigit() and int(ans) <= len(courses):
            break
        print('  输入无效，请重新输入')

    index = int(ans)
    if index == 0:
        manual = _ask('请粘贴课程地址（https:// 开头）: ')
        return manual if manual.startswith('http') else None
    c = courses[index - 1]
    if c.get('url', '').startswith('http'):
        url = c['url']
    else:
        # host 由适配器在 ensure_ready 里传入；这里用占位的默认 host，稍后替换
        url = adapter.course_url_of(_CURRENT_HOST[0], c['id'])
    print(f'  已选择: {c["title"]} -> {url}')
    return url


_CURRENT_HOST = ['']


def ensure_ready(path: str, force_reselect: bool = False):
    """把 config.ini 补到能跑：site + course_url + cookie。缺哪步补哪步。

    force_reselect=True 时强制重选站点（供 --site / 选择站点.bat 调用）。
    站点一旦变化，旧的 course_url / cookie / cookies_full 属于另一个站点，
    必须清掉，否则会拿 A 站的凭据去刷 B 站。
    """
    import sites

    cfg = refresh_cookie.read_config(path)

    def get(key):
        try:
            return (cfg.get('Settings', key) or '').strip()
        except Exception:
            return ''

    print('=' * 56)
    print('网课自动播放器 - 首次配置')
    print('=' * 56)

    # ---- 第 0 步：站点 ----
    old_site = get('site')
    site_key = old_site
    changed = force_reselect
    if force_reselect:
        site_key = choose_site()
        changed = (site_key != old_site)
    else:
        try:
            adapter = sites.get_adapter(site_key)
            print(f'\n当前站点: {adapter.name}（配置里 site = {site_key}）')
            change = _ask('换站点？输入 y 重选，直接回车沿用: ', '').lower()
            if change == 'y':
                site_key = choose_site()
                changed = (site_key != old_site)
        except Exception:
            site_key = choose_site()
            changed = (site_key != old_site)

    # 站点变了 → 旧凭据/课程地址属于另一个站，全部清空重新来
    if changed and old_site and old_site != site_key:
        old_name = sites.get_adapter(old_site).name if old_site in dict(sites.list_adapters()) else old_site
        new_name = sites.get_adapter(site_key).name
        print(f'\n已从「{old_name}」切换到「{new_name}」')
        print('  旧站点的课程地址和凭据已清空，下面为新站点重新配置。')
        for k in ('course_url', 'cookie', 'cookies_full'):
            refresh_cookie.set_config_value(path, k, '')
        url, cookie = '', ''
    refresh_cookie.set_config_value(path, 'site', site_key)
    from sites import get_adapter
    adapter = get_adapter(site_key)

    # 站点切换后 cfg 对象还是旧的，直接用刚清空的空值，别从旧 cfg 读回
    if changed and old_site and old_site != site_key:
        url, cookie = '', ''
    else:
        url = get('course_url')
        cookie = get('cookie')
    host = host_of(url) if url.startswith('http') else adapter.home_url('https://' + adapter.hosts[0] + '/')
    _CURRENT_HOST[0] = host

    # ---- 第 1 步：凭据 ----
    courses = None
    if cookie:
        try:
            courses = adapter.fetch_courses(cookie, host)
            print(f'  已保存的凭据可用（读到 {len(courses)} 门课程）')
        except Exception as e:
            print(f'  已保存的凭据不可用（{type(e).__name__}: {e}），需要重新获取')

    if not cookie or courses is None:
        print('\n第 1 步 / 2：获取登录凭据')
        cookie = adapter.get_credential()
        if not cookie:
            print('\n没有拿到登录凭据，配置未完成。')
            return False
        refresh_cookie.set_config_value(path, 'cookie', cookie)
        print(f'  已写入 config.ini（长度 {len(cookie)}，内容不回显）')
        try:
            courses = adapter.fetch_courses(cookie, host)
        except Exception as e:
            print(f'  读取课程列表失败（{type(e).__name__}: {e}），下面手动填地址')
            courses = None

    # ---- 第 2 步：课程 ----
    if url.startswith('http'):
        print(f'\n第 2 步 / 2：课程地址已配置 —— {url}')
        print('  想换课程：把 config.ini 里的 course_url 清空，再跑一次即可')
        return True

    if courses:
        chosen = choose_course(courses, adapter)
    else:
        print('\n第 2 步 / 2：手动输入课程地址')
        print(f'  拿法：{adapter.course_url_hint}')
        chosen = _ask('课程地址（https:// 开头）: ')

    if not chosen or not chosen.startswith('http'):
        print('\n课程地址无效，配置未完成。')
        return False
    refresh_cookie.set_config_value(path, 'course_url', chosen)
    print(f'  已写入 config.ini: {chosen}')
    print('\n配置完成。')
    return True
