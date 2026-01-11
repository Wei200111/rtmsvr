#!/usr/bin/env python3
"""TCP接收和解码测试脚本

用途：
1. 连接到播发服务器
2. 实时接收二进制帧数据
3. 解码并显示帧内容
4. 对比原始INX文件验证正确性
"""

import sys
import socket
import struct
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tcpcmn import crc16, LEAP_SECOND_TABLE
from src.parser import parse_inx


def decode_frame(data: bytes) -> Optional[Dict[str, Any]]:
    """解码二进制帧
    
    Args:
        data: 二进制帧数据
        
    Returns:
        解码后的字典，包含所有字段；失败返回None
    """
    if len(data) < 19:
        print(f"  ✗ 帧太短: {len(data)} 字节")
        return None
    
    result = {}
    offset = 0
    
    try:
        # === Header (15字节) ===
        magic = struct.unpack('>H', data[offset:offset+2])[0]
        offset += 2
        if magic != 0x01AA:
            print(f"  ✗ 魔数错误: 0x{magic:04X}")
            return None
        result['magic'] = magic
        
        msg_id = data[offset]
        offset += 1
        if msg_id != 0x02:
            print(f"  ✗ 消息ID错误: 0x{msg_id:02X}")
            return None
        result['msg_id'] = msg_id
        
        frame_len = struct.unpack('>H', data[offset:offset+2])[0]
        offset += 2
        if frame_len != len(data):
            print(f"  ✗ 长度不匹配: 头部={frame_len}, 实际={len(data)}")
            return None
        result['frame_len'] = frame_len
        
        gps_week, gps_sow = struct.unpack('>HI', data[offset:offset+6])
        offset += 6
        result['gps_week'] = gps_week
        result['gps_sow'] = gps_sow
        
        # 转换GPS时间为UTC
        gps_epoch = datetime(1980, 1, 6)
        gps_time = gps_epoch + timedelta(weeks=gps_week, seconds=gps_sow)
        # 查找对应的闰秒
        leap_seconds = 18  # 默认
        for leap_date, leap_val in LEAP_SECOND_TABLE:
            if gps_time >= leap_date:
                leap_seconds = leap_val
            else:
                break
        utc_time = gps_time - timedelta(seconds=leap_seconds)
        result['utc_time'] = utc_time
        
        interval, iod = struct.unpack('>HB', data[offset:offset+3])
        offset += 3
        result['interval'] = interval
        result['iod'] = iod
        offset += 1  # 跳过1字节padding，对应encoder中的'x'
        
        # === Body ===
        model_type = data[offset]
        offset += 1
        result['model_type'] = model_type
        print(f"  [DEBUG] After model_type: offset={offset}")
        
        radius_m, height_m, coef_cnt = struct.unpack('>iiI', data[offset:offset+12])
        offset += 12
        result['radius'] = radius_m / 1000.0  # 转换回千米
        result['height'] = height_m / 1000.0  # 转换回千米
        result['coef_cnt'] = coef_cnt
        print(f"  [DEBUG] After radius/height/coef_cnt: offset={offset}, coef_cnt={coef_cnt}")
        
        # 读取系数
        coefs = []
        for _ in range(coef_cnt):
            coef_int = struct.unpack('>i', data[offset:offset+4])[0]
            offset += 4
            coef_tecu = coef_int / 1000.0
            coefs.append(coef_tecu)
        result['coefs'] = coefs
        print(f"  [DEBUG] After coefficients: offset={offset}")
        
        # 读取网格定义（微度格式，I32）
        lat1_udeg, lat2_udeg, dlat_udeg = struct.unpack('>iii', data[offset:offset+12])
        offset += 12
        lon1_udeg, lon2_udeg, dlon_udeg = struct.unpack('>iii', data[offset:offset+12])
        offset += 12
        print(f"  [DEBUG] After grid definition: offset={offset}")
        # 微度转换为度
        result['lat1'] = lat1_udeg / 1e6
        result['lat2'] = lat2_udeg / 1e6
        result['dlat'] = dlat_udeg / 1e6
        result['lon1'] = lon1_udeg / 1e6
        result['lon2'] = lon2_udeg / 1e6
        result['dlon'] = dlon_udeg / 1e6
        
        # 计算网格尺寸
        lat1 = result['lat1']
        lat2 = result['lat2']
        dlat = result['dlat']
        lon1 = result['lon1']
        lon2 = result['lon2']
        dlon = result['dlon']
        nlat = int((lat1 - lat2) / abs(dlat)) + 1
        nlon = int((lon2 - lon1) / abs(dlon)) + 1
        result['nlat'] = nlat
        result['nlon'] = nlon
        
        # 读取grid_total验证字段
        grid_total = struct.unpack('>H', data[offset:offset+2])[0]
        offset += 2
        result['grid_total'] = grid_total
        
        # RMS压缩数据（调试：打印offset）
        crc_offset = len(data) - 4  # 应该是726
        print(f"  [DEBUG] 读取RMS前: offset={offset}, crc_offset={crc_offset}")
        rms_size = crc_offset - offset
        print(f"  [DEBUG] RMS大小: {rms_size}字节")
        rms_compressed = data[offset:offset+rms_size]
        offset += rms_size
        print(f"  [DEBUG] 读取RMS后: offset={offset}")
        result['rms_compressed'] = rms_compressed
        result['rms_size'] = rms_size
        
        # 解压RMS数据
        rms_indices = []
        for byte in rms_compressed:
            high = (byte >> 4) & 0x0F
            low = byte & 0x0F
            rms_indices.extend([high, low])
        # 取实际需要的点数
        total_points = nlat * nlon
        rms_indices = rms_indices[:total_points]
        result['rms_indices'] = rms_indices
        
        # === Tail (4字节) ===
        received_crc = struct.unpack('>H', data[offset:offset+2])[0]
        offset += 2
        calculated_crc = crc16(data[2:crc_offset])
        if received_crc != calculated_crc:
            print(f"  ✗ CRC错误: 接收=0x{received_crc:04X}, 计算=0x{calculated_crc:04X}")
            return None
        result['crc'] = received_crc
        
        tail_marker = struct.unpack('>H', data[offset:offset+2])[0]
        offset += 2
        if tail_marker != 0x00FF:
            print(f"  ✗ 尾部标记错误: 0x{tail_marker:04X}")
            return None
        result['tail_marker'] = tail_marker
        
        return result
    
    except struct.error as e:
        print(f"  ✗ 解码错误: {e}")
        print(f"     当前offset={offset}, 数据总长度={len(data)}")
        print(f"     尝试读取的范围: [{offset}:{offset+4}]")
        return None
    except Exception as e:
        print(f"  ✗ 未知错误: {e}")
        import traceback
        traceback.print_exc()
        return None


def print_decoded(decoded: Dict[str, Any], compare_file: Optional[str] = None):
    """打印解码结果
    
    Args:
        decoded: 解码后的字典
        compare_file: 可选的INX文件路径，用于对比验证
    """
    print("\n" + "="*80)
    print("解码结果")
    print("="*80)
    
    print(f"\n[Header]")
    print(f"  魔数: 0x{decoded['magic']:04X}")
    print(f"  消息ID: 0x{decoded['msg_id']:02X}")
    print(f"  帧长度: {decoded['frame_len']} 字节")
    print(f"  GPS时间: Week {decoded['gps_week']}, SOW {decoded['gps_sow']}")
    print(f"  UTC时间: {decoded['utc_time'].strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  建模间隔: {decoded['interval']} 分钟")
    print(f"  IOD: {decoded['iod']}")
    
    print(f"\n[Body - 模型参数]")
    print(f"  模型类型: {decoded['model_type']}")
    print(f"  地球半径: {decoded['radius']} 米 ({decoded['radius']/1000} km)")
    print(f"  参考高度: {decoded['height']} 米 ({decoded['height']/1000} km)")
    print(f"  系数个数: {decoded['coef_cnt']}")
    
    print(f"\n[Body - 多项式系数] (前5个)")
    for i, coef in enumerate(decoded['coefs'][:5]):
        print(f"    [{i}] {coef:12.4f} TECU")
    
    print(f"\n[Body - 网格定义]")
    print(f"  纬度: {decoded['lat1']}° → {decoded['lat2']}° (步长 {decoded['dlat']}°)")
    print(f"  经度: {decoded['lon1']}° → {decoded['lon2']}° (步长 {decoded['dlon']}°)")
    print(f"  网格尺寸: {decoded['nlat']} × {decoded['nlon']} = {decoded['nlat']*decoded['nlon']} 点")
    
    print(f"\n[Body - RMS压缩]")
    print(f"  压缩字节数: {decoded['rms_size']}")
    print(f"  解压索引数: {len(decoded['rms_indices'])}")
    print(f"  前20个索引: {decoded['rms_indices'][:20]}")
    
    print(f"\n[Tail]")
    print(f"  CRC-16: 0x{decoded['crc']:04X}")
    print(f"  尾部标记: 0x{decoded['tail_marker']:04X}")
    
    # 如果提供了对比文件，进行验证
    if compare_file and Path(compare_file).exists():
        print(f"\n" + "="*80)
        print("对比原始文件")
        print("="*80)
        
        try:
            parsed = parse_inx(compare_file)
            
            # 对比时间
            parsed_time = parsed['time']
            if parsed_time == decoded['utc_time']:
                print(f"  ✓ 时间匹配: {parsed_time}")
            else:
                print(f"  ✗ 时间不匹配: 文件={parsed_time}, 解码={decoded['utc_time']}")
            
            # 对比系数
            if len(parsed['coefs']) == decoded['coef_cnt']:
                print(f"  ✓ 系数个数匹配: {decoded['coef_cnt']}")
                max_diff = max(abs(a - b) for a, b in zip(parsed['coefs'], decoded['coefs']))
                if max_diff < 0.01:
                    print(f"  ✓ 系数值匹配 (最大差异 {max_diff:.6f} TECU)")
                else:
                    print(f"  ✗ 系数值差异过大 (最大差异 {max_diff:.6f} TECU)")
            else:
                print(f"  ✗ 系数个数不匹配: 文件={len(parsed['coefs'])}, 解码={decoded['coef_cnt']}")
            
            # 对比网格
            if (abs(parsed['lat1'] - decoded['lat1']) < 0.01 and
                abs(parsed['lon1'] - decoded['lon1']) < 0.01):
                print(f"  ✓ 网格定义匹配")
            else:
                print(f"  ✗ 网格定义不匹配")
            
            # 对比RMS矩阵尺寸
            if (len(parsed['rms']) == decoded['nlat'] and 
                len(parsed['rms'][0]) == decoded['nlon']):
                print(f"  ✓ RMS矩阵尺寸匹配: {decoded['nlat']}×{decoded['nlon']}")
            else:
                print(f"  ✗ RMS矩阵尺寸不匹配")
                
        except Exception as e:
            print(f"  ✗ 对比文件解析失败: {e}")
    
    print("="*80)


def receive_and_decode(host: str, port: int, count: int = 1, 
                       compare_file: Optional[str] = None,
                       duration: Optional[int] = None,
                       output_file: Optional[str] = None):
    """接收并解码TCP帧
    
    Args:
        host: 服务器地址
        port: 服务器端口
        count: 接收帧数（-1为无限）
        compare_file: 可选的INX文件路径，用于对比验证
        duration: 可选的运行时长（秒），如果指定则在时长到达后停止
        output_file: 可选的输出文件路径，如果指定则将结果写入文件
    """
    import time
    
    # 打开输出文件（如果指定）
    output_fp = None
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_fp = open(output_path, 'w', encoding='utf-8')
        output_fp.write(f"接收测试开始 - {datetime.now()}\n")
        output_fp.write(f"服务器: {host}:{port}\n")
        if duration:
            output_fp.write(f"测试时长: {duration}秒\n")
        output_fp.write("="*80 + "\n\n")
    
    print(f"连接到 {host}:{port}")
    if output_fp:
        output_fp.write(f"连接到 {host}:{port}\n")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    
    start_time = time.time() if duration else None
    
    try:
        sock.connect((host, port))
        print(f"✓ 已连接")
        if output_fp:
            output_fp.write(f"✓ 已连接\n\n")
        
        received = 0
        while count == -1 or received < count:
            # 检查是否超时
            if duration and (time.time() - start_time) >= duration:
                msg = f"\n已达到设定时长 {duration}秒，停止接收\n"
                print(msg.strip())
                if output_fp:
                    output_fp.write(msg)
                break
            
            # 接收Header确定帧长度
            header = b''
            while len(header) < 15:
                chunk = sock.recv(15 - len(header))
                if not chunk:
                    print("连接关闭")
                    return
                header += chunk
            
            # 解析长度
            frame_len = struct.unpack('>H', header[3:5])[0]
            
            # 接收剩余数据
            remaining = frame_len - 15
            body_tail = b''
            while len(body_tail) < remaining:
                chunk = sock.recv(remaining - len(body_tail))
                if not chunk:
                    print("连接关闭")
                    return
                body_tail += chunk
            
            frame_data = header + body_tail
            received += 1
            elapsed = time.time() - start_time if start_time else 0
            
            separator = f"\n{'='*80}\n"
            separator += f"接收帧 #{received}, 长度 {len(frame_data)} 字节"
            if duration:
                separator += f" (elapsed: {elapsed:.1f}s)"
            separator += f"\n{'='*80}\n"
            
            print(separator, end='')
            if output_fp:
                output_fp.write(separator)
            
            # 输出完整十六进制dump到文件
            if output_fp:
                output_fp.write("\n--- 完整帧数据 (十六进制) ---\n")
                for i in range(0, len(frame_data), 16):
                    # 字节偏移
                    output_fp.write(f"{i:04d}: ")
                    # 十六进制
                    hex_part = ' '.join(f'{b:02x}' for b in frame_data[i:i+16])
                    output_fp.write(f"{hex_part:<48}  ")
                    # ASCII (可打印字符)
                    ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in frame_data[i:i+16])
                    output_fp.write(f"{ascii_part}\n")
                output_fp.write("\n")
            
            hex_info = f"前20字节 (hex): {' '.join(f'{b:02x}' for b in frame_data[:20])}\n"
            hex_info += f"后10字节 (hex): {' '.join(f'{b:02x}' for b in frame_data[-10:])}\n"
            print(hex_info)
            if output_fp:
                output_fp.write(hex_info)
            
            # 解码
            decoded = decode_frame(frame_data)
            if decoded:
                if output_fp:
                    # 写入详细解码结果到文件
                    output_fp.write(f"\n✓ 解码成功\n\n")
                    output_fp.write(f"--- Header ---\n")
                    output_fp.write(f"Magic:      0x{decoded['magic']:04X}\n")
                    output_fp.write(f"Message ID: 0x{decoded['msg_id']:02X}\n")
                    output_fp.write(f"Frame Len:  {decoded['frame_len']} bytes\n")
                    output_fp.write(f"GPS Week:   {decoded['gps_week']}\n")
                    output_fp.write(f"GPS SOW:    {decoded['gps_sow']}\n")
                    output_fp.write(f"UTC Time:   {decoded['utc_time']}\n")
                    output_fp.write(f"Interval:   {decoded['interval']} min\n")
                    output_fp.write(f"IOD:        {decoded['iod']}\n\n")
                    
                    output_fp.write(f"--- Body ---\n")
                    output_fp.write(f"Model Type: {decoded['model_type']}\n")
                    output_fp.write(f"Radius:     {decoded['radius']:.3f} km\n")
                    output_fp.write(f"Height:     {decoded['height']:.3f} km\n")
                    output_fp.write(f"Coef Count: {decoded['coef_cnt']}\n")
                    output_fp.write(f"Coefficients (前10个): ")
                    output_fp.write(', '.join(f"{c:.3f}" for c in decoded['coefs'][:10]))
                    output_fp.write(f" ... (共{len(decoded['coefs'])}个)\n\n")
                    
                    output_fp.write(f"Grid Definition:\n")
                    output_fp.write(f"  Latitude:  [{decoded['lat1']:.2f}, {decoded['lat2']:.2f}] step={decoded['dlat']:.2f}\n")
                    output_fp.write(f"  Longitude: [{decoded['lon1']:.2f}, {decoded['lon2']:.2f}] step={decoded['dlon']:.2f}\n")
                    output_fp.write(f"  Grid Size: {decoded['nlat']} x {decoded['nlon']} = {decoded['grid_total']} points\n\n")
                    
                    output_fp.write(f"RMS Data:\n")
                    output_fp.write(f"  Compressed Size: {decoded['rms_size']} bytes\n")
                    output_fp.write(f"  RMS Indices (前20个): ")
                    output_fp.write(', '.join(str(idx) for idx in decoded['rms_indices'][:20]))
                    output_fp.write(f" ... (共{len(decoded['rms_indices'])}个)\n\n")
                    
                    output_fp.write(f"--- Tail ---\n")
                    output_fp.write(f"CRC:        0x{decoded['crc']:04X}\n")
                    output_fp.write(f"Tail Mark:  0x{decoded['tail_marker']:04X}\n\n")
                    output_fp.flush()
                
                print_decoded(decoded, compare_file)
            else:
                msg = "✗ 解码失败\n"
                print(msg.strip())
                if output_fp:
                    output_fp.write(msg)
    
    except socket.timeout:
        msg = "接收超时\n"
        print(msg.strip())
        if output_fp:
            output_fp.write(msg)
    except Exception as e:
        msg = f"错误: {e}\n"
        print(msg.strip())
        if output_fp:
            output_fp.write(msg)
    finally:
        sock.close()
        msg = "\n连接关闭\n"
        print(msg.strip())
        if output_fp:
            output_fp.write(msg)
            output_fp.write(f"\n接收测试结束 - {datetime.now()}\n")
            output_fp.write(f"总共接收: {received} 帧\n")
            output_fp.write("="*80 + "\n")
            output_fp.close()
            print(f"\n结果已保存到: {Path(output_file).absolute()}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='TCP接收和解码测试')
    parser.add_argument('-H', '--host', default='127.0.0.1', help='服务器地址')
    parser.add_argument('-p', '--port', type=int, default=5000, help='服务器端口')
    parser.add_argument('-n', '--count', type=int, default=3, help='接收帧数（-1为无限）')
    parser.add_argument('-c', '--compare', help='对比的INX文件路径')
    parser.add_argument('-t', '--time', type=int, help='运行时长（秒）')
    parser.add_argument('-o', '--output', help='输出文件路径', default='output/decode_results.txt')
    
    args = parser.parse_args()
    
    receive_and_decode(args.host, args.port, args.count, args.compare, args.time, args.output)


if __name__ == '__main__':
    main()
