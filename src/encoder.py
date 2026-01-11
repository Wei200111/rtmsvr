# encoder.py - 二进制协议编码器

import struct
from typing import List, Dict, Any
from src.tcpcmn import crc16, utc2gps, rms2idx


def encode_frame(data: Dict[str, Any], iod: int) -> bytes:
    """将模型数据编码为二进制帧
    
    Args:
        data: parse_inx()返回的字典
        iod: IOD计数器（绑定数据内容，非发送次数）
    
    Returns:
        完整二进制帧（Header + Body + Tail）
    """
    # 1. 编码Body部分（用于计算长度）
    body = _encode_body(data)
    
    # 2. 编码Header（严格按照设计文档13字节）
    msg_id = 0x02
    length = 13 + len(body) + 4  # Header(13B) + Body + Tail(4B)
    week, sow = utc2gps(data['time'])
    sow = int(sow * 1000)  # 单位0.001秒，需乘1000
    interval = data.get('interval', 900) // 60  # 从data读取（秒）转换为分钟
    
    header = struct.pack(
        '>HBHHIBB',
        0x01AA,       # 魔数 2字节
        msg_id,       # 消息ID 1字节
        length,       # 帧长度 2字节
        week,         # GPS周 2字节
        sow,          # GPS秒 4字节
        interval,     # 建模间隔 1字节
        iod           # IOD 1字节
    )
    
    # 3. 计算CRC（从消息ID到Body结束）
    crc_data = header[2:] + body  # 跳过魔数
    checksum = crc16(crc_data)
    
    # 4. 编码Tail
    tail = struct.pack('>HH', checksum, 0x00FF)
    
    return header + body + tail


def _encode_body(data: Dict[str, Any]) -> bytes:
    """编码Body部分(严格按照设计文档)
    
    Body结构:
    - U16 地球半径(km)6371
    - U16 模型参考高(km)450
    - U8  模型代号 0
    - U8  阶数N,M
    - I32[K] 系数列表(0.001 TECU)
    - I16 起始经度(0.1度)
    - I16 起始纬度(0.1度)
    - I16 截止经度(0.1度)
    - I16 截止纬度(0.1度)
    - U8  纬度间隔(0.1度)
    - U8  经度间隔(0.1度)
    - U16 网格总数
    - U8[] RMS压缩数据
    """
    body = bytearray()
    
    # 1. 模型参考高和地球半径(U16,单位km) - 按照帧体顺序！
    base_radius = int(data['base_r'] + 0.5)
    ref_height = int(data['hgt'] + 0.5)
    body.extend(struct.pack('>HH', ref_height, base_radius))
    
    # 2. 模型代号(U8,固定0)
    body.extend(struct.pack('>B', 0))
    
    # 3. 阶数(U8,高4位=N,低4位=M)
    # 直接使用parser.py解析的order字段
    N, M = data['order']
    order_byte = (N << 4) | M
    body.extend(struct.pack('>B', order_byte))
    
    coef_cnt = data['coef_cnt']
    
    # 4. 系数列表(I32,单位0.001 TECU)
    coefs_int = []
    for c in data['coefs']:
        val = c * 1000
        if val >= 0:
            val = int(val + 1e-9)
        else:
            val = int(val - 1e-9)
        coefs_int.append(val)
    
    body.extend(struct.pack(f'>{coef_cnt}i', *coefs_int))
    
    # 5. 网格定义(I16x4 + U8x2,单位0.1度)
    lat1, lat2, dlat = data['lat']
    lon1, lon2, dlon = data['lon']
    
    lon1_d1 = int(lon1 * 10 + (0.5 if lon1 >= 0 else -0.5))
    lat1_d1 = int(lat1 * 10 + (0.5 if lat1 >= 0 else -0.5))
    lon2_d1 = int(lon2 * 10 + (0.5 if lon2 >= 0 else -0.5))
    lat2_d1 = int(lat2 * 10 + (0.5 if lat2 >= 0 else -0.5))
    
    dlat_d1 = int(abs(dlat) * 10 + 0.5)
    dlon_d1 = int(abs(dlon) * 10 + 0.5)
    
    body.extend(struct.pack('>hhhhBB', 
                           lon1_d1, lat1_d1, lon2_d1, lat2_d1,
                           dlat_d1, dlon_d1))
    
    # 6. 网格总数(U16)
    rms_matrix = data['rms']
    if len(rms_matrix) > 0 and len(rms_matrix[0]) > 0:
        nlat = len(rms_matrix)
        nlon = len(rms_matrix[0])
        total_points = nlat * nlon
    else:
        total_points = 0
    
    body.extend(struct.pack('>H', total_points))
    
    # 7. RMS压缩数据
    rms_compressed = _compress_rms(rms_matrix)
    body.extend(rms_compressed)
    
    return bytes(body)


def _compress_rms(rms: List[List[int]]) -> bytes:
    """压缩RMS矩阵为字节流
    
    扫描顺序: 纬度优先（55→25降序），经度递增（95→135）
    编码方式: 高4位=点N，低4位=点N+1
    
    Args:
        rms: RMS矩阵（单位0.1 TECU整数）
    
    Returns:
        压缩后的字节流
    """
    compressed = bytearray()
    indices = []
    
    # 纬度降序扫描
    for row in rms:
        for val in row:
            # RMS值单位是0.1 TECU，除以10转换成TECU
            rms_tecu = val / 10.0
            idx = rms2idx(rms_tecu)
            indices.append(idx)
    
    # 打包为字节（两个4-bit索引）
    for i in range(0, len(indices), 2):
        high = indices[i]
        low = indices[i + 1] if i + 1 < len(indices) else 0
        byte = (high << 4) | low
        compressed.append(byte)
    
    return bytes(compressed)
