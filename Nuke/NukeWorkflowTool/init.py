# -*- coding: utf-8 -*-
"""
LiangLiang Nuke Pipeline Plugin Init
"""
import os
import sys
import nuke

current_dir = os.path.dirname(os.path.abspath(__file__)).replace('\\', '/')

if current_dir not in sys.path:
    sys.path.append(current_dir)

nuke.pluginAddPath(current_dir)
if os.path.exists(os.path.join(current_dir, "icons")):
    nuke.pluginAddPath(os.path.join(current_dir, "icons"))