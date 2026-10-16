# -*- coding: utf-8 -*-
"""快速语法检查（ASCII 路径下运行，避免非 ASCII 路径带来的干扰）"""
import ast
import os
import sys

WIN = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
files = ["main.py", "app/config.py", "app/ui/main_window.py",
         "app/ui/theme.py", "app/ui/history.py", "app/node.py"]
bad = 0
for f in files:
    p = os.path.join(WIN, f)
    try:
        ast.parse(open(p, encoding="utf-8").read())
        print("AST OK  ", f)
    except SyntaxError as e:
        bad += 1
        print("SYNTAX!!", f, e)
print("bad =", bad)
sys.exit(1 if bad else 0)
