"""
开发模式启动器。

支持两种模式：
1. 仅 Python 后端（假设前端 dev server 已在 5173 端口运行）
2. 同时启动 Vite dev server + Python 后端

使用方法：
    python run_dev.py              # 模式 1
    python run_dev.py --with-vite  # 模式 2
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"


def start_vite():
    if not (FRONTEND / "node_modules").exists():
        print("[dev] 安装前端依赖 ...")
        subprocess.check_call(["npm", "install", "--no-audit", "--no-fund"], cwd=str(FRONTEND), shell=True)
    print("[dev] 启动 Vite dev server ...")
    # 使用 shell=True 让 Windows 能找到 npm.cmd
    return subprocess.Popen(
        "npm run dev",
        cwd=str(FRONTEND),
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )


def wait_for_vite(timeout=30):
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://127.0.0.1:5173", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-vite", action="store_true", help="同时启动 Vite dev server")
    args = parser.parse_args()

    vite = None
    try:
        if args.with_vite:
            vite = start_vite()
            if not wait_for_vite():
                print("[dev] Vite 启动超时，尝试继续 ...")
            else:
                print("[dev] Vite 已就绪 -> http://127.0.0.1:5173")

        # 启动后端（pywebview 窗口）
        from backend.main import main as backend_main
        return backend_main()
    finally:
        if vite is not None:
            vite.terminate()
            try:
                vite.wait(timeout=5)
            except subprocess.TimeoutExpired:
                vite.kill()


if __name__ == "__main__":
    sys.exit(main() or 0)
