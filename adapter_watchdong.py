import subprocess
import time
import signal
import sys
import os

# --- 配置 ---
# 适配器主脚本的文件名
ADAPTER_SCRIPT_FILENAME = "main.py"
# 看门狗脚本所在的目录，也应该是 main.py 所在的目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 适配器主脚本的完整路径
ADAPTER_SCRIPT_PATH = os.path.join(BASE_DIR, ADAPTER_SCRIPT_FILENAME)

# 重启间隔（秒）
# 例如: 6 小时 = 6 * 60 * 60 = 21600 秒
RESTART_INTERVAL_SECONDS = 1 * 60 * 60

# 优雅关闭的等待超时时间（秒）
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 30

# 用于运行适配器脚本的 Python 解释器 (与运行此看门狗脚本的解释器相同)
PYTHON_EXECUTABLE = sys.executable
# --- /配置 ---

# 全局变量，用于跟踪当前运行的适配器进程
current_adapter_process = None

def start_adapter():
    """启动适配器子进程"""
    global current_adapter_process
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 正在启动适配器: {ADAPTER_SCRIPT_PATH}")
    try:
        # 在 main.py 所在的目录作为工作目录来运行它
        process = subprocess.Popen([PYTHON_EXECUTABLE, ADAPTER_SCRIPT_PATH], cwd=BASE_DIR)
        current_adapter_process = process
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 适配器已启动，PID: {process.pid}")
        return process
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 启动适配器时出错: {e}")
        current_adapter_process = None
        return None

def stop_adapter(process_to_stop):
    """停止指定的适配器子进程"""
    if process_to_stop and process_to_stop.poll() is None:  # 检查进程是否仍在运行
        pid = process_to_stop.pid
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 正在停止适配器 (PID: {pid})...")
        try:
            # 发送 SIGINT (Ctrl+C) 信号以触发 main.py 中的 graceful_shutdown
            process_to_stop.send_signal(signal.SIGINT)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 已发送 SIGINT。等待优雅关闭 ({GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS}秒)...")
            process_to_stop.wait(timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 适配器 (PID: {pid}) 已优雅关闭。")
        except subprocess.TimeoutExpired:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 适配器 (PID: {pid}) 优雅关闭超时。正在强制终止...")
            process_to_stop.kill()
            process_to_stop.wait()  # 确保进程资源被回收
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 适配器 (PID: {pid}) 已被强制终止。")
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 停止适配器 (PID: {pid}) 时发生错误: {e}。正在强制终止...")
            try:
                process_to_stop.kill()
                process_to_stop.wait()
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 适配器 (PID: {pid}) 在错误处理中被强制终止。")
            except Exception as e_kill:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 强制终止适配器 (PID: {pid}) 时出错: {e_kill}")
        finally:
            global current_adapter_process
            if current_adapter_process == process_to_stop:
                current_adapter_process = None
    else:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 适配器进程未运行或已被停止。")


def watchdog_shutdown_handler(signum, frame):
    """处理看门狗自身的关闭信号"""
    print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] 看门狗收到信号 {signal.Signals(signum).name}。正在关闭适配器并退出...")
    if current_adapter_process:
        stop_adapter(current_adapter_process)
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 看门狗已退出。")
    sys.exit(0)

if __name__ == "__main__":
    # 注册信号处理函数，以便优雅地关闭看门狗和它管理的适配器进程
    signal.signal(signal.SIGINT, watchdog_shutdown_handler)  # 处理 Ctrl+C
    signal.signal(signal.SIGTERM, watchdog_shutdown_handler) # 处理 kill 命令

    if not os.path.isfile(ADAPTER_SCRIPT_PATH):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 错误: 适配器脚本 '{ADAPTER_SCRIPT_PATH}' 未找到。")
        sys.exit(1)

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 看门狗已启动。监控目标: {ADAPTER_SCRIPT_PATH}")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 适配器将每隔 {RESTART_INTERVAL_SECONDS / 3600:.2f} 小时重启一次。")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 按 Ctrl+C 来停止看门狗和适配器。")

    try:
        while True:
            start_adapter() # 此函数会设置全局变量 current_adapter_process

            if current_adapter_process:
                # 等待指定的时间间隔。
                # 如果在此期间 current_adapter_process 意外终止，这个简单的定时重启逻辑
                # 仍会等到间隔期满再尝试停止（一个可能已不存在的进程）并重启。
                # 这符合“定时启动”的需求，而不是一个崩溃监控器。
                try:
                    time.sleep(RESTART_INTERVAL_SECONDS)
                except InterruptedError: # 被信号中断（例如SIGINT）
                    # 信号处理器 watchdog_shutdown_handler 应该已经处理了退出
                    # 此处可以添加日志，但主要逻辑在信号处理器中
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 看门狗休眠被中断，将由信号处理器完成退出。")
                    # 通常 watchdog_shutdown_handler 会调用 sys.exit()，所以这里可能不会执行到
                    break # 退出 while 循环


                # 只有当 time.sleep 自然完成（未被信号中断）时，才会执行到这里
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 计划重启适配器。")
                # 检查 current_adapter_process 是否仍然存在，因为它可能已被信号处理器清除
                if current_adapter_process:
                    stop_adapter(current_adapter_process) # stop_adapter 会将 current_adapter_process 设为 None
            else:
                # 如果 start_adapter() 失败
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 适配器启动失败。60秒后重试...")
                time.sleep(60) # 等待一段时间再尝试启动

            # 在重启或重试启动之前稍作停顿
            # 仅当 current_adapter_process 为 None 时（表示已停止或启动失败）
            if current_adapter_process is None:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 等待 5 秒后进行下一次操作...")
                time.sleep(5)

    except KeyboardInterrupt:
        # 理论上，SIGINT 应该由 watchdog_shutdown_handler 捕获并处理。
        # 这个块是为了应对一些极端情况。
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] 看门狗主循环被 KeyboardInterrupt 中断。")
        # 确保在退出前清理
        if current_adapter_process and current_adapter_process.poll() is None:
            stop_adapter(current_adapter_process)
        sys.exit(0)
    finally:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 看门狗正在关闭...")
        # 确保如果因为其他原因退出循环，并且适配器仍在运行，则停止它
        if current_adapter_process and current_adapter_process.poll() is None:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 在最终关闭期间确保适配器已停止...")
            stop_adapter(current_adapter_process)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 看门狗已完全停止。")