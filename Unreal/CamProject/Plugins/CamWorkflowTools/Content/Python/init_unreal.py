# -*- coding: utf-8 -*-
"""
CamWorkflowTools 启动入口：精准挂载至 UE 5.4 顶部主工具栏 (纯Python免编译稳定版)
Author: LiangLiangArtist
"""
import unreal

def open_cam_importer_widget():
    """打开 EUW 面板 (符合 UE 5.4 PackageName 规范)"""
    widget_pkg_path = "/CamWorkflowTools/EUW_UECamImporter"
    
    # 兼容回退：如果资产还在 /Game 目录下
    if not unreal.EditorAssetLibrary.does_asset_exist(widget_pkg_path):
        widget_pkg_path = "/Game/EUW_UECamImporter"

    widget_asset = unreal.EditorAssetLibrary.load_asset(widget_pkg_path)
    if widget_asset:
        editor_subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
        editor_subsystem.spawn_and_register_tab(widget_asset)
        print("[CamWorkflowTools] 成功呼出镜头组装面板！")
    else:
        unreal.EditorDialog.show_message("提示", f"未能找到 UI 微件资产:\n{widget_pkg_path}\n请确认已将其移至插件 Content 目录", unreal.AppMsgType.OK)

def register_toolbar_button():
    """使用 ToolMenus 将按钮挂载进顶部主工具栏"""
    menus = unreal.ToolMenus.get()

    # 定位 UE 5.4 顶部主工具栏
    target_menu_names = [
        "LevelEditor.LevelEditorToolBar.PlayToolBar",
        "LevelEditor.LevelEditorToolBar.User",
        "LevelEditor.LevelEditorToolBar"
    ]
    
    toolbar = None
    for m_name in target_menu_names:
        toolbar = menus.find_menu(m_name)
        if toolbar:
            break

    if not toolbar:
        print("[CamWorkflowTools] 警告: 未找到合适的顶部工具栏位置")
        return

    entry_name = unreal.Name("OpenCamImporterBtn")
    section_name = unreal.Name("CamPipelineSection")

    # 1. 严格使用 TOOL_BAR_BUTTON 类型，杜绝 EMultiBlockType 警告
    entry = unreal.ToolMenuEntry(
        name=entry_name,
        type=unreal.MultiBlockType.TOOL_BAR_BUTTON
    )
    
    entry.set_label(unreal.Text("镜头装配"))
    entry.set_tool_tip(unreal.Text("点击打开 Maya 镜头交付与自动化组装面板"))

    # 2. 绑定 Python 点击触发命令
    entry.set_string_command(
        type=unreal.ToolMenuStringCommandType.PYTHON,
        custom_type="",
        string="import init_unreal; init_unreal.open_cam_importer_widget()"
    )

    # 3. 锁定官方高清电影摄像机图标 (免编译、绝无透明/空白异常)
    entry.set_icon(unreal.Name("EditorStyle"), unreal.Name("ClassIcon.CineCameraActor"))

    # 4. 挂载进工具栏并强制重绘刷新
    toolbar.add_menu_entry(section_name, entry)
    menus.refresh_all_widgets()
    print("[CamWorkflowTools] 顶部工具栏按钮已完美挂载！")

# 启动引擎或重新加载脚本时自动执行
try:
    register_toolbar_button()
except Exception as e:
    print(f"[CamWorkflowTools] 挂载按钮失败: {e}")