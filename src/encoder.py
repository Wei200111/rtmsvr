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
    
    # 2. 编码Header
    msg_id = 0x02
    length = 15 + len(body) + 4  # Header(15B) + Body + Tail(4B)
    week, sow = utc2gps(data['time'])
    interval = 15  # 建模间隔15分钟
    
    header = struct.pack(
        '>HBHHIHBx',
        0x01AA,       # 魔数
        msg_id,       # 消息ID
        length,       # 帧长度
        week,         # GPS周
        sow,          # 秒数SOW
        interval,     # 建模间隔
        iod           # IOD（绑定数据内容）
    )
    
    # 3. 计算CRC（从消息ID到Body结束）
    crc_data = header[2:] + body  # 跳过魔数
    checksum = crc16(crc_data)
    
    # 4. 编码Tail
    tail = struct.pack('>HH', checksum, 0x00FF)
    
    return header + body + tail


def _encode_body(data: Dict[str, Any]) -> bytes:
    """编码Body部分
    
    Body结构:
    - U8 model_type=0
    - I32 base_radius（米）
    - I32 ref_height（米）
    - U32 coef_count
    - I32[coef_count] coefficients
    - I32 lat1, lat2, dlat（微度）
    - I32 lon1, lon2, dlon（微度）
    - U16 grid_total（验证用）
    - U8[] rms_compressed（两个4-bit索引打包为1字节）
    """
    body = bytearray()
    
    # 1. Model type
    body.extend(struct.pack('>B', 0))
    
    # 2. Model parameters（添加epsilon避免截断误差）
    base_r_m = int(data['base_r'] * 1000 + 1e-9)
    hgt_m = int(data['hgt'] * 1000 + 1e-9)
    body.extend(struct.pack('>ii', base_r_m, hgt_m))
    
    # 3. Coefficients（TECU → 0.001 TECU整数）
    coef_cnt = data['coef_cnt']
    body.extend(struct.pack('>I', coef_cnt))
    
    coefs_int = []
    for c in data['coefs']:
        # 转换为0.001 TECU单位，添加epsilon避免截断
        val = c * 1000
        if val >= 0:
            val = int(val + 1e-9)
        else:
            val = int(val - 1e-9)
        coefs_int.append(val)
    
    body.extend(struct.pack(f'>{coef_cnt}i', *coefs_int))
    
    # 4. Grid definition（度 → 微度）
    lat1, lat2, dlat = data['lat']
    lon1, lon2, dlon = data['lon']
    
    # 对每个值添加epsilon避免截断，注意符号
    # GIM格式中纬度从北向南，dlat为负值，但协议中间隔应使用绝对值
    lat1_udeg = int(lat1 * 1e6 + (1e-9 if lat1 >= 0 else -1e-9))
    lat2_udeg = int(lat2 * 1e6 + (1e-9 if lat2 >= 0 else -1e-9))
    dlat_udeg = int(abs(dlat) * 1e6 + 1e-9)  # 使用绝对值
    lon1_udeg = int(lon1 * 1e6 + (1e-9 if lon1 >= 0 else -1e-9))
    lon2_udeg = int(lon2 * 1e6 + (1e-9 if lon2 >= 0 else -1e-9))
    dlon_udeg = int(abs(dlon) * 1e6 + 1e-9)  # 使用绝对值
    
    body.extend(struct.pack('>iiiiii', 
                           lat1_udeg, lat2_udeg, dlat_udeg,
                           lon1_udeg, lon2_udeg, dlon_udeg))
    
    # 5. Compress RMS
    rms_matrix = data['rms']
    rms_compressed = _compress_rms(rms_matrix)
    
    # 6. Grid total（验证用）
    total_points = len(rms_compressed) * 2  # 每字节包含2个点
    # 如果总点数为奇数，最后一个字节只有高4位有效
    if len(rms_matrix) > 0 and len(rms_matrix[0]) > 0:
        nlat = len(rms_matrix)
        nlon = len(rms_matrix[0])
        total_points = nlat * nlon
    
    body.extend(struct.pack('>H', total_points))
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
