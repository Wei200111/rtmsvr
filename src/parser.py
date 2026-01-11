# parser.py - INX文件解析器

import re
from datetime import datetime
from typing import Dict, List, Tuple, Any


def parse_inx(path: str) -> Dict[str, Any]:
    """解析INX文件，提取模型参数和RMS数据
    
    Args:
        path: INX文件路径
    
    Returns:
        {
            'time': datetime,           # EPOCH OF CURRENT MAP
            'order': (N, M),            # 阶数
            'coef_cnt': int,            # 从"Total coefficients"读取
            'coefs': [float],           # 系数列表（按文件顺序）
            'base_r': float,            # 地球半径 6371 km
            'hgt': float,               # 参考高 450 km
            'lat': (lat1, lat2, dlat),  # 纬度范围
            'lon': (lon1, lon2, dlon),  # 经度范围
            'rms': [[int]],             # RMS矩阵（单位0.1TECU）
        }
    """
    result = {
        'time': None,
        'order': (0, 0),
        'coef_cnt': 0,
        'coefs': [],
        'base_r': 6371.0,
        'hgt': 450.0,
        'lat': (55.0, 25.0, -1.0),
        'lon': (95.0, 135.0, 1.0),
        'rms': [],
        'interval': 900  # 默认15分钟（单位：秒）
    }
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        # 尝试latin-1编码
        with open(path, 'r', encoding='latin-1') as f:
            lines = f.readlines()
    except FileNotFoundError:
        raise FileNotFoundError(f'INX文件不存在: {path}')
    
    i = 0
    in_header = False
    while i < len(lines):
        line = lines[i].strip()
        
        # 检测Header区域
        if 'IONEX VERSION' in line or 'END OF HEADER' not in ''.join(lines[:i+1]):
            in_header = True
        elif 'END OF HEADER' in line:
            in_header = False
        
        # 解析BASE RADIUS (仅在Header中)
        if in_header and 'BASE RADIUS' in line:
            result['base_r'] = float(line.split()[0])
        
        # 解析HGT1 (仅在Header中)
        elif in_header and 'HGT1' in line:
            parts = line.split()
            result['hgt'] = float(parts[0])
        
        # 解析LAT范围 (仅在Header中)
        elif in_header and 'LAT1' in line and 'LAT2' in line:
            parts = line.split()
            result['lat'] = (float(parts[0]), float(parts[1]), float(parts[2]))
        
        # 解析LON范围 (仅在Header中)
        elif in_header and 'LON1' in line and 'LON2' in line:
            parts = line.split()
            result['lon'] = (float(parts[0]), float(parts[1]), float(parts[2]))
        
        # 解析INTERVAL (仅在Header中)
        elif in_header and 'INTERVAL' in line:
            parts = line.split()
            if parts and parts[0].isdigit():
                result['interval'] = int(parts[0])  # 单位：秒
        
        # 解析COEFFICIENTS块
        elif 'COEFFICIENTS START' in line:
            i += 1
            # 读取Order和Total coefficients
            while i < len(lines):
                line = lines[i].strip()
                if 'Order:' in line and 'Total coefficients:' in line:
                    # 例如: "Order: 2 x 2, Total coefficients: 9"
                    match = re.search(r'Order:\s*(\d+)\s*x\s*(\d+).*Total coefficients:\s*(\d+)', line)
                    if match:
                        result['order'] = (int(match.group(1)), int(match.group(2)))
                        result['coef_cnt'] = int(match.group(3))
                    i += 1
                elif 'MAP' in line and 'COEF' in line:
                    # 读取时间: MAP 1 COEF 2025 11 18 16 0 0
                    parts = line.split()
                    if len(parts) >= 9:
                        year, month, day, hour, minute, second = map(int, parts[3:9])
                        result['time'] = datetime(year, month, day, hour, minute, second)
                    i += 1
                    # 读取系数
                    coef_lines = []
                    while i < len(lines) and 'COEFFICIENTS END' not in lines[i]:
                        coef_line = lines[i].strip()
                        # 跳过注释行和包含非数字内容的行
                        if coef_line and not coef_line.startswith('*'):
                            # 只提取数字部分（排除"COEFFICIENT DATA"等文本）
                            # 提取所有浮点数
                            numbers = []
                            for token in coef_line.split():
                                try:
                                    numbers.append(float(token))
                                except ValueError:
                                    # 跳过非数字token（如"COEFFICIENT"）
                                    pass
                            if numbers:
                                coef_lines.extend(numbers)
                        i += 1
                    # 系数已经是float列表
                    result['coefs'] = coef_lines
                    break
                else:
                    i += 1
        
        # 解析RMS MAP块
        elif 'START OF RMS MAP' in line:
            i += 1
            rms_data = []
            while i < len(lines) and 'END OF RMS MAP' not in lines[i]:
                line = lines[i].strip()
                # 跳过EPOCH行
                if 'EPOCH OF CURRENT MAP' in line:
                    i += 1
                    continue
                # 检测纬度行（包含LAT/LON标记）
                if 'LAT/LON' in line:
                    i += 1
                    # 读取该纬度的所有RMS数值（可能跨多行，直到下一个LAT/LON行）
                    rms_values = []
                    while i < len(lines) and 'END OF RMS MAP' not in lines[i]:
                        rms_line = lines[i].strip()
                        # 遇到下一个纬度行则停止
                        if 'LAT/LON' in rms_line:
                            break
                        # 读取RMS数值行
                        if rms_line and not rms_line.startswith('*') and 'EPOCH' not in rms_line:
                            try:
                                # RMS值直接读取（文件中已是0.1 TECU单位的整数）
                                rms_values.extend([int(x) for x in rms_line.split()])
                            except ValueError:
                                # 跳过无法解析的行
                                pass
                        i += 1
                    if rms_values:
                        rms_data.append(rms_values)
                else:
                    i += 1
            result['rms'] = rms_data
            break
        
        i += 1
    
    return result
