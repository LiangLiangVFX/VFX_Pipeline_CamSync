# -*- coding: utf-8 -*-
"""
LiangLiang Nuke Pipeline Plugin Menu
"""
import nuke

try:
    import LiangLiangNukeWorkflow
    
    # 获取 Nuke 顶部主菜单栏
    nuke_menu = nuke.menu("Nuke")
    
    # 创建一级菜单：UE镜头管线
    pipeline_menu = nuke_menu.addMenu("UE镜头管线", icon="Movie.png")
    
    # 添加子功能 1：制作前实拍预处理
    pipeline_menu.addCommand(
        "1. 制作前: 实拍预处理与输出底板 (生成ue/workarea/bg)", 
        "LiangLiangNukeWorkflow.show_prep_menu()", 
        icon="Write.png"
    )
    
    # 添加子功能 2：渲染后 MRQ 分层组装
    pipeline_menu.addCommand(
        "2. 渲染后: MRQ分层组装与ID拆层 (AutoComper)", 
        "LiangLiangNukeWorkflow.show_autocomp_menu()", 
        icon="Merge.png"
    )

except Exception as e:
    print(f"[CamWorkflow] Nuke 菜单加载异常: {e}")