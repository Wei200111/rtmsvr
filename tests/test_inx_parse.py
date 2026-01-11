# test_inx_parse.py - 测试INX文件解析和帧编码

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parser import parse_inx
from src.encoder import encode_frame
import struct


def test_parse_and_encode():
    """测试INX文件解析和帧编码"""
    
    inx_file = Path(__file__).parent / 'test_data' / 'ATMO2025322160000_vtec_grid.inx'
    
    print("=" * 80)
    print(f"测试文件: {inx_file.name}")
    print("=" * 80)
    
    # 1. 解析INX文件
    print("\n[1] 解析INX文件...")
    try:
        data = parse_inx(str(inx_file))
        print("  ✓ 解析成功")
    except Exception as e:
        print(f"  ✗ 解析失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 2. 显示解析结果
    print("\n[2] 解析结果:")
    print(f"  时间: {data['time']}")
    print(f"  阶数: {data['order']} (N×M)")
    print(f"  系数个数: {data['coef_cnt']}")
    print(f"  实际系数: {len(data['coefs'])} 个")
    print(f"  地球半径: {data['base_r']} km")
    print(f"  参考高度: {data['hgt']} km")
    print(f"  纬度范围: {data['lat'][0]}° → {data['lat'][1]}° (步长 {data['lat'][2]}°)")
    print(f"  经度范围: {data['lon'][0]}° → {data['lon'][1]}° (步长 {data['lon'][2]}°)")
    print(f"  RMS矩阵: {len(data['rms'])} 行 × {len(data['rms'][0]) if data['rms'] else 0} 列")
    
    # 显示前几个系数
    print(f"\n  前5个系数:")
    for i, coef in enumerate(data['coefs'][:5]):
        print(f"    [{i}] {coef:12.4f} TECU")
    
    # 显示RMS样例
    if data['rms']:
        print(f"\n  RMS样例 (前3行, 前10列):")
        for i, row in enumerate(data['rms'][:3]):
            vals = ' '.join(f"{v:3d}" for v in row[:10])
            print(f"    行{i}: {vals} ...")
    
    # 3. 编码为二进制帧
    print("\n[3] 编码为二进制帧...")
    try:
        frame = encode_frame(data, iod=1)
        print(f"  ✓ 编码成功，帧长度: {len(frame)} 字节")
    except Exception as e:
        print(f"  ✗ 编码失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 4. 解析帧头验证
    print("\n[4] 帧结构验证:")
    
    # 解析Header (15字节)
    magic = struct.unpack('>H', frame[0:2])[0]
    msg_id = frame[2]
    length = struct.unpack('>H', frame[3:5])[0]
    week = struct.unpack('>H', frame[5:7])[0]
    sow = struct.unpack('>I', frame[7:11])[0]
    interval = struct.unpack('>H', frame[11:13])[0]
    iod = frame[13]
    
    print(f"  Header (15字节):")
    print(f"    魔数: 0x{magic:04X} {'✓' if magic == 0x01AA else '✗ 错误'}")
    print(f"    消息ID: 0x{msg_id:02X} {'✓' if msg_id == 0x02 else '✗ 错误'}")
    print(f"    帧长度: {length} 字节 {'✓' if length == len(frame) else f'✗ 不匹配(实际{len(frame)})'}")
    print(f"    GPS周: {week}")
    print(f"    GPS秒: {sow}")
    print(f"    建模间隔: {interval} 分钟")
    print(f"    IOD: {iod}")
    
    # 解析Body起始部分
    offset = 15
    model_type = frame[offset]
    base_r_m = struct.unpack('>i', frame[offset+1:offset+5])[0]
    hgt_m = struct.unpack('>i', frame[offset+5:offset+9])[0]
    coef_cnt = struct.unpack('>I', frame[offset+9:offset+13])[0]
    
    print(f"\n  Body开始部分:")
    print(f"    模型类型: {model_type} {'✓' if model_type == 0 else '✗ 错误'}")
    print(f"    地球半径: {base_r_m} 米 ({base_r_m/1000} km)")
    print(f"    参考高度: {hgt_m} 米 ({hgt_m/1000} km)")
    print(f"    系数个数: {coef_cnt} {'✓' if coef_cnt == data['coef_cnt'] else '✗ 不匹配'}")
    
    # 解析前几个系数
    offset = 15 + 13  # Header + model_type + base_r + hgt + coef_cnt
    print(f"\n  前5个系数 (编码后):")
    for i in range(min(5, coef_cnt)):
        coef_encoded = struct.unpack('>i', frame[offset:offset+4])[0]
        coef_decoded = coef_encoded / 1000.0  # 转回TECU (0.001 TECU量化)
        original = data['coefs'][i]
        diff = abs(coef_decoded - original)
        # 0.001 TECU精度，允许0.001的误差
        status = '✓' if diff < 0.002 else '✗'
        print(f"    [{i}] 原始: {original:12.4f}, 编码: {coef_encoded:8d} (0.001TECU), 解码: {coef_decoded:12.4f} {status}")
        offset += 4
    
    # 解析Grid定义
    grid_offset = 15 + 13 + coef_cnt * 4
    lat1_udeg = struct.unpack('>i', frame[grid_offset:grid_offset+4])[0]
    lat2_udeg = struct.unpack('>i', frame[grid_offset+4:grid_offset+8])[0]
    dlat_udeg = struct.unpack('>i', frame[grid_offset+8:grid_offset+12])[0]
    lon1_udeg = struct.unpack('>i', frame[grid_offset+12:grid_offset+16])[0]
    lon2_udeg = struct.unpack('>i', frame[grid_offset+16:grid_offset+20])[0]
    dlon_udeg = struct.unpack('>i', frame[grid_offset+20:grid_offset+24])[0]
    grid_total = struct.unpack('>H', frame[grid_offset+24:grid_offset+26])[0]
    
    print(f"\n  网格定义:")
    print(f"    纬度: {lat1_udeg/1e6}° → {lat2_udeg/1e6}° (步长 {dlat_udeg/1e6}°)")
    print(f"    经度: {lon1_udeg/1e6}° → {lon2_udeg/1e6}° (步长 {dlon_udeg/1e6}°)")
    print(f"    网格总点数: {grid_total}")
    
    # 计算期望的网格点数
    nlat = len(data['rms'])
    nlon = len(data['rms'][0]) if data['rms'] else 0
    expected_total = nlat * nlon
    print(f"    期望点数: {expected_total} ({nlat}×{nlon}) {'✓' if grid_total == expected_total else '✗ 不匹配'}")
    
    # 解析RMS压缩数据
    rms_offset = grid_offset + 26
    rms_bytes_count = len(frame) - rms_offset - 4  # 减去Tail的4字节
    print(f"\n  RMS压缩:")
    print(f"    压缩数据: {rms_bytes_count} 字节")
    print(f"    可容纳点数: {rms_bytes_count * 2} 个 (每字节2个4-bit索引)")
    
    # 显示前几个RMS压缩值
    print(f"    前10个字节 (hex): {frame[rms_offset:rms_offset+10].hex(' ')}")
    
    # 解析Tail
    tail_offset = len(frame) - 4
    crc = struct.unpack('>H', frame[tail_offset:tail_offset+2])[0]
    type_marker = struct.unpack('>H', frame[tail_offset+2:tail_offset+4])[0]
    
    print(f"\n  Tail (4字节):")
    print(f"    CRC: 0x{crc:04X}")
    print(f"    类型标记: 0x{type_marker:04X} {'✓' if type_marker == 0x00FF else '✗ 错误'}")
    
    # 验证CRC
    from src.tcpcmn import crc16
    crc_data = frame[2:tail_offset]  # 从消息ID到CRC前
    calculated_crc = crc16(crc_data)
    print(f"    计算CRC: 0x{calculated_crc:04X} {'✓' if calculated_crc == crc else '✗ 不匹配'}")
    
    # 总结
    print("\n" + "=" * 80)
    if (magic == 0x01AA and msg_id == 0x02 and length == len(frame) and 
        model_type == 0 and coef_cnt == data['coef_cnt'] and 
        type_marker == 0x00FF and calculated_crc == crc and
        grid_total == expected_total):
        print("测试结果: 全部通过 ✓")
        print("=" * 80)
        return True
    else:
        print("测试结果: 存在问题 ✗")
        print("=" * 80)
        return False


if __name__ == '__main__':
    success = test_parse_and_encode()
    sys.exit(0 if success else 1)
