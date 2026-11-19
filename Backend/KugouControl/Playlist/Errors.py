"""歌单点播的错误分类，供搜索回退与工作进程共用。"""
from __future__ import annotations

from KugouControl.Track import TrackFailed


class PlaylistMiss(TrackFailed):
    """完整读取或明确空结果证明该歌曲不在歌单内，可安全回退搜索。"""


class PlaylistUnsupported(TrackFailed):
    """尚未尝试播放：当前页面没有可靠定位方式，可沿用搜索。"""
