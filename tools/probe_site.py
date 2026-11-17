'''
站点结构探测器（只读，不点任何视频、不改配置）。

用途：某个站点读不到小节/播放不了时，用它 dump 页面结构，
拿 class 采样和 iframe / video 清单去校准 sites/ 里的选择器。

用法：
    python tools/probe_site.py <课程网址>

要求：浏览器里先登录好该站点（本脚本会打开一个可见窗口，
      如果没有登录态就自己扫码登录后，再复制课程网址传给本脚本）。
      
产出：程序目录下 _probe_<域名>_<时间戳>/ 里
    - page_source.html    完整页面源码
    - report.txt          class 采样、video/iframe 清单、候选小节元素
'''
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import refresh_cookie
from selenium.webdriver.common.by import By

refresh_cookie.setup_output()
refresh_cookie.bypass_proxy_for_localhost()


def main():
    if len(sys.argv) < 2:
        print('用法: python tools/probe_site.py <课程网址>')
        print('例:   python tools/probe_site.py "https://ai-smart-course-student-pro.zhihuishu.com/learnPage/..."')
        return 1
    url = sys.argv[1]
    if not url.startswith('http'):
        print('网址必须以 http(s):// 开头')
        return 1

    from selenium import webdriver
    print('启动可见浏览器窗口（请用已经登录该站点的浏览器环境）...')
    try:
        from selenium.webdriver.edge.options import Options as EdgeOptions
        opt = EdgeOptions()
        driver = webdriver.Edge(options=opt)
    except Exception:
        driver = webdriver.Chrome()

    out_dir = os.path.join(
        refresh_cookie.app_dir(),
        '_probe_' + url.split('//', 1)[-1].split('/')[0].replace('.', '_') + '_' + time.strftime('%Y%m%d_%H%M%S'),
    )
    os.makedirs(out_dir, exist_ok=True)

    try:
        driver.maximize_window()
        driver.set_page_load_timeout(60)
        try:
            driver.get(url)
        except Exception:
            pass
        input('\n页面打开后：如果没登录先扫码登录、点进课程学习页，然后回到这里按回车开始采集... ')

        # 完整源码
        with open(os.path.join(out_dir, 'page_source.html'), 'w', encoding='utf-8') as f:
            f.write(driver.page_source)

        lines = []
        lines.append(f'URL: {driver.current_url}')
        lines.append(f'标题: {driver.title}')
        lines.append('')

        # class 采样
        counts = Counter()
        for el in driver.find_elements(By.XPATH, '//*[@class]'):
            for c in (el.get_attribute('class') or '').split():
                counts[c] += 1
        lines.append('== 出现最多的 class（前 40）==')
        for k, v in counts.most_common(40):
            lines.append(f'  {k}x{v}')
        lines.append('')

        # video / iframe 清单
        vids = driver.find_elements(By.TAG_NAME, 'video')
        lines.append(f'== video 元素: {len(vids)} 个 ==')
        for i, v in enumerate(vids[:10]):
            lines.append(f'  [{i}] id={v.get_attribute("id")} class={v.get_attribute("class")} src={(v.get_attribute("src") or "")[:100]}')
        frames = driver.find_elements(By.TAG_NAME, 'iframe')
        lines.append(f'== iframe 元素: {len(frames)} 个 ==')
        for i, fr in enumerate(frames[:10]):
            lines.append(f'  [{i}] id={fr.get_attribute("id")} src={(fr.get_attribute("src") or "")[:120]}')
        lines.append('')

        # 常见小节候选选择器的命中数
        candidates = [
            '.study-unit', '.leaf-detail', '.clearfix.video', '.resources-item',
            '.child-main', '.chapter-content-second', '.source-icon', '.job',
            'li[data-id]', '.task-item', '.chapter_unit',
        ]
        lines.append('== 候选小节选择器命中数 ==')
        for sel in candidates:
            try:
                lines.append(f'  {sel}: {len(driver.find_elements(By.CSS_SELECTOR, sel))}')
            except Exception:
                pass

        report = '\n'.join(lines)
        with open(os.path.join(out_dir, 'report.txt'), 'w', encoding='utf-8') as f:
            f.write(report)
        print(report)
        print(f'\n已保存到: {out_dir}')
    finally:
        input('\n按回车关闭浏览器... ')
        driver.quit()
    return 0


if __name__ == '__main__':
    sys.exit(main())
