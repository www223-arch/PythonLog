from typing import Any, Dict, Optional, Tuple

from data_sources.manager import (
    create_file_source,
    create_serial_source,
    create_tcp_source,
    create_udp_source,
)


def build_data_source(source_type: str, config: Dict[str, Any]) -> Tuple[Any, str, Optional[str]]:
    """根据规范化配置构建数据源。

    Returns:
        (data_source, success_log, justfloat_mode)
    """
    if source_type == "UDP":
        host = config["host"]
        port = config["port"]
        header = config["header"]
        send_host = config["send_host"]
        send_port = config["send_port"]

        data_source = create_udp_source(host, port)
        data_source.set_send_target(send_host, send_port)
        return data_source, f"已连接到UDP {host}:{port}，数据校验头: {header}", None

    if source_type == "TCP":
        mode = config["mode"]
        local_host = config["local_host"]
        local_port = config["local_port"]
        target_host = config["target_host"]
        target_port = config["target_port"]

        if mode == "client":
            data_source = create_tcp_source(
                host=local_host,
                port=local_port,
                mode='client',
                peer_host=target_host,
                peer_port=target_port,
            )
            return data_source, f"已连接TCP服务端 {target_host}:{target_port}，协议: UDP同格式", None

        data_source = create_tcp_source(host=local_host, port=local_port, mode='server')
        return data_source, f"已监听TCP {local_host}:{local_port}，协议: UDP同格式", None

    if source_type == "串口":
        serial_port = config["serial_port"]
        baudrate = config["baudrate"]
        protocol = config["protocol"]
        header = config.get("header", "")

        if protocol == 'text':
            data_source = create_serial_source(serial_port, baudrate, protocol, header)
            return data_source, f"已连接到串口 {serial_port} @ {baudrate}bps，协议: 文本协议，数据校验头: {header}", None

        if protocol in ['justfloat', 'firewater']:
            justfloat_mode = config["justfloat_mode"]
            delta_t = config["delta_t"]
            data_source = create_serial_source(serial_port, baudrate, protocol, '', justfloat_mode, delta_t)
            return data_source, f"已连接到串口 {serial_port} @ {baudrate}bps，协议: {protocol.capitalize()}", justfloat_mode

        data_source = create_serial_source(serial_port, baudrate, 'rawdata', '')
        return data_source, f"已连接到串口 {serial_port} @ {baudrate}bps，协议: Rawdata", None

    # 文件
    file_path = config["file_path"]
    protocol = config["protocol"]
    header = config.get("header", "")

    if protocol == 'text':
        data_source = create_file_source(file_path, protocol, header)
        return data_source, f"已连接到文件 {file_path}，协议: 文本协议，数据校验头: {header}", None

    if protocol == 'csv':
        data_source = create_file_source(file_path, 'csv', '')
        return data_source, f"已连接到文件 {file_path}，协议: CSV（需与导出CSV表头一致）", None

    if protocol == 'justfloat':
        justfloat_mode = config["justfloat_mode"]
        delta_t = config["delta_t"]
        data_source = create_file_source(file_path, protocol, '', justfloat_mode, delta_t)
        return data_source, f"已连接到文件 {file_path}，协议: Justfloat", justfloat_mode

    data_source = create_file_source(file_path, 'rawdata', '')
    return data_source, f"已连接到文件 {file_path}，协议: Rawdata", None
