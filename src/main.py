# main.py - 主程序入口

import sys
import signal
import logging
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tcpcmn import load_cfg, init_log
from src.tcpsvr import TcpServer
from src.bcast import Broadcaster
from src.watcher import FileWatcher


def main():
    """主程序"""
    # 1. 加载配置
    # 获取脚本所在目录的父目录
    base_dir = Path(__file__).parent.parent
    cfg_path = base_dir / 'config' / 'bcast.json'
    if not cfg_path.exists():
        print(f'错误: 配置文件不存在 {cfg_path}')
        sys.exit(1)
    
    try:
        cfg = load_cfg(str(cfg_path))
    except Exception as e:
        print(f'配置文件加载失败: {e}')
        sys.exit(1)
    
    # 2. 确保日志目录存在
    log_file = cfg.get('logging', {}).get('file', 'logs/bcast.log')
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 3. 初始化日志
    log = init_log(cfg)
    log.info('=' * 60)
    log.info('RTVM广播系统启动')
    log.info('=' * 60)
    
    # 4. 创建TCP服务器
    tcp_cfg = cfg['tcp_server']
    tcpsvr = TcpServer(
        host=tcp_cfg['host'],
        port=tcp_cfg['port'],
        max_clients=tcp_cfg.get('max_clients', 10)
    )
    
    try:
        tcpsvr.start()
    except Exception as e:
        log.error(f'TCP服务器启动失败: {e}')
        sys.exit(1)
    
    # 5. 创建播发管理器
    bcast_cfg = cfg['broadcast']
    
    # 设置保存路径（支持时间格式和定时切换）
    save_path = bcast_cfg.get('save_path', None)
    if save_path:
        log.info(f'播发数据保存路径: {save_path}')
    
    broadcaster = Broadcaster(
        tcpsvr=tcpsvr,
        interval=bcast_cfg['interval_seconds'],
        save_path=save_path
    )
    
    # 6. 创建文件监控器
    watch_cfg = cfg['file_watcher']
    watcher = FileWatcher(
        watch_dir=watch_cfg['watch_dir'],
        callback=broadcaster.set_file,
        pattern=watch_cfg['file_pattern']
    )
    
    try:
        watcher.start()
    except Exception as e:
        log.error(f'文件监控启动失败: {e}')
        tcpsvr.stop()
        sys.exit(1)
    
    # 7. 加载初始文件（最新的.inx文件）
    watch_dir = Path(watch_cfg['watch_dir'])
    if watch_dir.exists():
        inx_files = sorted(watch_dir.glob(watch_cfg['file_pattern']))
        if inx_files:
            latest_file = inx_files[-1]
            log.info(f'加载初始文件: {latest_file.name}')
            broadcaster.set_file(latest_file)
        else:
            log.warning(f'监控目录中未找到.inx文件')
    
    # 8. 启动播发线程
    broadcaster.start()
    
    # 8. 注册信号处理（优雅退出）
    def signal_handler(sig, frame):
        log.info('收到退出信号，正在关闭...')
        broadcaster.stop()
        watcher.stop()
        tcpsvr.stop()
        log.info('系统已停止')
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 10. 主循环（保持运行）
    log.info('系统运行中，按Ctrl+C退出')
    
    try:
        while True:
            signal.pause()  # 等待信号
    except AttributeError:
        # Windows不支持signal.pause()，使用Thread.join()
        import threading
        event = threading.Event()
        event.wait()


if __name__ == '__main__':
    main()
