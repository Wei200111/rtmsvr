#!/usr/bin/env python3
"""快速测试：播发和接收解码

用法：
1. 先运行此脚本启动播发服务器（会自动后台运行）
2. 然后自动启动接收解码客户端
3. 接收3帧后自动停止
"""

import sys
import subprocess
import time
from pathlib import Path


def main():
    print("="*80)
    print("快速测试：播发 -> 接收 -> 解码")
    print("="*80)
    
    project_root = Path(__file__).parent.parent
    config_file = project_root / 'config' / 'bcast.json'
    test_inx = project_root / 'tests' / 'test_data' / 'ATMO2025322160000_vtec_grid.inx'
    
    if not config_file.exists():
        print(f"✗ 配置文件不存在: {config_file}")
        return
    
    if not test_inx.exists():
        print(f"✗ 测试INX文件不存在: {test_inx}")
        return
    
    print(f"\n[1] 启动播发服务器（后台）")
    print(f"    配置文件: {config_file}")
    print(f"    测试文件: {test_inx}")
    
    # 启动播发服务器
    server_proc = subprocess.Popen(
        [sys.executable, '-m', 'src.main', str(config_file)],
        cwd=str(project_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # 等待服务器启动
    print("    等待服务器启动...")
    time.sleep(3)
    
    if server_proc.poll() is not None:
        stdout, stderr = server_proc.communicate()
        print(f"✗ 服务器启动失败")
        print(f"stdout: {stdout}")
        print(f"stderr: {stderr}")
        return
    
    print("    ✓ 服务器已启动")
    
    try:
        print(f"\n[2] 启动接收解码客户端")
        print(f"    接收3帧并解码对比...")
        
        # 启动接收客户端
        client_proc = subprocess.run(
            [sys.executable, 'tests/decode_receiver.py',
             '-H', '127.0.0.1',
             '-p', '5000',
             '-n', '3',
             '-c', str(test_inx)],
            cwd=str(project_root),
            timeout=60
        )
        
        if client_proc.returncode == 0:
            print("\n✓ 测试完成")
        else:
            print(f"\n✗ 客户端返回错误码: {client_proc.returncode}")
    
    except subprocess.TimeoutExpired:
        print("\n✗ 客户端超时")
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        print(f"\n[3] 停止服务器")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
            print("    ✓ 服务器已停止")
        except subprocess.TimeoutExpired:
            server_proc.kill()
            print("    ✓ 服务器已强制停止")
    
    print("="*80)


if __name__ == '__main__':
    main()
