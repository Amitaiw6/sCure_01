import os
import sys

IO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if IO_DIR not in sys.path:
    sys.path.insert(0, IO_DIR)
