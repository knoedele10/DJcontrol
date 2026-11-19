"""只匹配真机验证过的精确版本，更新后默认关闭操作能力。"""

import re
import unicodedata

VERSION = "10.2.52.25713"
PROFILE = "kugou-10.2.52.25713"
MAIN_CLASS = "kugou_ui"
SUFFIX = " - 酷狗音乐"
MEDIA_KEYS = {"toggle": 0xB3, "media_next": 0xB0, "media_previous": 0xB1}
# 播放栏"进度"滑块的 RangeValue 单位：真机连续采样为每秒 100（百分之一秒），最大值即歌曲时长。
POSITION_UNITS_PER_SECOND = 100
# 搜索结果页是画出来的，只能按位置点。坐标相对"内嵌页"左上角，在搜索框高 48 像素（150% 缩放）时量得，
# 其他缩放按搜索框高度等比换算。first_song 点在第一行歌名和歌手之间的空白处，不会点到链接。
SEARCH_LAYOUT = {"search_box_height": 48, "songs_tab": (200, 43), "first_song": (560, 261),
                 "rows": (100, 620), "results_wait": 6.0, "songs_wait": 3.0, "play_wait": 12.0}

# 歌单使用实际 UIA 矩形，不猜测歌曲位置。B 路线的坐标必须真机测量后才可填写。
# 酷狗 10.2.52 真机结构（2026-11-18）：左侧导航 List「导航」只在顶部「音乐」页出现，项名是完整歌单名；
# 歌单页的歌曲在 List「单曲」里。两个列表都没有 ScrollPattern，只能投递滚轮；滚出视口的项名字为空。
# edge_margin：列表下沿被播放栏进度条压住的高度；点击只落在避开这一条的部分。
# wait：播放时定位歌单的上限；inspect_wait：检测（部分名称要把侧栏读完一遍）；play_wait：双击后核验播放；
# add_wait：加歌对话框；load_wait：歌单页刚打开时等歌曲出现。
PLAYLIST_LAYOUT = {"wait": 14.0, "inspect_wait": 24.0, "play_wait": 10.0, "add_wait": 14.0, "load_wait": 4.0,
                   "filter_wait": 1.0, "search_box_height": 48, "first_song": None,
                   "music_tab": "音乐", "nav_list": "导航", "own_header": "自建歌单", "song_lists": ("单曲",),
                   "nav_fixed": ("我的收藏", "我的频道", "本地与下载", "音乐云盘", "已购音乐", "最近播放", "默认列表",
                                 "自建歌单", "收藏歌单"),
                   "edge_margin": 12, "scan_notches": 3, "row_blank_right": 0.025, "wheel_start": 0.6, "wheel_poll": 0.05,
                   "filter_names": ("歌单内搜索", "搜索歌单", "搜索本歌单", "搜索歌曲", "搜索"),
                   "empty_names": ("暂无歌曲", "没有找到相关歌曲", "没有搜索结果", "无搜索结果"),
                   "empty_playlist_names": ("暂无歌曲", "这里没内容显示~"),
                   "title_headers": ("歌曲", "歌曲名", "歌曲名称", "歌名"),
                   "artist_headers": ("歌手", "歌手名", "歌手名称")}
PLAYLIST_ADD_SOFT_TIMEOUT = 43
PLAYLIST_ADD_TIMEOUT = 48


def exact_track(got_title: str, got_artist: str, title: str, artist: str) -> bool:
    """歌单/加歌使用完整曲名，不把 Live、伴奏等版本后缀省略；歌手集合需一致。"""
    wanted_title = _exact_text(title)
    wanted_singers = _exact_singers(artist)
    return bool(wanted_title and wanted_singers and wanted_title == _exact_text(got_title)
                and wanted_singers == _exact_singers(got_artist))


def _exact_text(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def _exact_singers(value: str) -> set[str]:
    return set(filter(None, re.split(r"[、,/&;]", _exact_text(value))))


def match(version: str | None) -> str | None:
    return PROFILE if version == VERSION else None


def parse_title(title: str) -> tuple[str, str]:
    text = title.strip()
    if not text.endswith(SUFFIX):
        return "", ""
    text = text[:-len(SUFFIX)]
    artist, separator, song = text.partition(" - ")
    return (song, artist) if separator else (text, "")


def _plain(text: str) -> str:
    # NFKC 把全角字母数字（如酷狗里的「ＴＲＡ＄Ｈ」）折成半角，再忽略大小写和标点空格。
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).casefold() if ch.isalnum())


def same_track(got_title: str, got_artist: str, title: str, artist: str) -> bool:
    """酷狗标题里的歌是不是要播的这首：歌名要包含在内，歌手有任意一位对上即可（合唱、Live 版写法不一）。"""

    want = _plain(title)
    if not want or want not in _plain(got_title):
        return False
    singers = [name for name in map(_plain, re.split(r"[、,，/&;；]", artist)) if name]
    # 歌手要出现在歌手栏，或歌名的括号里（feat. 写法）；歌名正文里带歌手名的多半是别人翻唱。
    shown = _plain(got_artist + "".join(re.findall(r"[(（\[【](.*?)[)）\]】]", got_title)))
    return not singers or any(name in shown for name in singers)
