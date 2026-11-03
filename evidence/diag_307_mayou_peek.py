# -*- coding: utf-8 -*-
"""只读：打印码友书阳 byg.js 指定区间（去掉 writeln 包装），用于人工判断半波区块位置。"""
import re
import sys

path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Administrator\AppData\Local\Temp\byg.js"
ranges = [(15600, 16300), (17400, 18100), (16600, 17200)]
text = open(path, encoding="utf-8", errors="replace").read()
for a, b in ranges:
    s = text[a:b]
    s = re.sub(r'document\.writeln\("', "|", s)
    s = s.replace('");', "")
    s = s.replace("<br>", " ⏎ ")
    print("===== %d-%d =====" % (a, b))
    print(s)
    print()
