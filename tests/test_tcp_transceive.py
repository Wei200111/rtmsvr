#!/usr/bin/env python3
"""TCP收发验证测试"""

import sys
import socket
import threading
import time
import struct
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parser import parse_inx
from src.encoder import encode_frame
from src.tcpcmn import crc16


def start_test_server(frame_data: bytes, port: int, send_count: int = 3):
    """测试服务器：发送指定的帧数据"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', port))
    server.listen(1)
    
    print(f"[服务器] 启动在端口 {port}")
    
    try:
        conn, addr = server.accept()
        print(f"[服务器] 客户端连接: {addr}")
        
        for i in range(send_count):
            conn.sendall(frame_data)
            print(f"[服务器] 发送帧 #{i+1}, 长度 {len(frame_data)} 字节")
            time.sleep(1)
        
        time.sleep(0.5)  # 等待客户端接收完成
        conn.close()
    except Exception as e:
        print(f"[服务器] 错误: {e}")
    finally:
        server.close()
        print("[服务器] 关闭")


def validate_frame(data: bytes) -> bool:
    """验证接收到的帧"""
    if len(data) < 19:  # 最小帧长度
        print(f"  ✗ 帧太短: {len(data)} 字节")
        return False
    
    # 1. 检查魔数
    magic = struct.unpack('>H', data[0:2])[0]
    if magic != 0x01AA:
        print(f"  ✗ 魔数错误: 0x{magic:04X} (期望 0x01AA)")
        return False
    print(f"  ✓ 魔数: 0x{magic:04X}")
    
    # 2. 检查消息ID
    msg_id = data[2]
    if msg_id != 0x02:
        print(f"  ✗ 消息ID错误: 0x{msg_id:02X} (期望 0x02)")
        return False
    print(f"  ✓ 消息ID: 0x{msg_id:02X}")
    
    # 3. 检查长度
    frame_len = struct.unpack('>H', data[3:5])[0]
    if frame_len != len(data):
        print(f"  ✗ 长度不匹配: 头部={frame_len}, 实际={len(data)}")
        return False
    print(f"  ✓ 帧长度: {frame_len} 字节")
    
    # 4. 验证CRC
    crc_offset = len(data) - 4
    received_crc = struct.unpack('>H', data[crc_offset:crc_offset+2])[0]
    calculated_crc = crc16(data[2:crc_offset])
    if received_crc != calculated_crc:
        print(f"  ✗ CRC错误: 接收=0x{received_crc:04X}, 计算=0x{calculated_crc:04X}")
        return False
    print(f"  ✓ CRC校验: 0x{received_crc:04X}")
    
    # 5. 检查尾部标记
    tail_marker = struct.unpack('>H', data[-2:])[0]
    if tail_marker != 0x00FF:
        print(f"  ✗ 尾部标记错误: 0x{tail_marker:04X} (期望 0x00FF)")
        return False
    print(f"  ✓ 尾部标记: 0x{tail_marker:04X}")
    
    # 6. 解析GPS时间和IOD
    gps_week, gps_sow = struct.unpack('>HI', data[5:11])
    interval, iod = struct.unpack('>HB', data[11:14])
    print(f"  ✓ GPS时间: Week {gps_week}, SOW {gps_sow}")
    print(f"  ✓ 间隔: {interval} 分钟, IOD: {iod}")
    
    # 7. 解析Body开始部分
    model_type = data[15]
    radius, height, coef_cnt = struct.unpack('>III', data[16:28])
    print(f"  ✓ 模型类型: {model_type}")
    print(f"  ✓ 地球半径: {radius} 米 ({radius/1000} km)")
    print(f"  ✓ 参考高度: {height} 米 ({height/1000} km)")
    print(f"  ✓ 系数个数: {coef_cnt}")
    
    return True


def test_client(port: int, expected_frame: bytes, recv_count: int = 3):
    """测试客户端：接收并验证数据"""
    time.sleep(0.5)  # 等待服务器启动
    
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    try:
        client.connect(('127.0.0.1', port))
        print(f"[客户端] 连接到服务器端口 {port}")
        
        for i in range(recv_count):
            # 先接收Header确定长度
            header = client.recv(15)
            if len(header) < 15:
                print(f"[客户端] 接收Header失败")
                return
            
            frame_len = struct.unpack('>H', header[3:5])[0]
            remaining = frame_len - 15
            
            # 接收剩余数据
            body_tail = b''
            while len(body_tail) < remaining:
                chunk = client.recv(remaining - len(body_tail))
                if not chunk:
                    break
                body_tail += chunk
            
            received = header + body_tail
            
            print(f"\n[客户端] 接收帧 #{i+1}, 长度 {len(received)} 字节")
            print(f"  前20字节 (hex): {' '.join(f'{b:02x}' for b in received[:20])}")
            print(f"  后10字节 (hex): {' '.join(f'{b:02x}' for b in received[-10:])}")
            
            # 验证帧结构
            if validate_frame(received):
                print("  ✓ 帧结构验证通过")
            else:
                print("  ✗ 帧结构验证失败")
            
            # 对比原始数据
            if received == expected_frame:
                print("  ✓ 数据完全匹配原始帧")
            else:
                print(f"  ✗ 数据不匹配 (期望 {len(expected_frame)} 字节)")
                # 找出差异位置
                for idx, (a, b) in enumerate(zip(expected_frame, received)):
                    if a != b:
                        print(f"    首个差异在偏移 {idx}: 期望 0x{a:02x}, 收到 0x{b:02x}")
                        break
    
    except Exception as e:
        print(f"[客户端] 错误: {e}")
    finally:
        client.close()
        print("[客户端] 关闭连接")


def main():
    print("=" * 80)
    print("TCP 收发验证测试")
    print("=" * 80)
    
    # 1. 解析INX文件并编码
    inx_file = Path(__file__).parent / 'test_data' / 'ATMO2025322160000_vtec_grid.inx'
    print(f"\n[1] 解析INX文件: {inx_file.name}")
    
    parsed_data = parse_inx(str(inx_file))
    print(f"  ✓ 解析成功")
    print(f"    RMS矩阵: {len(parsed_data['rms'])} 行 × {len(parsed_data['rms'][0])} 列")
    print(f"    系数个数: {len(parsed_data['coefs'])}")
    
    # 2. 编码为二进制帧
    print(f"\n[2] 编码为二进制帧")
    frame = encode_frame(parsed_data, iod=1)
    print(f"  ✓ 编码成功，帧长度: {len(frame)} 字节")
    print(f"  原始帧前20字节 (hex): {' '.join(f'{b:02x}' for b in frame[:20])}")
    print(f"  原始帧后10字节 (hex): {' '.join(f'{b:02x}' for b in frame[-10:])}")
    
    # 3. 启动TCP收发测试
    print(f"\n[3] 启动TCP收发测试")
    test_port = 12345
    send_count = 3
    
    # 启动服务器线程
    server_thread = threading.Thread(
        target=start_test_server,
        args=(frame, test_port, send_count),
        daemon=True
    )
    server_thread.start()
    
    # 启动客户端测试
    test_client(test_port, frame, send_count)
    
    # 等待服务器线程结束
    server_thread.join(timeout=5)
    
    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)


if __name__ == '__main__':
    main()
