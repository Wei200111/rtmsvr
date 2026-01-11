# tcpcmn.py - 通用工具函数

import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple

# GPS时间常量
GPS_EPOCH = datetime(1980, 1, 6, 0, 0, 0)

# GPS-UTC闰秒表（从1980年至今的累积闰秒，来源：IERS公告）
# 格式：(生效日期, GPS-UTC闰秒数)
LEAP_SECOND_TABLE = [
    (datetime(1981, 7, 1), 1),
    (datetime(1982, 7, 1), 2),
    (datetime(1983, 7, 1), 3),
    (datetime(1985, 7, 1), 4),
    (datetime(1988, 1, 1), 5),
    (datetime(1990, 1, 1), 6),
    (datetime(1991, 1, 1), 7),
    (datetime(1992, 7, 1), 8),
    (datetime(1993, 7, 1), 9),
    (datetime(1994, 7, 1), 10),
    (datetime(1996, 1, 1), 11),
    (datetime(1997, 7, 1), 12),
    (datetime(1999, 1, 1), 13),
    (datetime(2006, 1, 1), 14),
    (datetime(2009, 1, 1), 15),
    (datetime(2012, 7, 1), 16),
    (datetime(2015, 7, 1), 17),
    (datetime(2017, 1, 1), 18),
    # 2017年之后IERS未再公布新闰秒（截至2026年）
    # 如有更新请在此添加新记录
]


def get_leap_seconds(dt: datetime) -> int:
    """根据UTC时间查询GPS-UTC闰秒数
    
    Args:
        dt: UTC datetime对象
    
    Returns:
        对应时刻的GPS-UTC闰秒数
    """
    leap_sec = 0
    for date, leap in LEAP_SECOND_TABLE:
        if dt >= date:
            leap_sec = leap
        else:
            break
    return leap_sec


def load_cfg(path: str = "config/bcast.json") -> Dict[str, Any]:
    """加载并校验配置文件
    
    Args:
        path: 配置文件路径
    
    Returns:
        配置字典
    
    Raises:
        FileNotFoundError: 文件不存在
        json.JSONDecodeError: JSON格式错误
    """
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    # 基础校验
    assert cfg['tcp_server']['port'] > 0, "Invalid port"
    assert cfg['broadcast']['interval_seconds'] > 0, "Invalid interval"
    
    return cfg


def utc2gps(dt: datetime) -> Tuple[int, int]:
    """UTC时间转GPS Week/SOW（动态查询闰秒）
    
    Args:
        dt: UTC datetime对象
    
    Returns:
        (gps_week, gps_sow) - SOW为整数秒
    """
    leap_sec = get_leap_seconds(dt)
    gps_dt = dt + timedelta(seconds=leap_sec)
    delta = gps_dt - GPS_EPOCH
    week = delta.days // 7
    sow = (delta.days % 7) * 86400 + delta.seconds
    return week, sow


def crc16(data: bytes) -> int:
    """CRC-16/XMODEM校验（多项式0x1021）
    
    Args:
        data: 待校验数据
    
    Returns:
        CRC值（0x0000-0xFFFF）
    """
    crc = 0x0000
    poly = 0x1021
    
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ poly
            else:
                crc <<= 1
            crc &= 0xFFFF
    
    return crc


def init_log(cfg: dict) -> logging.Logger:
    """初始化文件+控制台双重日志
    
    Args:
        cfg: 配置字典（包含 logging 配置）
    
    Returns:
        Logger对象
    """
    log_cfg = cfg.get('logging', {})
    level = getattr(logging, log_cfg.get('level', 'INFO'))
    
    # 文件日志
    file_handler = logging.FileHandler(
        log_cfg.get('file', 'logs/bcast.log'),
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    
    # 控制台日志
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # 格式
    fmt = '%(asctime)s [%(levelname)s] %(message)s'
    formatter = logging.Formatter(fmt)
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 配置
    logger = logging.getLogger('bcast')
    logger.setLevel(level)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def rms2idx(rms_tecu: float) -> int:
    """RMS值(TECU) → 4-bit索引(0-15)
    
    Args:
        rms_tecu: RMS值（单位TECU）
    
    Returns:
        索引（0-15）
    """
    bounds = [0, 0.6, 1.2, 1.8, 2.4, 3.0, 3.6, 4.2, 4.8, 5.4, 6.0, 6.6, 7.2, 7.8, 8.4, 9.0]
    for i in range(15):
        if rms_tecu < bounds[i+1]:
            return i
    return 15  # ≥9.0 TECU
