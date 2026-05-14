#!/usr/bin/env python3
"""
用法：
  启动：python serve.py /path/to/file.html [--port 8888]
  关闭：python serve.py --stop [--port 8888]
"""
import argparse
import os
import signal
import socket
import sys
import subprocess

PID_FILE = "/tmp/visualsolver_serve.pid"
PORT_FILE = "/tmp/visualsolver_serve_port"


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def stop_server():
    if not os.path.exists(PID_FILE):
        print("没有正在运行的服务。")
        return
    with open(PID_FILE) as f:
        pid = int(f.read().strip())
    port = ""
    if os.path.exists(PORT_FILE):
        with open(PORT_FILE) as f:
            port = f.read().strip()
    try:
        os.kill(pid, signal.SIGTERM)
        os.remove(PID_FILE)
        if os.path.exists(PORT_FILE):
            os.remove(PORT_FILE)
        print(f"✓ 服务已停止 (PID {pid}, 端口 {port})")
    except ProcessLookupError:
        print(f"进程 {pid} 已不存在，清理 PID 文件。")
        os.remove(PID_FILE)
        if os.path.exists(PORT_FILE):
            os.remove(PORT_FILE)


def start_server(html_path: str, port: int):
    html_path = os.path.abspath(html_path)
    if not os.path.exists(html_path):
        print(f"错误：文件不存在：{html_path}")
        sys.exit(1)

    serve_dir = os.path.dirname(html_path)
    filename = os.path.basename(html_path)

    # 如果已有服务在运行，先停止
    if os.path.exists(PID_FILE):
        print("检测到已有服务在运行，先停止旧服务...")
        stop_server()

    # 后台启动 http.server
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port)],
        cwd=serve_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    with open(PORT_FILE, "w") as f:
        f.write(str(port))

    ip = get_local_ip()
    print(f"✓ 服务已启动 (PID {proc.pid})")
    print(f"  目录：{serve_dir}")
    print(f"  在浏览器打开：http://{ip}:{port}/{filename}")
    print(f"\n  停止服务：python serve.py --stop")


def main():
    parser = argparse.ArgumentParser(description="快速启动/停止 HTML 预览服务")
    parser.add_argument("html", nargs="?", help="HTML 文件路径")
    parser.add_argument("--port", type=int, default=8888, help="端口号（默认 8888）")
    parser.add_argument("--stop", action="store_true", help="停止服务")
    args = parser.parse_args()

    if args.stop:
        stop_server()
    elif args.html:
        start_server(args.html, args.port)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
