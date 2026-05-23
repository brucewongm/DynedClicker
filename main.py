"""dyclicker 入口"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gui.app import launch_gui


def main() -> None:
    launch_gui()


if __name__ == "__main__":
    main()
