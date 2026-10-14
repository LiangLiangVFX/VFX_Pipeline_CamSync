# -*- coding: utf-8 -*-
import os
import nuke
import LiangLiangNukeWorkflow

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

toolbar = nuke.menu("Nodes").addMenu("LiangLiangVFX", icon=user_main_logo)

# 功能 1: 实拍预处理 (Keyer 图标)
toolbar.addCommand(
    "实拍预处理与输出UE底板",
    "LiangLiangNukeWorkflow.show_prep_menu()",
    icon="Keyer.png"
)

# 功能 2: [AI] RVM 全自动发丝级抠像 (Roto 图标)
toolbar.addCommand(
    "[AI] RVM 全自动发丝级抠像",
    "LiangLiangNukeWorkflow.show_ai_rvm_menu()",
    icon="Roto.png"
)

# 功能 3: [AI] SAM 2 交互式精准跟踪遮罩 (Tracker 图标)
toolbar.addCommand(
    "[AI] SAM 2 交互式精准跟踪遮罩",
    "LiangLiangNukeWorkflow.show_ai_sam2_menu()",
    icon="Tracker.png"
)

# 功能 4: UE渲染分层自动预合成与 ID 拆层 (Shuffle 图标)
toolbar.addCommand(
    "UE渲染分层自动预合成与ID拆层",
    "LiangLiangNukeWorkflow.show_autocomp_menu()",
    icon="Shuffle.png"
)