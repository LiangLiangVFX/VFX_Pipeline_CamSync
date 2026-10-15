# -*- coding: utf-8 -*-
import os
import sys
import importlib
import nuke

# 确保 ~/.nuke 路径在系统路径中
current_dir = os.path.dirname(os.path.abspath(__file__)).replace('\\', '/')
if current_dir not in sys.path:
    sys.path.append(current_dir)

# 1. 探测自定义图标库目录
icons_dir = os.path.join(current_dir, "icons").replace('\\', '/')
if os.path.exists(icons_dir):
    nuke.pluginAddPath(icons_dir)

# 2. 探测自定义主 Logo
user_main_logo = None
for ext in ['.png', '.jpg', '.jpeg', '.ico']:
    cand = os.path.join(icons_dir, f"icon{ext}").replace('\\', '/')
    if os.path.exists(cand):
        user_main_logo = cand
        break

if not user_main_logo:
    user_main_logo = os.path.join(icons_dir, "icon.png").replace('\\', '/')

# 3. 首次导入或自动更新 LiangLiangNukeWorkflow
try:
    if 'LiangLiangNukeWorkflow' in sys.modules:
        importlib.reload(sys.modules['LiangLiangNukeWorkflow'])
    else:
        import LiangLiangNukeWorkflow
except Exception as e:
    print(f"[LiangLiangVFX] 初始导入 LiangLiangNukeWorkflow 失败: {e}")


# =============================================================================
# 热重载核心函数 (一键同时刷新 LiangLiangNukeWorkflow.py + 左侧栏 + 顶部菜单栏)
# =============================================================================
def reload_liangliang_pipeline():
    try:
        import LiangLiangNukeWorkflow
        importlib.reload(LiangLiangNukeWorkflow)
        print(">> [LiangLiangVFX] LiangLiangNukeWorkflow 核心模块热重载成功！")
    except Exception as e:
        nuke.message(f"LiangLiangNukeWorkflow 重载失败:\n{e}")
        return

    menu_file = os.path.abspath(__file__)
    try:
        # 清空左侧工具栏与顶部主菜单栏的旧条目，防止重复叠加
        nodes_m = nuke.menu("Nodes").findItem("LiangLiangVFX")
        if nodes_m and hasattr(nodes_m, "clearMenu"):
            nodes_m.clearMenu()

        top_m = nuke.menu("Nuke").findItem("LiangLiangVFX")
        if top_m and hasattr(top_m, "clearMenu"):
            top_m.clearMenu()

        with open(menu_file, "r", encoding="utf-8") as f:
            exec(compile(f.read(), menu_file, 'exec'), globals())

        nuke.message("管线脚本已全量热重载成功！\n\n• LiangLiangNukeWorkflow 代码已更新\n• 左侧工具栏与顶部菜单栏已同步刷新")
    except Exception as e:
        nuke.message(f"菜单重载失败:\n{e}")


# =============================================================================
# 统一菜单项注册函数 (同时绑定到 左侧 Nodes 栏 与 顶部 Nuke 主菜单栏)
# =============================================================================
def _populate_ll_menu(menu_obj):
    # 功能 1: 实拍预处理 (Keyer 图标)
    menu_obj.addCommand(
        "实拍预处理与输出UE底板",
        "LiangLiangNukeWorkflow.show_prep_menu()",
        icon="Keyer.png"
    )
    # 功能 2: [AI] RVM 全自动发丝级抠像 (Roto 图标)
    menu_obj.addCommand(
        "[AI] RVM 全自动发丝级抠像",
        "LiangLiangNukeWorkflow.show_ai_rvm_menu()",
        icon="Roto.png"
    )
    # 功能 3: [AI] MatAnyone 2 发丝级目标锁定抠像 (Tracker 图标)
    menu_obj.addCommand(
        "[AI] MatAnyone 2 发丝级目标锁定抠像 (CVPR 2026)",
        "LiangLiangNukeWorkflow.show_ai_sam2_menu()",
        icon="Tracker.png"
    )
    # 功能 4: UE渲染分层自动预合成与 ID 拆层 (Shuffle 图标)
    menu_obj.addCommand(
        "UE渲染分层自动预合成与ID拆层",
        "LiangLiangNukeWorkflow.show_autocomp_menu()",
        icon="Shuffle.png"
    )
    # 功能 5: 重新载入管线脚本 (Refresh 图标)
    menu_obj.addSeparator()
    menu_obj.addCommand(
        "重新载入管线脚本",
        "reload_liangliang_pipeline()",
        icon="Refresh.png"
    )

# 1. 注册到左侧节点工具栏 (Nodes)
toolbar = nuke.menu("Nodes").addMenu("LiangLiangVFX", icon=user_main_logo)
_populate_ll_menu(toolbar)

# 2. 注册到顶部主菜单栏 (Nuke)
topbar = nuke.menu("Nuke").addMenu("LiangLiangVFX")
_populate_ll_menu(topbar)