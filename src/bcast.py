# bcast.py - 播发管理器（IOD绑定数据内容）

import logging
import hashlib
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
from threading import Thread, Event

from src.parser import parse_inx
from src.encoder import encode_frame
from src.tcpsvr import TcpServer


class Broadcaster:
    """广播管理器
    
    IOD语义（重要）:
    - IOD必须绑定数据内容，而非发送次数
    - 同一文件重复播发时，IOD保持不变
    - 只有数据内容真正变化时，IOD才递增
    - 使用文件哈希作为内容标识
    
    文件保存功能（类似rtkrcv）:
    - 支持时间格式路径: %Y年 %m月 %d日 %h时 %M分 %S秒
    - 支持定时切换: ::S=24 表示24小时换文件
    - 示例: output/vtec_%Y%m%d_%h%M.bin::S=1 (每小时换文件)
    """
    
    def __init__(self, tcpsvr: TcpServer, interval: float = 10.0, 
                 save_path: Optional[str] = None):
        """初始化播发管理器
        
        Args:
            tcpsvr: TCP服务器实例
            interval: 播发间隔（秒）
            save_path: 保存路径（支持时间格式和::S=N切换），例如:
                      "output/vtec_%Y%m%d_%h%M.bin::S=1"  # 每小时换文件
                      "output/data_%Y%m%d.bin::S=24"      # 每天换文件
        """
        self.tcpsvr = tcpsvr
        self.interval = interval
        self.save_path_template = save_path
        self.swap_interval_hours = None  # 文件切换间隔（小时）
        
        self.save_file = None
        self.current_save_path: Optional[Path] = None
        self.last_swap_time: Optional[datetime] = None
        
        self.current_file: Optional[Path] = None
        self.current_data: Optional[Dict] = None
        self.current_iod: int = 0
        self.content_hash: Optional[str] = None
        
        self.thread: Optional[Thread] = None
        self.stop_event = Event()
        self.log = logging.getLogger('Broadcaster')
        
        # 解析保存路径和切换参数（必须在self.log初始化之后）
        if save_path:
            self._parse_save_path(save_path)
    
    def _parse_save_path(self, path_str: str):
        """解析保存路径配置
        
        支持格式: path::S=N
        其中N为小时数，例如::S=24表示24小时换一次文件
        """
        parts = path_str.split('::')
        self.save_path_template = parts[0]
        
        if len(parts) > 1:
            # 解析切换参数 S=N
            match = re.search(r'S=(\d+)', parts[1])
            if match:
                self.swap_interval_hours = int(match.group(1))
                self.log.info(f"文件切换间隔: {self.swap_interval_hours} 小时")
    
    def _format_save_path(self, dt: Optional[datetime] = None) -> Path:
        """根据时间格式化保存路径
        
        Args:
            dt: 时间（默认当前时间）
            
        Returns:
            格式化后的路径
        """
        if not self.save_path_template:
            return None
        
        if dt is None:
            dt = datetime.now()
        
        # 替换时间占位符
        path_str = self.save_path_template
        path_str = path_str.replace('%Y', dt.strftime('%Y'))
        path_str = path_str.replace('%m', dt.strftime('%m'))
        path_str = path_str.replace('%d', dt.strftime('%d'))
        path_str = path_str.replace('%h', dt.strftime('%H'))
        path_str = path_str.replace('%M', dt.strftime('%M'))
        path_str = path_str.replace('%S', dt.strftime('%S'))
        
        return Path(path_str)
    
    def _should_swap_file(self) -> bool:
        """判断是否需要切换文件"""
        if not self.swap_interval_hours:
            return False
        
        if not self.last_swap_time:
            return True
        
        now = datetime.now()
        elapsed_hours = (now - self.last_swap_time).total_seconds() / 3600
        
        return elapsed_hours >= self.swap_interval_hours
    
    def _open_save_file(self):
        """打开或切换保存文件"""
        if not self.save_path_template:
            return
        
        # 关闭旧文件
        if self.save_file:
            self.save_file.close()
            self.log.info(f"关闭文件: {self.current_save_path}")
        
        # 生成新文件路径
        new_path = self._format_save_path()
        
        # 创建目录
        new_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 打开新文件
        self.save_file = open(new_path, 'wb')
        self.current_save_path = new_path
        self.last_swap_time = datetime.now()
        
        self.log.info(f"打开新文件: {new_path}")
    
    def set_file(self, filepath: Path):
        """设置待播发文件（检查内容是否变化）
        
        Args:
            filepath: INX文件路径
        """
        # 计算文件哈希（内容标识）
        new_hash = self._compute_hash(filepath)
        
        if new_hash != self.content_hash:
            # 内容变化，更新IOD
            self.current_iod = (self.current_iod + 1) % 256
            self.content_hash = new_hash
            self.log.info(f'检测到新内容，IOD更新为 {self.current_iod}')
        else:
            self.log.debug(f'内容未变化，IOD保持 {self.current_iod}')
        
        # 解析文件
        try:
            self.current_data = parse_inx(str(filepath))
            self.current_file = filepath
            self.log.info(f'加载文件: {filepath.name}, IOD={self.current_iod}')
        except Exception as e:
            self.log.error(f'解析文件失败: {e}')
    
    def _compute_hash(self, filepath: Path) -> str:
        """计算文件内容哈希（用于IOD绑定）
        
        Args:
            filepath: 文件路径
        
        Returns:
            SHA256哈希值
        """
        try:
            with open(filepath, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            self.log.error(f'计算哈希失败: {e}')
            return ''
    
    def start(self):
        """启动定时播发线程"""
        if self.thread and self.thread.is_alive():
            self.log.warning('播发线程已在运行')
            return
        
        self.stop_event.clear()
        self.thread = Thread(target=self._broadcast_loop, daemon=True)
        self.thread.start()
        self.log.info(f'播发线程启动，间隔 {self.interval} 秒')
    
    def _broadcast_loop(self):
        """播发循环（每隔interval秒发送一次）"""
        # 首次打开文件
        if self.save_path_template and not self.save_file:
            self._open_save_file()
        
        while not self.stop_event.is_set():
            try:
                # 检查是否需要切换文件
                if self._should_swap_file():
                    self._open_save_file()
                
                # 接受新客户端
                self.tcpsvr.accept_clients()
                
                # 播发数据
                if self.current_data:
                    frame = encode_frame(self.current_data, self.current_iod)
                    
                    # 保存到文件
                    if self.save_file:
                        self.save_file.write(frame)
                        self.save_file.flush()
                    
                    sent = self.tcpsvr.broadcast(frame)
                    
                    if sent > 0:
                        self.log.info(f'播发成功: {len(frame)} 字节 → {sent} 客户端, IOD={self.current_iod}')
                    else:
                        self.log.debug(f'无客户端连接，跳过播发')
                else:
                    self.log.debug('无数据，跳过播发')
                
            except Exception as e:
                self.log.error(f'播发异常: {e}')
            
            # 等待下一个周期
            self.stop_event.wait(self.interval)
    
    def stop(self):
        """停止播发线程"""
        self.log.info('正在停止播发线程...')
        self.stop_event.set()
        
        if self.thread:
            self.thread.join(timeout=5.0)
        
        # 关闭保存文件
        if self.save_file:
            self.save_file.close()
            self.log.info(f'已关闭保存文件: {self.current_save_path}')
        
        self.log.info('播发线程已停止')
