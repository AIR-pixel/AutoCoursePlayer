# -*- coding: utf-8 -*-
"""一键打包：把项目打成一个可双击运行的 exe，并压成给用户下载的 zip。

产物（都在 dist/ 下）：
    长江雨课堂自动播放器.exe                单文件，双击即用，目标机器不需要装 Python
    长江雨课堂自动播放器-v<版本>.zip         给用户下载的包：
                                            exe + 使用说明.txt + 作者主页.url + LICENSE

用户那边的初始流程是自动的：exe 启动时发现自己旁边没有 config.ini（或里面还缺
course_url / cookie），就先走一遍配置向导 —— 自动取登录凭据、列课程让人挑，
写完再开始刷。所以"下载 -> 双击"就完事了，不需要看文档手填文件。

用法：
    python tools/build_exe.py               # 版本号取自 pyproject.toml
    python tools/build_exe.py 1.2.0         # 显式指定版本
    python tools/build_exe.py --no-zip      # 只出 exe，不打包
    python tools/build_exe.py --keep-build  # 保留 build/ 中间产物（默认会删）

注意：**已发布过的版本不要重打包。** 目标 zip 已存在时会拒绝覆盖，除非加
--force —— 否则 dist/ 里那份是用户已经下载走的字节，悄悄改掉会让校验值对不上。
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(REPO, 'dist')
BUILD = os.path.join(REPO, 'build')
APP_NAME = '网课自动播放器'
ENTRY = 'main.py'

# 显式带上，别让 PyInstaller 去猜。
# selenium 4.5x 的 selenium/webdriver/__init__.py 改成了动态 __getattr__ 懒加载
# （一张 "名字 -> (模块路径, 属性名)" 的表），PyInstaller 的静态分析跟不进字符串表，
# 于是 webdriver.Edge / webdriver.Chrome 这些运行时才解析的引用会被漏掉。
# 结果就是 exe 能启动、一到建浏览器就 ModuleNotFoundError。
HIDDEN_IMPORTS = [
    'selenium.webdriver.chrome.webdriver',
    'selenium.webdriver.chrome.options',
    'selenium.webdriver.chrome.service',
    'selenium.webdriver.edge.webdriver',
    'selenium.webdriver.edge.options',
    'selenium.webdriver.edge.service',
    'selenium.webdriver.firefox.options',
    'selenium.webdriver.common.selenium_manager',
    'selenium.webdriver.common.service',
]

# 本项目一行都没用到；不排掉的话 exe 会白白胖几十 MB。
# 刻意不动 unittest / setuptools / pkg_resources —— 有些库在导入期会碰它们。
EXCLUDES = [
    'tkinter', 'numpy', 'matplotlib', 'pandas', 'scipy', 'PIL', 'IPython', 'pytest',
]

USAGE_TXT = """网课自动播放器（Windows 免安装版）
========================================

第一次用？只看这三步就够了
--------------------------
把整个文件夹解压出来，里面有 3 个绿色 bat 按钮，双击对应的就行：

  【① 选择站点.bat】   第一次必用。选你要刷的平台（雨课堂/学习通/智慧树），
                       然后照提示登录、挑一门课。只做一次。

  【② 开始刷课.bat】   选完站点后，以后每天就双击这个。自动后台播放、
                       跳过看过的、播完自动切下一集。关掉窗口=停止。

  【③ 手动获取Cookie.bat】 提示"要重新登录"或刷不动时双击这个，
                       会打开浏览器让你登录，登录完自动继续，不用管其它。

就这么简单。下面是一些你可能想知道的。


包里有什么
----------
· ① 选择站点.bat       —— 换平台 / 第一次配置（双击）
· ② 开始刷课.bat       —— 日常刷课（双击）
· ③ 手动获取Cookie.bat —— 凭据过期时重新登录（双击）
· {app}.exe            —— 主程序，bat 就是调用它，不用单独双击
· 使用说明.txt         —— 就是这个文件
· LICENSE / 作者主页.url


常见问题
--------
Q: 双击后窗口一闪就没了？
A: 现在不会了。真出错时会停在窗口里显示原因和解决办法，把那一段截图发作者即可。

Q: 提示"要重新登录 / Cookie 过期"？
A: 双击【③ 手动获取Cookie.bat】，在打开的浏览器里登录一次，程序会自动接着刷。
   （各平台登录态隔几天会失效，这是平台机制，不是坏了。）

Q: 想换课程 / 换平台？
A: 换平台：双击【① 选择站点.bat】重选。
   换课程（同平台）：用记事本打开 config.ini，清空 course_url 那一行，再双击【②】。

Q: 不想在后台跑、想看着它播？
A: 用记事本打开 config.ini，把 headless = true 改成 false，再双击【②】。

Q: 智慧树为什么是 1 倍速？
A: 智慧树按"学习时长"记完成，强开倍速反而会让视频推进变慢（实测 1.5x 变成 0.2x），
   所以本站固定 1x 原速，这是最快最稳的。超星 2x、雨课堂按 config 里的 speed。


它做什么
--------
· 后台无窗口运行，自动切换下一集，已经看完的自动跳过。
· 未开放（带锁）的小节不算"刷完"，日志里如实说明。
· 断点续播：进度记在平台服务端，中途关掉再开就接着刷。


注意
----
· 需要 Edge 或 Chrome（Windows 10/11 一般自带 Edge）。程序会优先用系统默认浏览器。
· 首次运行会联网下载浏览器驱动，稍有等待属正常；之后走本地缓存。
· exe 没有代码签名，SmartScreen 提示「未知发布者」时点「更多信息」→「仍要运行」。
· 请自行确认用途符合所在学校/平台规定，风险自负。

许可
----
LGPL-2.1，详见随包的 LICENSE。
"""

# 随包附一个"直达作者主页"的快捷方式。
#
# 用 .url（Internet 快捷方式）而不是 .lnk：
#   * .lnk 是二进制格式，得靠 COM（WScript.Shell）生成，而本机沙箱正好禁 New-Object -ComObject；
#   * .url 是 INI 式纯文本，可复现、可 diff，任何 Windows 双击都能用默认浏览器打开。
# 内容必须是**纯 ASCII 且不带 BOM**：.url 按 ANSI 解析，BOM 会让它整个认不出来。
# 行尾用 CRLF —— .url 是 INI 血统，按惯例来，别在这里省字节。
AUTHOR_HOMEPAGE = 'https://github.com/AIR-pixel'
SHORTCUT_NAME = '作者主页.url'


def version() -> str:
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if args:
        return args[0]
    with open(os.path.join(REPO, 'pyproject.toml'), 'rb') as f:
        return tomllib.load(f)['project']['version']


def ensure_pyinstaller():
    if importlib.util.find_spec('PyInstaller') is None:
        print('[!] 当前解释器里没有 PyInstaller，先装上（这是 pyproject 里声明的构建依赖）')
        print(f'    {sys.executable} -m pip install "pyinstaller>=6.16"')
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller>=6.16'],
                       check=True)
        print()


def write_version_file(ver: str) -> str:
    """生成 PyInstaller 的版本资源文件。

    没有它，exe 属性里是空的；有了它，右键 -> 属性能看到版本号和说明，
    用户报问题时也能一眼看到跑的是哪版。
    """
    parts = (ver.split('.') + ['0', '0', '0'])[:4]
    nums = ', '.join(str(int(p)) for p in parts)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({nums}), prodvers=({nums}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404b0', [
        StringStruct('CompanyName', ''),
        StringStruct('FileDescription', '网课自动播放器（雨课堂/学习通/智慧树）'),
        StringStruct('FileVersion', '{ver}'),
        StringStruct('InternalName', '{APP_NAME}'),
        StringStruct('LegalCopyright', 'LGPL-2.1'),
        StringStruct('OriginalFilename', '{APP_NAME}.exe'),
        StringStruct('ProductName', '网课自动播放器（雨课堂/学习通/智慧树）'),
        StringStruct('ProductVersion', '{ver}'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    path = os.path.join(BUILD, 'version_info.txt')
    os.makedirs(BUILD, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def run_pyinstaller(ver: str):
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--clean', '--onefile', '--console',
        '--name', APP_NAME,
        '--distpath', DIST, '--workpath', BUILD, '--specpath', BUILD,
        '--version-file', write_version_file(ver),
    ]
    for m in HIDDEN_IMPORTS:
        cmd += ['--hidden-import', m]
    for m in EXCLUDES:
        cmd += ['--exclude-module', m]
    cmd.append(ENTRY)

    print('[1/3] PyInstaller ...')
    subprocess.run(cmd, cwd=REPO, check=True)
    exe = os.path.join(DIST, APP_NAME + '.exe')
    if not os.path.exists(exe):
        sys.exit(f'[X] 没生成 {exe}，看上面的 PyInstaller 日志')
    print(f'      OK  {os.path.relpath(exe, REPO)}  ({os.path.getsize(exe) / 1048576:.1f} MB)')


def zip_target(ver: str) -> str:
    return os.path.join(DIST, f'{APP_NAME}-v{ver}.zip')


def guard_release(ver: str, force: bool):
    """已发布过的版本不许悄悄重打。

    这一步刻意放在**构建之前**：跑完两分钟 PyInstaller 再报"不准覆盖"是白等，
    早退早改。
    """
    target = zip_target(ver)
    if os.path.exists(target) and not force:
        sys.exit(f'[X] {os.path.relpath(target, REPO)} 已存在（很可能已经发布过了）。\n'
                 '    确认要重打就加 --force，但记得同步重发 Release，\n'
                 '    否则对外公布的校验值会与实际附件对不上。')


def make_shortcut() -> str:
    """生成「作者主页.url」并返回路径。

    按字节写而不是用文本模式：要的是**确定的** ASCII + CRLF + 无 BOM，
    文本模式会跟着平台/编码设置飘，而 .url 一旦带上 BOM 就整个失效。
    """
    path = os.path.join(BUILD, SHORTCUT_NAME)
    with open(path, 'wb') as f:
        f.write(b'[InternetShortcut]\r\n')
        f.write(b'URL=' + AUTHOR_HOMEPAGE.encode('ascii') + b'\r\n')
    return path


# 三个双击入口，只调用 exe、不依赖系统 Python。
# 内容全 ASCII（避免 GBK/UTF-8 编码坑），文件名用中文方便用户识别。
# 每个 bat 末尾 pause：即使 exe 自己没停住，窗口也不会一闪而过。
BAT_FILES = {
    '① 选择站点.bat': '"%~dp0{app}.exe" --site',
    '② 开始刷课.bat': '"%~dp0{app}.exe"',
    '③ 手动获取Cookie.bat': '"%~dp0{app}.exe" --cookie',
}


def make_bat_scripts():
    """生成三个 bat，返回 [(绝对路径, 归档名), ...]。"""
    os.makedirs(BUILD, exist_ok=True)
    out = []
    for name, cmd in BAT_FILES.items():
        body = (
            '@echo off\r\n'
            'cd /d "%~dp0"\r\n'
            'set "NO_PROXY=localhost,127.0.0.1,::1"\r\n'
            'set "no_proxy=localhost,127.0.0.1,::1"\r\n'
            + cmd.format(app=APP_NAME) + '\r\n'
            'echo.\r\n'
            'pause\r\n'
        )
        path = os.path.join(BUILD, name)
        # bat 里的 exe 名是中文，用 GBK 编码（中文 Windows 的 cmd 默认代码页），
        # 和项目现有 run.bat 一致。文件名本身用中文方便用户识别。
        with open(path, 'wb') as f:
            f.write(body.encode('gbk'))
        out.append((path, name))
    return out


def make_zip(ver: str) -> str:
    target = zip_target(ver)
    exe = os.path.join(DIST, APP_NAME + '.exe')
    members = [(exe, f'{APP_NAME}.exe'),
               (os.path.join(REPO, 'LICENSE'), 'LICENSE'),
               (make_shortcut(), SHORTCUT_NAME)]
    # 三个双击入口放在最前，用户解压第一眼就看到
    members = make_bat_scripts() + members
    usage = os.path.join(BUILD, '使用说明.txt')
    # utf-8-sig：老版本记事本不认无 BOM 的 UTF-8，会显示成乱码
    with open(usage, 'w', encoding='utf-8-sig') as f:
        f.write(USAGE_TXT.format(app=APP_NAME))
    members.append((usage, '使用说明.txt'))

    print('[2/3] 压缩 ...')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo(APP_NAME + '/'), b'')   # 顶层目录项，解压后目录树整齐
        for src, arc in members:
            z.write(src, f'{APP_NAME}/{arc}')
    print(f'      OK  {os.path.relpath(target, REPO)}  ({os.path.getsize(target) / 1048576:.1f} MB)')
    return target


def main():
    ver = version()
    force = '--force' in sys.argv
    with_zip = '--no-zip' not in sys.argv
    print(f'打包 {APP_NAME} v{ver}  ({REPO})')

    if with_zip:
        guard_release(ver, force)
    ensure_pyinstaller()
    run_pyinstaller(ver)

    if not with_zip:
        print('[3/3] 跳过压缩（--no-zip）')
    else:
        make_zip(ver)

    if '--keep-build' not in sys.argv:
        shutil.rmtree(BUILD, ignore_errors=True)
    print('\n完成。dist/ 里的东西可以直接发出去。')


if __name__ == '__main__':
    main()
