# watcher.py - 文件监控（基于watchdog）

import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent


class InxFileHandler(FileSystemEventHandler):
    """INX文件事件处理器"""
    
    def __init__(self, callback, pattern: str = '*.inx'):
        """初始化文件处理器
        
        Args:
            callback: 文件变化回调函数 callback(filepath: Path)
            pattern: 文件模式（例如'*.inx'）
        """
        self.callback = callback
        self.pattern = pattern
        self.log = logging.getLogger('InxFileHandler')
    
    def on_created(self, event: FileCreatedEvent):
        """文件创建事件"""
        if not event.is_directory and self._match_pattern(event.src_path):
            self.log.info(f'检测到新文件: {event.src_path}')
            self.callback(Path(event.src_path))
    
    def on_modified(self, event: FileModifiedEvent):
        """文件修改事件"""
        if not event.is_directory and self._match_pattern(event.src_path):
            self.log.info(f'检测到文件修改: {event.src_path}')
            self.callback(Path(event.src_path))
    
    def _match_pattern(self, filepath: str) -> bool:
        """检查文件是否匹配模式
        
        Args:
            filepath: 文件路径
        
        Returns:
            是否匹配
        """
        p = Path(filepath)
        if self.pattern.startswith('*'):
            return p.name.endswith(self.pattern[1:])
        else:
            return p.name == self.pattern


class FileWatcher:
    """文件监控器"""
    
    def __init__(self, watch_dir: str, callback, pattern: str = '*.inx'):
        """初始化文件监控器
        
        Args:
            watch_dir: 监控目录
            callback: 文件变化回调 callback(filepath: Path)
            pattern: 文件模式
        """
        self.watch_dir = Path(watch_dir)
        self.pattern = pattern
        self.callback = callback
        
        self.observer = Observer()
        self.handler = InxFileHandler(callback, pattern)
        self.log = logging.getLogger('FileWatcher')
    
    def start(self):
        """启动监控"""
        if not self.watch_dir.exists():
            self.log.error(f'监控目录不存在: {self.watch_dir}')
            raise FileNotFoundError(f'目录不存在: {self.watch_dir}')
        
        self.observer.schedule(self.handler, str(self.watch_dir), recursive=False)
        self.observer.start()
        self.log.info(f'文件监控启动: {self.watch_dir} (模式: {self.pattern})')
    
    def stop(self):
        """停止监控"""
        self.log.info('正在停止文件监控...')
        self.observer.stop()
        self.observer.join()
        self.log.info('文件监控已停止')
