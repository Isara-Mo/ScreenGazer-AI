"""
视觉小说英语学习翻译工具 - 程序入口
Visual Novel English Learning Translation Tool - Entry Point
"""

import sys
import os
import traceback

# ── DLL 路径修复（Anaconda 环境兼容）──────────────────────────
# 在导入 PySide6 前，将其所在目录置于 PATH 最前，避免 Anaconda
# 的旧版 Qt DLL 被优先加载导致 ImportError。
def _fix_pyside6_dll_path() -> None:
    try:
        import importlib.util
        spec = importlib.util.find_spec("PySide6")
        if spec and spec.submodule_search_locations:
            pyside6_dir = spec.submodule_search_locations[0]
            current_path = os.environ.get("PATH", "")
            if pyside6_dir not in current_path:
                os.environ["PATH"] = pyside6_dir + os.pathsep + current_path
    except Exception:
        pass

_fix_pyside6_dll_path()

# 确保 src 在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("[Startup] 正在初始化 Qt...")
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon

print("[Startup] 正在加载主窗口模块...")
from src.ui.main_window import MainWindow


def main():
    # 高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("VN Translator")
    app.setApplicationDisplayName("视觉小说翻译助手")
    app.setOrganizationName("VNTranslator")

    # 设置应用程序关闭主窗口时自动退出
    app.setQuitOnLastWindowClosed(True)

    try:
        print("[Startup] 正在创建主窗口...")
        window = MainWindow()
        print("[Startup] 正在显示主窗口...")
        window.show()
        window.raise_()
        window.activateWindow()
        print("[Startup] 启动成功！进入事件循环")
        sys.exit(app.exec())

    except Exception as e:
        error_msg = f"程序启动失败:\n\n{e}\n\n{traceback.format_exc()}"
        print(f"[FATAL] {error_msg}", file=sys.stderr)
        try:
            QMessageBox.critical(None, "启动错误", error_msg)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
