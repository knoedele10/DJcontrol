"""当前文稿的预览文件缓存；保留全稿，避免内存上限和短 TTL 导致重复导出。"""

import tempfile
import logging
from collections import OrderedDict
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)


class PptPreviewCache:
    def __init__(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="kgdash-ppt-previews-")).resolve()
        self._files: OrderedDict[tuple, Path] = OrderedDict()

    def get(self, key: tuple) -> bytes | None:
        path = self._files.get(key)
        if path is None:
            return None
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            del self._files[key]
            return None
        self._files.move_to_end(key)
        return content

    def put(self, key: tuple, content: bytes, max_entries: int) -> None:
        path = self._files.get(key)
        if path is None:
            path = self.directory / f"{uuid4().hex}.png"
        path.write_bytes(content)
        self._files[key] = path
        self._files.move_to_end(key)
        # 至少容纳整份文稿；额外空间留给手动刷新及兼容尺寸。
        while len(self._files) > max_entries:
            _, old_path = self._files.popitem(last=False)
            old_path.unlink(missing_ok=True)

    def clear(self) -> None:
        for path in self._files.values():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # Windows 上可能有杀毒软件或预览进程短暂持有文件；不能阻断服务关闭。
                logger.warning("删除 PPT 预览缓存失败：%s", path, exc_info=True)
        self._files.clear()

    def close(self) -> None:
        self.clear()
        # 仅删除本实例创建且已经清空的目录，不递归删除其他文件。
        try:
            self.directory.rmdir()
        except OSError:
            logger.warning("删除 PPT 预览缓存目录失败：%s", self.directory, exc_info=True)
