# tcpsvr.py - TCP服务器（基于rtkrcv的tcpsvr_t设计）

import socket
import select
import logging
from typing import Set
from threading import Lock


class TcpServer:
    """TCP服务器（多客户端广播模式）
    
    参考rtkrcv的tcpsvr_t实现:
    - 非阻塞accept
    - 多客户端列表管理
    - 广播发送（捕获异常防止单客户端故障影响全局）
    """
    
    def __init__(self, host: str, port: int, max_clients: int = 10):
        """初始化TCP服务器
        
        Args:
            host: 绑定地址（"0.0.0.0"监听所有接口）
            port: 端口号
            max_clients: 最大客户端数
        """
        self.host = host
        self.port = port
        self.max_clients = max_clients
        self.sock = None
        self.clients: Set[socket.socket] = set()
        self.lock = Lock()
        self.log = logging.getLogger('TcpServer')
    
    def start(self):
        """启动TCP服务器"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.host, self.port))
            self.sock.listen(self.max_clients)
            self.sock.setblocking(False)  # 非阻塞模式
            self.log.info(f'TCP服务器启动: {self.host}:{self.port}')
        except Exception as e:
            self.log.error(f'启动失败: {e}')
            raise
    
    def accept_clients(self):
        """非阻塞接受新客户端连接（rtkrcv风格）"""
        try:
            readable, _, _ = select.select([self.sock], [], [], 0)
            if readable:
                conn, addr = self.sock.accept()
                conn.setblocking(False)
                
                with self.lock:
                    if len(self.clients) < self.max_clients:
                        self.clients.add(conn)
                        self.log.info(f'新客户端连接: {addr}, 总计 {len(self.clients)} 个')
                    else:
                        self.log.warning(f'拒绝连接（已满）: {addr}')
                        conn.close()
        except BlockingIOError:
            pass
        except Exception as e:
            self.log.error(f'accept异常: {e}')
    
    def broadcast(self, data: bytes) -> int:
        """广播数据到所有客户端
        
        Args:
            data: 二进制帧数据
        
        Returns:
            成功发送的客户端数量
        """
        if not data:
            return 0
        
        sent_count = 0
        disconnected = []
        
        with self.lock:
            for client in self.clients:
                try:
                    client.sendall(data)
                    sent_count += 1
                except BrokenPipeError:
                    self.log.warning(f'客户端断开（BrokenPipe）: {client.getpeername()}')
                    disconnected.append(client)
                except ConnectionResetError:
                    self.log.warning(f'客户端重置（Reset）: {client.getpeername()}')
                    disconnected.append(client)
                except Exception as e:
                    self.log.error(f'发送失败: {e}')
                    disconnected.append(client)
            
            # 清理断开的客户端
            for client in disconnected:
                try:
                    client.close()
                except:
                    pass
                self.clients.discard(client)
        
        if disconnected:
            self.log.info(f'已移除 {len(disconnected)} 个断开客户端，剩余 {len(self.clients)} 个')
        
        return sent_count
    
    def get_client_count(self) -> int:
        """获取当前客户端数量"""
        with self.lock:
            return len(self.clients)
    
    def stop(self):
        """停止TCP服务器"""
        self.log.info('正在关闭TCP服务器...')
        
        with self.lock:
            for client in self.clients:
                try:
                    client.close()
                except:
                    pass
            self.clients.clear()
        
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        
        self.log.info('TCP服务器已关闭')
