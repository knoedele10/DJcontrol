"""歌单操作：仅使用能回读的页面和歌曲身份；没有证据时不猜坐标或报告成功。

所有对象仅在 Worker 的 COM 线程使用，父进程只接收可序列化的快照。

酷狗 10.2.52 的真机结构（2026-11-18 探测）：
- 左侧导航只在顶部「音乐」页出现：Pane「导航」→ List「导航」。项名是完整歌单名（界面文字可能被截断），
  没有 ScrollPattern，滚出视口的项名字为空、矩形为零，只能投递鼠标滚轮滚动；UIA 的 Select() 不会让页面跳转。
- 歌单页的标题是 Text「歌单名」；歌曲在 Pane「单曲」→ List「单曲」的 ListItem 里，名字形如
  '<a 歌名>歌名</a>，歌手:甲、乙，专辑:…，时长:02:33'。列表同样只能滚轮滚动，末尾可能残留一行旧内容。
- 页面里有隐藏的 Text「歌单名」和「共 N 首歌曲」，用来确认成员是否读全。
"""

from KugouControl.Track import TrackFailed

from .Add import add_to_playlist, inspect_add
from .Errors import PlaylistMiss, PlaylistUnsupported
from .Page import inspect, open_playlist
from .Playback import play_from_playlist

__all__ = [
    'PlaylistMiss',
    'PlaylistUnsupported',
    'TrackFailed',
    'add_to_playlist',
    'inspect',
    'inspect_add',
    'open_playlist',
    'play_from_playlist',
]
