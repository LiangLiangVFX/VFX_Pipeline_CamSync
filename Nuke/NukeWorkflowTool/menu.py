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


def _get_builtin_icon(candidates, fallback="Roto.png"):
    """在 Nuke 插件路径中自动校验并返回真实存在的内置图标，确保 100% 显示不留空"""
    plugin_paths = nuke.pluginPath()
    for icon_name in candidates:
        for p in plugin_paths:
            full_p = os.path.join(p, icon_name)
            if os.path.exists(full_p):
                return icon_name
    return fallback


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
# 统一菜单项注册函数 (已隐藏备用 RVM，仅展示三大主力 AI 引擎)
# =============================================================================
def _populate_ll_menu(menu_obj):
    biref_icon = _get_builtin_icon(["RotoPaint.png", "FilterErode.png", "Keyer.png"], "Roto.png")
    sam2mat_icon = _get_builtin_icon(["Cryptomatte.png", "CameraTracker.png", "SmartVector.png", "Primatte.png"], "Tracker.png")

    # 功能 1: 实拍预处理 (Keyer 图标)
    menu_obj.addCommand(
        "实拍预处理与输出UE底板",
        "LiangLiangNukeWorkflow.show_prep_menu()",
        icon="Keyer.png"
    )
    # 功能 2: [AI] BiRefNet 全自动高清万物抠像 (RotoPaint 图标)
    menu_obj.addCommand(
        "[AI] BiRefNet 全自动高清万物抠像 (2K发丝与道具)",
        "LiangLiangNukeWorkflow.show_ai_birefnet_menu()",
        icon=biref_icon
    )
    # 功能 3: [AI] MatAnyone 2 发丝级目标锁定抠像 (Tracker 图标)
    menu_obj.addCommand(
        "[AI] MatAnyone 2 发丝级目标锁定抠像 (CVPR 2026)",
        "LiangLiangNukeWorkflow.show_ai_sam2_menu()",
        icon="Tracker.png"
    )
    # 功能 4: [AI] SAM2Matting 万物发丝级跟踪抠像 (Cryptomatte/CameraTracker 图标)
    menu_obj.addCommand(
        "[AI] SAM2Matting 万物发丝级跟踪抠像 (ECCV 2026)",
        "LiangLiangNukeWorkflow.show_ai_sam2matting_menu()",
        icon=sam2mat_icon
    )
    # 功能 5: UE渲染分层自动预合成与 ID 拆层 (Shuffle 图标)
    menu_obj.addCommand(
        "UE渲染分层自动预合成与ID拆层",
        "LiangLiangNukeWorkflow.show_autocomp_menu()",
        icon="Shuffle.png"
    )
    # 功能 6: 重新载入管线脚本 (Refresh 图标)
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