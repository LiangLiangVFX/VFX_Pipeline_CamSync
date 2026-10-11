# -*- coding: utf-8 -*-
import os
import nuke
import LiangLiangNukeWorkflow

# -------------------------------------------------------------------------
# 1. 注册 icons 目录并绑定主 Logo (锁定 icon.png)
# -------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__)).replace('\\', '/')
icons_dir = os.path.join(current_dir, "icons").replace('\\', '/')

if os.path.exists(icons_dir):
    nuke.pluginAddPath(icons_dir)

# 寻找主图标 icon.png (支持常见格式)
user_main_logo = None
for ext in ['.png', '.jpg', '.jpeg', '.ico']:
    cand = os.path.join(icons_dir, f"icon{ext}").replace('\\', '/')
    if os.path.exists(cand):
        user_main_logo = cand
        break

if not user_main_logo:
    user_main_logo = os.path.join(icons_dir, "icon.png").replace('\\', '/')


# -------------------------------------------------------------------------
# 2. 注册工具栏与菜单 (恢复 Nuke 原生默认图标尺寸)
# -------------------------------------------------------------------------
toolbar = nuke.menu("Nodes").addMenu("LiangLiangVFX", icon=user_main_logo)

toolbar.addCommand(
    "实拍预处理与输出UE底板",
    "LiangLiangNukeWorkflow.show_prep_menu()",
    icon="Keyer.png"
)

toolbar.addCommand(
    "UE渲染分层（单层）自动预合成与ID拆层",
    "LiangLiangNukeWorkflow.show_autocomp_menu()",
    icon="Merge.png"
)