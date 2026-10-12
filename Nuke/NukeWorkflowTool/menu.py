# -*- coding: utf-8 -*-
import os
import nuke
import LiangLiangNukeWorkflow

# 1. 注册 icons 目录并绑定主 Logo (锁定 icon.png)
current_dir = os.path.dirname(os.path.abspath(__file__)).replace('\\', '/')
icons_dir = os.path.join(current_dir, "icons").replace('\\', '/')

if os.path.exists(icons_dir):
    nuke.pluginAddPath(icons_dir)

user_main_logo = None
for ext in ['.png', '.jpg', '.jpeg', '.ico']:
    cand = os.path.join(icons_dir, f"icon{ext}").replace('\\', '/')
    if os.path.exists(cand):
        user_main_logo = cand
        break

if not user_main_logo:
    user_main_logo = os.path.join(icons_dir, "icon.png").replace('\\', '/')

# 2. 注册工具栏与两大核心功能 (菜单二图标已换为 Shuffle.png)
toolbar = nuke.menu("Nodes").addMenu("LiangLiangVFX", icon=user_main_logo)

# 功能 1: 实拍预处理与输出UE底板
toolbar.addCommand(
    "实拍预处理与输出UE底板",
    "LiangLiangNukeWorkflow.show_prep_menu()",
    icon="Keyer.png"
)

# 功能 2: UE渲染分层自动预合成与ID拆层 (单层/多层合一，使用多层 Shuffle 图标)
toolbar.addCommand(
    "UE渲染分层自动预合成与ID拆层",
    "LiangLiangNukeWorkflow.show_autocomp_menu()",
    icon="Shuffle.png"
)