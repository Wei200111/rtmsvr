# RTVM电离层模型广播系统

基于TCP协议的电离层模型数据实时广播系统，兼容RTKLIB/str2str接收格式。

## 功能特性

- **自动监控**: 监控INX文件目录，自动加载新文件
- **TCP广播**: 多客户端并发连接，10秒周期广播
- **IOD绑定**: IOD计数器绑定数据内容（哈希），而非发送次数
- **异常处理**: TCP发送异常捕获，防止单客户端故障影响全局
- **精度保证**: Float→Int转换使用epsilon（1e-9），避免截断误差

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置参数

编辑 `config/bcast.json`:

```json
{
  "file_watcher": {
    "watch_dir": "e:/rtm/rtmodel5window/vminx",
    "file_pattern": "*.inx"
  },
  "broadcast": {
    "interval_seconds": 10.0
  },
  "tcp_server": {
    "host": "0.0.0.0",
    "port": 5000,
    "max_clients": 10
  }
}
```

### 3. 运行程序

```bash
cd e:\rtm\rtmodel5window\bofa\rtmsvr
python -m src.main
```

### 4. 客户端连接

使用RTKLIB或任意TCP客户端连接:

```bash
# rtkrcv示例
tcpcli://localhost:5000

# 或使用telnet测试
telnet localhost 5000
```

## 项目结构

```
rtmsvr/
├── config/
│   └── bcast.json          # 配置文件
├── logs/
│   └── bcast.log           # 运行日志
├── src/
│   ├── __init__.py         # 包初始化
│   ├── main.py             # 主程序入口
│   ├── parser.py           # INX文件解析器
│   ├── encoder.py          # 二进制协议编码器
│   ├── tcpsvr.py           # TCP服务器（rtkrcv风格）
│   ├── bcast.py            # 播发管理器（IOD绑定）
│   ├── watcher.py          # 文件监控器（watchdog）
│   └── tcpcmn.py           # 公共工具函数
└── requirements.txt        # Python依赖
```

## 协议格式

### 帧结构

```
Header (13字节):
  - U16 魔数 0x01AA
  - U8  消息ID 0x02
  - U16 帧长度
  - U16 GPS周
  - U32 GPS秒SOW
  - U16 建模间隔（分钟）
  - U8  IOD计数器
  - U8  保留

Body (可变长度):
  - U8  模型类型（0=球谐）
  - I32 地球半径（米）
  - I32 参考高度（米）
  - U32 系数个数
  - I32[] 系数数组（0.1 TECU单位）
  - I32[6] 网格定义（微度）
  - U16 网格总点数
  - U8[] RMS压缩数据

Tail (4字节):
  - U16 CRC-16/XMODEM校验和
  - U16 类型标记 0x00FF
```

### 字节序

所有多字节字段使用**大端序**（Big-Endian）。

## IOD语义说明

**重要**: IOD（Issue of Data）必须绑定数据内容，而非发送次数。

- ✅ 同一文件重复播发 → IOD保持不变
- ✅ 文件内容变化 → IOD递增
- ❌ 每次发送都递增IOD（错误）

实现方式: 通过SHA256哈希识别文件内容变化。

## 日志说明

日志输出到两个位置:
- 控制台: 实时显示INFO级别
- 文件: `logs/bcast.log` 详细记录

示例输出:
```
2025-01-18 16:00:00 INFO     TCP服务器启动: 0.0.0.0:5000
2025-01-18 16:00:05 INFO     新客户端连接: ('127.0.0.1', 52341), 总计 1 个
2025-01-18 16:00:10 INFO     播发成功: 1024 字节 → 1 客户端, IOD=1
```

## 常见问题

### Q1: 如何修改播发间隔？

编辑 `config/bcast.json` 中的 `broadcast.interval_seconds`。

### Q2: 端口被占用怎么办？

修改 `tcp_server.port` 为其他可用端口（建议1024-65535）。

### Q3: 如何验证数据正确性？

查看日志中的CRC校验和、帧长度、IOD变化。

## 测试工具

### 接收解码脚本
```bash
# 接收3帧并对比原始文件
python tests/decode_receiver.py -H 127.0.0.1 -p 5000 -n 3 -c tests/test_data/ATMO2025322160000_vtec_grid.inx

# 持续接收
python tests/decode_receiver.py -H 127.0.0.1 -p 5000 -n -1
```

### 快速测试
```bash
# 自动启动服务器和客户端，接收3帧后停止
python tests/quick_test.py
```

### 单元测试
```bash
# 系统综合测试
python tests/test_system.py

# INX解析编码测试
python tests/test_inx_parse.py

# TCP收发验证
python tests/test_tcp_transceive.py
```

## 技术参考

- RTKLIB: https://github.com/tomojitakasu/RTKLIB
- CRC-16/XMODEM: Polynomial 0x1021
- IONEX格式: IGS标准格式规范

## 许可证

MIT License
