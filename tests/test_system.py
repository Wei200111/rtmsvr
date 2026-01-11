# test_system.py - 系统综合测试

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from src.tcpcmn import get_leap_seconds, utc2gps, crc16, rms2idx
from src.encoder import encode_frame


def test_all():
    """运行所有测试"""
    print("=" * 70)
    print("RTVM系统综合测试")
    print("=" * 70)
    
    all_pass = True
    
    # 1. 闰秒测试
    print("\n[1/5] 闰秒查询测试...")
    leap_2026 = get_leap_seconds(datetime(2026, 1, 11))
    if leap_2026 == 18:
        print(f"  ✓ 2026年闰秒正确: {leap_2026}s")
    else:
        print(f"  ✗ 2026年闰秒错误: 期望18, 实际{leap_2026}")
        all_pass = False
    
    # 2. GPS时间转换测试
    print("\n[2/5] GPS时间转换测试...")
    week, sow = utc2gps(datetime(2025, 11, 18, 16, 0, 0))
    print(f"  UTC 2025-11-18 16:00:00 → GPS Week {week}, SOW {sow}")
    if week > 2300:  # 粗略验证
        print("  ✓ GPS周正确")
    else:
        print(f"  ✗ GPS周异常")
        all_pass = False
    
    # 3. CRC测试
    print("\n[3/5] CRC-16/XMODEM测试...")
    test_data = b"123456789"
    crc_val = crc16(test_data)
    expected_crc = 0x31C3  # "123456789"的标准CRC-16/XMODEM值
    if crc_val == expected_crc:
        print(f"  ✓ CRC正确: 0x{crc_val:04X}")
    else:
        print(f"  ✗ CRC错误: 期望0x{expected_crc:04X}, 实际0x{crc_val:04X}")
        all_pass = False
    
    # 4. RMS索引映射测试
    print("\n[4/5] RMS索引映射测试...")
    test_cases = [
        (0, 0),    # <6 → 0
        (5, 0),    # <6 → 0
        (6, 1),    # 6~12 → 1
        (12, 2),   # 12~18 → 2
        (90, 15),  # ≥90 → 15
        (100, 15), # ≥90 → 15
    ]
    rms_ok = True
    for rms_val, expected_idx in test_cases:
        actual_idx = rms2idx(rms_val)
        if actual_idx != expected_idx:
            print(f"  ✗ RMS={rms_val} → 期望{expected_idx}, 实际{actual_idx}")
            rms_ok = False
            all_pass = False
    if rms_ok:
        print(f"  ✓ RMS映射测试通过 ({len(test_cases)}个用例)")
    
    # 5. 帧编码测试
    print("\n[5/5] 帧编码测试...")
    mock_data = {
        'time': datetime(2025, 11, 18, 16, 0, 0),
        'order': (2, 2),
        'coef_cnt': 9,
        'coefs': [1.5, -2.3, 0.0, 4.7, -0.8, 3.2, -1.1, 2.9, 0.5],
        'base_r': 6371.0,
        'hgt': 450.0,
        'lat': (55.0, 25.0, -1.0),
        'lon': (95.0, 135.0, 1.0),
        'rms': [[5, 10, 15], [20, 25, 30]]
    }
    
    try:
        frame = encode_frame(mock_data, iod=1)
        if len(frame) > 0:
            magic = int.from_bytes(frame[0:2], 'big')
            msg_id = frame[2]
            length = int.from_bytes(frame[3:5], 'big')
            
            print(f"  帧长度: {len(frame)} 字节")
            print(f"  魔数: 0x{magic:04X} {'✓' if magic == 0x01AA else '✗'}")
            print(f"  消息ID: 0x{msg_id:02X} {'✓' if msg_id == 0x02 else '✗'}")
            print(f"  声明长度: {length}, 实际长度: {len(frame)} {'✓' if length == len(frame) else '✗'}")
            
            if magic == 0x01AA and msg_id == 0x02 and length == len(frame):
                print("  ✓ 帧编码测试通过")
            else:
                print("  ✗ 帧编码存在问题")
                all_pass = False
        else:
            print("  ✗ 帧编码失败（长度为0）")
            all_pass = False
    except Exception as e:
        print(f"  ✗ 帧编码异常: {e}")
        all_pass = False
    
    # 总结
    print("\n" + "=" * 70)
    if all_pass:
        print("测试结果: 全部通过 ✓")
        print("=" * 70)
        return 0
    else:
        print("测试结果: 存在失败 ✗")
        print("=" * 70)
        return 1


if __name__ == '__main__':
    sys.exit(test_all())
