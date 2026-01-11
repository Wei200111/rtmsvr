#!/usr/bin/env python3
"""调试解码问题 - 详细跟踪offset"""

import struct

# 从输出文件中看到的前20字节
hex_data = "01aa0202da09590008 83c2000f01000000 6136b8"
# 这是示例，实际需要完整730字节

# 手动解析Header
print("=== Header 解析 ===")
print(f"总长度应该是: 730字节")
print(f"Header: 15字节")
print(f"Body: 730 - 15 - 4 = 711字节")
print(f"Tail: 4字节")
print()

# 从INX文件我们知道：
# - 9个系数
# - 网格: 55.0→25.0 step 1.0 (纬度31个点)
# -      95.0→135.0 step 1.0 (经度41个点)
# - 总点数: 31 x 41 = 1271个点

nlat = 31
nlon = 41
total_points = nlat * nlon
print(f"网格点数: {nlat} x {nlon} = {total_points}")

# Body结构计算：
body_size = 0
print("\n=== Body 结构 ===")
print(f"Model type (B): 1字节")
body_size += 1

print(f"Radius, Height, CoefCnt (iiI): 12字节")
body_size += 12

coef_cnt = 9
print(f"Coefficients (9 x i): {coef_cnt * 4}字节")
body_size += coef_cnt * 4

print(f"Grid定义 (6 x i): 24字节")
body_size += 24

print(f"Grid total (H): 2字节")
body_size += 2

# RMS压缩：每2个点1字节，如果是奇数点数则最后半字节
rms_bytes = (total_points + 1) // 2
print(f"RMS压缩 ({total_points}点 → {rms_bytes}字节): {rms_bytes}字节")
body_size += rms_bytes

print(f"\nBody总计: {body_size}字节")
print(f"预期总长: 15 + {body_size} + 4 = {15 + body_size + 4}字节")

if 15 + body_size + 4 == 730:
    print("✓ 长度匹配！")
else:
    print(f"✗ 长度不匹配！差异: {730 - (15 + body_size + 4)}字节")
