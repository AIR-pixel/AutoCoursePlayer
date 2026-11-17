'''
站点适配器注册表。

新增站点：在 sites/ 下加一个模块 + 在这里 import 并注册一次。
内核和向导都通过 get_adapter(key) 拿实例，不直接 import 具体站点。
'''
from .yuketang import YuketangAdapter
from .chaoxing import ChaoxingAdapter
from .zhihuishu import ZhihuishuAdapter

# key -> 适配器类。顺序 = 向导里列出的顺序。
_REGISTRY = {
    YuketangAdapter.key: YuketangAdapter,
    ChaoxingAdapter.key: ChaoxingAdapter,
    ZhihuishuAdapter.key: ZhihuishuAdapter,
}


def list_adapters():
    """返回 [(key, name), ...]，供向导列表用。"""
    return [(k, cls.key and cls.name) for k, cls in _REGISTRY.items()]


def get_adapter(key: str):
    """按 key 取适配器实例。未知 key 抛 ValueError。"""
    key = (key or '').strip().lower()
    if key not in _REGISTRY:
        raise ValueError(f'未知站点: {key!r}；可选: {", ".join(_REGISTRY)}')
    return _REGISTRY[key]()


def guess_adapter_key(course_url: str):
    """根据课程 URL 猜站点 key，猜不出返回 None。"""
    for key, cls in _REGISTRY.items():
        inst = cls()
        if inst.match_host(course_url):
            return key
    return None
