# -*- coding: utf-8 -*-
"""
Maya -> UE 镜头交付标准工具 (智能向上嗅探 ue/workarea 交付路径版)
Author: LiangLiangArtist
Contact: liangliangvfx@gmail.com
"""

import os
import re
import subprocess
import maya.cmds as cmds
import maya.mel as mel

class MayaToUECamExporterUI(object):
    def __init__(self):
        self.win_name = "MayaToUECamExporter_Layout_Win"
        self.ref_dummy_grp = "UE_Mannequin_Ref_TempGrp"
        self.interactive_scale_grp = "UE_Interactive_Scale_Pivot_Grp"
        self.original_grp_pos = None
        self.show_ui()

    def get_readable_fps(self):
        time_unit = cmds.currentUnit(query=True, time=True)
        fps_map = {
            'film': '24 fps (Film)',
            'pal': '25 fps (PAL)',
            'ntsc': '30 fps (NTSC)',
            'show': '48 fps',
            'palf': '50 fps',
            'ntscf': '60 fps',
            '23.976fps': '23.976 fps',
            '24fps': '24 fps',
            '25fps': '25 fps',
            '29.97fps': '29.97 fps',
            '30fps': '30 fps',
            '48fps': '48 fps',
            '50fps': '50 fps',
            '59.94fps': '59.94 fps',
            '60fps': '60 fps',
            'game': '15 fps'
        }
        return fps_map.get(time_unit, f"{time_unit}")

    def resolve_default_export_dir(self, scene_path):
        """
        向上回溯检测 UE 规范目录：
        路径规范：.../{ShotID}/ue/workarea/
        若向上逐级遍历找到已存在的 ue/workarea，则优先使用；
        否则兜底默认保存至当前 Maya 工程同级文件夹。
        """
        if not scene_path:
            return cmds.workspace(query=True, rootDirectory=True).replace('\\', '/')

        current_dir = os.path.normpath(os.path.dirname(scene_path)).replace('\\', '/')
        fallback_dir = current_dir

        # 向上回溯最多 6 层，搜寻 ue/workarea 结构
        check_dir = current_dir
        for _ in range(6):
            target_ue_workarea = os.path.normpath(os.path.join(check_dir, "ue", "workarea")).replace('\\', '/')
            if os.path.exists(target_ue_workarea) and os.path.isdir(target_ue_workarea):
                print(f"[CamExporter] 成功智能嗅探到 UE 工作区目录: {target_ue_workarea}")
                return target_ue_workarea

            # 如果当前目录名本身就是 workarea 且其父级为 ue
            if os.path.basename(check_dir).lower() == "workarea":
                parent = os.path.basename(os.path.dirname(check_dir)).lower()
                if parent == "ue" and os.path.exists(check_dir):
                    return check_dir

            parent_dir = os.path.dirname(check_dir)
            if parent_dir == check_dir:
                break
            check_dir = parent_dir

        print(f"[CamExporter] 未检测到 ue/workarea 文件夹，回退至工程同级目录: {fallback_dir}")
        return fallback_dir

    def show_ui(self):
        if cmds.window(self.win_name, exists=True):
            cmds.deleteUI(self.win_name)

        self.win = cmds.window(
            self.win_name, 
            title="Maya -> UE 镜头交付工具 [LiangLiangArtist]", 
            widthHeight=(410, 665), 
            sizeable=True
        )
        
        main_layout = cmds.columnLayout(adjustableColumn=True, rowSpacing=4, columnOffset=["both", 12])
        
        cmds.separator(height=5, style='none')
        cmds.text(label="【 Maya -> UE 镜头交付工具 】", font="boldLabelFont", align="center")
        cmds.separator(height=4, style='in')

        # ----------------- 区域 1：镜头基本信息与帧率规范 -----------------
        scene_path = cmds.file(query=True, sceneName=True)
        shot_name, ep_name, is_empty_scene = self.parse_shot_info(scene_path)

        orig_start_f = int(cmds.playbackOptions(query=True, minTime=True))
        orig_end_f = int(cmds.playbackOptions(query=True, maxTime=True))
        duration = orig_end_f - orig_start_f + 1

        plate_start_default = 1001 if orig_start_f in [0, 1] else orig_start_f
        plate_end_default = plate_start_default + duration - 1

        fps_text = self.get_readable_fps()

        cmds.frameLayout(label=" 镜头基本信息与帧率规范 ", collapsable=False, marginWidth=6, marginHeight=5)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=2)

        # 空场景显式黄色告警提示条
        if is_empty_scene:
            cmds.text(
                label="⚠️ 当前为未命名的空工程，未能识别镜头信息，请核对输入", 
                backgroundColor=[0.42, 0.35, 0.18], 
                height=22,
                align="center",
                font="boldLabelFont"
            )
            cmds.separator(height=2, style='none')
        
        self.shot_field = cmds.textFieldGrp(
            label="镜头号 (Shot):", 
            text=shot_name, 
            placeholderText="如: 2180 (空场景请手动输入)",
            columnWidth2=(120, 235),
            changeCommand=lambda x: self.update_preview_lbl()
        )
        self.ep_field = cmds.textFieldGrp(
            label="集数 (Episode):", 
            text=ep_name, 
            placeholderText="如: EP28",
            columnWidth2=(120, 235)
        )
        self.scene_frame_grp = cmds.intFieldGrp(
            numberOfFields=2, 
            label="Maya 原始帧区间:", 
            value1=orig_start_f, 
            value2=orig_end_f, 
            enable=False,
            columnWidth3=(120, 105, 105)
        )
        self.fps_field = cmds.textFieldGrp(
            label="原始跟踪数据帧速率:", 
            text=fps_text, 
            enable=False,
            columnWidth2=(120, 235)
        )
        self.total_frames_field = cmds.textFieldGrp(
            label="跟踪文件总帧数:", 
            text=f"{duration} 帧 (Frames)", 
            enable=False,
            columnWidth2=(120, 235)
        )
        self.plate_frame_grp = cmds.intFieldGrp(
            numberOfFields=2, 
            label="素材帧命名区间:", 
            value1=plate_start_default, 
            value2=plate_end_default, 
            columnWidth3=(120, 105, 105),
            changeCommand=lambda x: self.update_preview_lbl()
        )
        
        display_shot = shot_name if shot_name else "Shot"
        self.preview_lbl = cmds.text(
            label=f"输出命名: cam{display_shot}_{plate_start_default}_{plate_end_default}.fbx (内部平移至 1~{duration} 帧)", 
            align="center", 
            font="obliqueLabelFont"
        )
        cmds.setParent(main_layout)

        # ----------------- 区域 2：场景缩放与比例对准 -----------------
        cmds.frameLayout(label=" 场景缩放与比例对准 (UE 厘米标准) ", collapsable=False, marginWidth=6, marginHeight=5)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=3)
        
        # 按钮三等分均分布局 (选集打组 -> 参考人偶 -> 清理人偶)
        btn_form = cmds.formLayout(numberOfDivisions=100)
        btn_grp = cmds.button(label="📦 选集打组 (Ctrl+G)", height=25, backgroundColor=[0.25, 0.38, 0.42], command=self.do_native_ctrl_g)
        btn_dummy = cmds.button(label="🧍 生成参考人偶", height=25, backgroundColor=[0.3, 0.35, 0.42], command=self.spawn_ue_dummy)
        btn_clean = cmds.button(label="❌ 清理人偶", height=25, command=self.remove_ue_dummy)

        cmds.formLayout(
            btn_form, edit=True,
            attachForm=[
                (btn_grp, 'top', 0), (btn_grp, 'bottom', 0), (btn_grp, 'left', 0),
                (btn_dummy, 'top', 0), (btn_dummy, 'bottom', 0),
                (btn_clean, 'top', 0), (btn_clean, 'bottom', 0), (btn_clean, 'right', 0)
            ],
            attachPosition=[
                (btn_grp, 'right', 2, 33),
                (btn_dummy, 'left', 2, 33), (btn_dummy, 'right', 2, 66),
                (btn_clean, 'left', 2, 66)
            ]
        )
        cmds.setParent('..')

        cmds.button(
            label="🎯 选跟踪人偶 -> 吸附标准模型并对齐轴心", 
            height=26, 
            backgroundColor=[0.32, 0.42, 0.52], 
            command=self.align_pivot_and_dummy_to_target
        )

        scale_form = cmds.formLayout(numberOfDivisions=100)
        btn_1x = cmds.button(label="🔄 1x (原比例)", height=23, command=lambda x: self.set_scale_val(1))
        btn_100x = cmds.button(label="🚀 100x (标准放大)", height=23, command=lambda x: self.set_scale_val(100))
        lbl_hint = cmds.text(label="拖动滑块实时缩放 ➔", align="center")

        cmds.formLayout(
            scale_form, edit=True,
            attachForm=[
                (btn_1x, 'top', 0), (btn_1x, 'bottom', 0), (btn_1x, 'left', 0),
                (btn_100x, 'top', 0), (btn_100x, 'bottom', 0),
                (lbl_hint, 'top', 0), (lbl_hint, 'bottom', 0), (lbl_hint, 'right', 0)
            ],
            attachPosition=[
                (btn_1x, 'right', 2, 33),
                (btn_100x, 'left', 2, 33), (btn_100x, 'right', 2, 66),
                (lbl_hint, 'left', 2, 66)
            ]
        )
        cmds.setParent('..')

        # 自动继承场景中已存在的缩放组数值
        initial_scale_val = 100
        initial_max_slider = 2000
        if cmds.objExists(self.interactive_scale_grp):
            try:
                scene_s = int(round(cmds.getAttr(f"{self.interactive_scale_grp}.scaleX")))
                if scene_s > 0:
                    initial_scale_val = scene_s
                    if initial_scale_val > initial_max_slider:
                        initial_max_slider = initial_scale_val * 2
            except:
                pass

        self.scale_slider = cmds.intSliderGrp(
            label="缩放倍数(整数):",
            field=True,
            minValue=1,
            maxValue=initial_max_slider,
            fieldMinValue=1,
            fieldMaxValue=1000000,
            value=initial_scale_val,
            step=1,
            columnWidth3=(120, 60, 180),
            changeCommand=self.on_scale_slider_committed
        )
        cmds.setParent(main_layout)

        # ----------------- 区域 3：虚幻空间重定向 (按需选用) -----------------
        cmds.frameLayout(label=" 虚幻空间坐标重定向 (可选：解决进UE原点偏远乱晃) ", collapsable=False, marginWidth=6, marginHeight=5)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=3)
        
        recenter_form = cmds.formLayout(numberOfDivisions=100)
        btn_recenter_cam = cmds.button(
            label="🧭 相机首帧水平归零", 
            height=26, 
            backgroundColor=[0.35, 0.45, 0.40],
            annotation="【按需点击】将第1帧相机对准世界(0,0)，在UE挂Actor不会乱晃。不点则保持原位不变！",
            command=self.recenter_cam_start_to_origin
        )
        btn_recenter_sel = cmds.button(
            label="📍 选中目标对准零点", 
            height=26, 
            backgroundColor=[0.38, 0.40, 0.48],
            annotation="【按需点击】单选场景中特定台阶/简模点，将其对准原点",
            command=self.recenter_selection_to_origin
        )
        btn_restore = cmds.button(
            label="↩️ 还原原始世界坐标", 
            height=26, 
            backgroundColor=[0.45, 0.35, 0.35],
            annotation="点击可一键撤销归零操作，完全还原跟踪文件原始绝对坐标",
            command=self.restore_original_coordinates
        )

        cmds.formLayout(
            recenter_form, edit=True,
            attachForm=[
                (btn_recenter_cam, 'top', 0), (btn_recenter_cam, 'bottom', 0), (btn_recenter_cam, 'left', 0),
                (btn_recenter_sel, 'top', 0), (btn_recenter_sel, 'bottom', 0),
                (btn_restore, 'top', 0), (btn_restore, 'bottom', 0), (btn_restore, 'right', 0)
            ],
            attachPosition=[
                (btn_recenter_cam, 'right', 2, 33),
                (btn_recenter_sel, 'left', 2, 33), (btn_recenter_sel, 'right', 2, 66),
                (btn_restore, 'left', 2, 66)
            ]
        )
        cmds.setParent('..')
        cmds.setParent(main_layout)

        # ----------------- 区域 4：资产输出配置 -----------------
        cmds.frameLayout(label=" 导出发布选项 ", collapsable=False, marginWidth=6, marginHeight=5)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=3)

        # 智能匹配导出目录：优先 ue/workarea，兜底为 Maya 自身同级目录
        default_dir = self.resolve_default_export_dir(scene_path)

        cmds.rowLayout(numberOfColumns=3, columnWidth3=(120, 195, 55), adjustableColumn=2)
        cmds.text(label="导出路径:  ", align="right", width=120)
        self.path_field = cmds.textField(text=default_dir)
        cmds.button(label="📂 浏览..", width=55, command=self.browse_dir)
        cmds.setParent('..')

        self.export_mesh_chk = cmds.checkBox(
            label="同时导出选中的匹配简模/点云 (自动排除参考人偶)", 
            value=False
        )
        cmds.setParent(main_layout)

        # ----------------- 底部主按钮与完整作者信息 -----------------
        cmds.separator(height=3, style='none')
        cmds.button(
            label="一键打包导出并输出目录", 
            height=38, 
            backgroundColor=[0.24, 0.46, 0.33], 
            command=self.do_export
        )
        
        cmds.separator(height=3, style='none')
        cmds.text(label="Pipeline Tool developed by LiangLiangArtist", align="center", font="obliqueLabelFont")
        cmds.text(label="Contact: liangliangvfx@gmail.com", align="center", font="smallPlainLabelFont")
        cmds.separator(height=4, style='none')

        cmds.showWindow(self.win)

    def parse_shot_info(self, scene_path):
        """解析工程名。若为空场景，返回空值与空场景标记，不强行填入假镜头"""
        if not scene_path:
            return "", "", True

        shot, ep = "", ""
        file_name = os.path.splitext(os.path.basename(scene_path))[0]
        
        ep_match = re.search(r'(ep[_\-]?\d+)', file_name, re.IGNORECASE)
        if ep_match:
            ep = ep_match.group(1).upper().replace('_', '').replace('-', '')

        cleaned_name = re.sub(r'[_\-]v\d+', '', file_name, flags=re.IGNORECASE)
        cleaned_name = re.sub(r'[_\-]version\d+', '', cleaned_name, flags=re.IGNORECASE)

        ep_shot_match = re.search(r'ep[_\-]?\d+[_\-](\d{3,5})', file_name, re.IGNORECASE)
        if ep_shot_match:
            shot = ep_shot_match.group(1)
        else:
            tokens = re.split(r'[_\-\s]+', cleaned_name)
            found_shot = None
            for token in tokens:
                if token.isdigit() and 3 <= len(token) <= 5:
                    if ep and token not in ep:
                        found_shot = token
                        break
                    elif not ep:
                        found_shot = token
                        break
            if found_shot:
                shot = found_shot
            else:
                shot_matches = re.findall(r'(\d{3,5})', cleaned_name)
                if shot_matches:
                    for sm in reversed(shot_matches):
                        if ep and sm not in ep:
                            shot = sm
                            break
                        elif not ep:
                            shot = sm
                            break

        is_empty = (not shot and not ep)
        return shot, ep, is_empty

    def recenter_cam_start_to_origin(self, *args):
        src_cam, _ = self.find_target_camera()
        if not src_cam:
            cmds.confirmDialog(title="提示", message="请先选定跟踪相机！", button=["好的"], icon="warning")
            return

        if not cmds.objExists(self.interactive_scale_grp):
            self.do_native_ctrl_g()

        if not cmds.objExists(self.interactive_scale_grp):
            return

        if self.original_grp_pos is None:
            self.original_grp_pos = cmds.xform(self.interactive_scale_grp, query=True, worldSpace=True, translation=True)

        orig_start = cmds.intFieldGrp(self.scene_frame_grp, query=True, value1=True)
        cur_t = cmds.currentTime(query=True)
        cmds.currentTime(orig_start)
        cam_pos = cmds.xform(src_cam, query=True, worldSpace=True, translation=True)
        cmds.currentTime(cur_t)

        delta_x = -cam_pos[0]
        delta_z = -cam_pos[2]

        grp_pos = cmds.xform(self.interactive_scale_grp, query=True, worldSpace=True, translation=True)
        cmds.xform(self.interactive_scale_grp, worldSpace=True, translation=[grp_pos[0] + delta_x, grp_pos[1], grp_pos[2] + delta_z])

        if cmds.objExists(self.ref_dummy_grp):
            d_pos = cmds.xform(self.ref_dummy_grp, query=True, worldSpace=True, translation=True)
            cmds.xform(self.ref_dummy_grp, worldSpace=True, translation=[d_pos[0] + delta_x, d_pos[1], d_pos[2] + delta_z])

        cmds.inViewMessage(
            amg='已将 <hl>相机首帧水平坐标归零</hl>！相机与简模相对运动保持 100% 无损。若需原位可点【还原】。', 
            pos='topCenter', 
            fade=True
        )

    def recenter_selection_to_origin(self, *args):
        sel = cmds.ls(selection=True, long=True) or []
        candidates = [s for s in sel if self.ref_dummy_grp not in s and self.interactive_scale_grp != s]
        if not candidates:
            cmds.confirmDialog(title="提示", message="请在场景中先选中一个你想作为世界原点的物体或顶点！", button=["好的"], icon="information")
            return

        if not cmds.objExists(self.interactive_scale_grp):
            self.do_native_ctrl_g()

        if not cmds.objExists(self.interactive_scale_grp):
            return

        if self.original_grp_pos is None:
            self.original_grp_pos = cmds.xform(self.interactive_scale_grp, query=True, worldSpace=True, translation=True)

        target_obj = candidates[0]
        bbox = cmds.exactWorldBoundingBox(target_obj)
        target_center = [(bbox[0] + bbox[3]) * 0.5, bbox[1], (bbox[2] + bbox[5]) * 0.5]

        delta_x = -target_center[0]
        delta_y = -target_center[1]
        delta_z = -target_center[2]

        grp_pos = cmds.xform(self.interactive_scale_grp, query=True, worldSpace=True, translation=True)
        cmds.xform(self.interactive_scale_grp, worldSpace=True, translation=[grp_pos[0] + delta_x, grp_pos[1] + delta_y, grp_pos[2] + delta_z])

        if cmds.objExists(self.ref_dummy_grp):
            cmds.xform(self.ref_dummy_grp, worldSpace=True, translation=[0, 0, 0])

        cmds.inViewMessage(amg='已将所选目标基准点 <hl>对齐世界零点 (0,0,0)</hl>！', pos='topCenter', fade=True)

    def restore_original_coordinates(self, *args):
        if self.original_grp_pos and cmds.objExists(self.interactive_scale_grp):
            cmds.xform(self.interactive_scale_grp, worldSpace=True, translation=self.original_grp_pos)
            cmds.inViewMessage(amg='已 <hl>100% 还原为原始世界坐标位置</hl>！与简模原位保持绝对一致。', pos='topCenter', fade=True)
        else:
            cmds.inViewMessage(amg='当前场景本就在原始世界坐标状态，无需还原。', pos='topCenter', fade=True)

    def align_pivot_and_dummy_to_target(self, *args):
        sel = cmds.ls(selection=True, long=True) or []
        target_candidates = [s for s in sel if self.ref_dummy_grp not in s and self.interactive_scale_grp != s]
        
        if not target_candidates:
            cmds.confirmDialog(
                title="选择提示", 
                message="请先在场景中【单选跟踪师自带的参考物/人偶】！\n然后再次点击此按钮即可完成吸附对准。", 
                button=["好的"], 
                icon="information"
            )
            return

        target_obj = target_candidates[0]
        bbox = cmds.exactWorldBoundingBox(target_obj)
        foot_x = (bbox[0] + bbox[3]) * 0.5
        foot_y = bbox[1]
        foot_z = (bbox[2] + bbox[5]) * 0.5

        if cmds.objExists(self.interactive_scale_grp):
            cmds.xform(self.interactive_scale_grp, worldSpace=True, pivots=[foot_x, foot_y, foot_z])

        if cmds.objExists(self.ref_dummy_grp):
            dummy_bbox = cmds.exactWorldBoundingBox(self.ref_dummy_grp)
            dummy_foot_y = dummy_bbox[1]
            cur_pos = cmds.xform(self.ref_dummy_grp, query=True, worldSpace=True, translation=True)
            offset_y = cur_pos[1] - dummy_foot_y
            cmds.xform(self.ref_dummy_grp, worldSpace=True, translation=[foot_x, foot_y + offset_y, foot_z])
        else:
            self.spawn_ue_dummy()
            if cmds.objExists(self.ref_dummy_grp):
                dummy_bbox = cmds.exactWorldBoundingBox(self.ref_dummy_grp)
                dummy_foot_y = dummy_bbox[1]
                cur_pos = cmds.xform(self.ref_dummy_grp, query=True, worldSpace=True, translation=True)
                offset_y = cur_pos[1] - dummy_foot_y
                cmds.xform(self.ref_dummy_grp, worldSpace=True, translation=[foot_x, foot_y + offset_y, foot_z])

        cmds.inViewMessage(
            amg='已完成 <hl>轴心对齐 + 人偶吸附</hl>！现在调整缩放，物体将原地缩放，小人不再飞走！', 
            pos='topCenter', 
            fade=True
        )

    def update_preview_lbl(self):
        shot = cmds.textFieldGrp(self.shot_field, query=True, text=True).strip() or "Shot"
        p_start = cmds.intFieldGrp(self.plate_frame_grp, query=True, value1=True)
        p_end = cmds.intFieldGrp(self.plate_frame_grp, query=True, value2=True)
        orig_s = cmds.intFieldGrp(self.scene_frame_grp, query=True, value1=True)
        orig_e = cmds.intFieldGrp(self.scene_frame_grp, query=True, value2=True)
        duration = orig_e - orig_s + 1
        
        cmds.textFieldGrp(self.total_frames_field, edit=True, text=f"{duration} 帧 (Frames)")
        cmds.textFieldGrp(self.fps_field, edit=True, text=self.get_readable_fps())
        cmds.text(self.preview_lbl, edit=True, label=f"输出命名: cam{shot}_{p_start}_{p_end}.fbx (内部平移至 1~{duration} 帧)")

    def fix_viewport_clipping(self):
        cameras = cmds.ls(type='camera') or []
        for c in cameras:
            try:
                cmds.setAttr(f"{c}.farClipPlane", 10000000.0)
                cmds.setAttr(f"{c}.nearClipPlane", 1.0)
            except:
                pass

    def get_dummy_file_path(self):
        possible_dirs = []
        try:
            cur_script = os.path.abspath(__file__)
            possible_dirs.append(os.path.dirname(cur_script))
        except:
            pass

        user_script_dir = cmds.internalVar(userScriptDir=True)
        possible_dirs.append(user_script_dir)
        user_home = os.path.expanduser('~')
        possible_dirs.append(os.path.join(user_home, "Documents", "maya", "scripts"))
        possible_dirs.append(os.path.join(user_home, "Documents", "maya", "2023", "scripts"))
        possible_dirs.append(os.path.join(user_home, "Documents", "maya", "2023", "zh_CN", "scripts"))
        possible_dirs.append(os.path.join(user_home, "Documents", "maya", "2024", "scripts"))
        possible_dirs.append(os.path.join(user_home, "Documents", "maya", "2024", "zh_CN", "scripts"))

        scene_dir = cmds.workspace(query=True, rootDirectory=True)
        if scene_dir:
            possible_dirs.append(scene_dir)

        for d in possible_dirs:
            if not d: continue
            for name in ["SM_Pose.fbx", "SM_Pose.obj", "sm_pose.fbx", "sm_pose.obj"]:
                chk_path = os.path.join(d, name).replace('\\', '/')
                if os.path.exists(chk_path):
                    return chk_path
        return None

    def spawn_ue_dummy(self, *args):
        self.remove_ue_dummy()
        
        if not cmds.pluginInfo('fbxmaya', query=True, loaded=True):
            try: cmds.loadPlugin('fbxmaya')
            except: pass

        dummy_model_path = self.get_dummy_file_path()

        if dummy_model_path and os.path.exists(dummy_model_path):
            imported = cmds.file(
                dummy_model_path, 
                i=True, 
                returnNewNodes=True, 
                ignoreVersion=True, 
                namespace="SM_POSE_REF",
                options="fbx"
            )
            dummy_grp = cmds.group(imported, name=self.ref_dummy_grp)
            cmds.inViewMessage(amg=f'成功载入专属模型: <hl>{os.path.basename(dummy_model_path)}</hl>！', pos='topCenter', fade=True)
        else:
            body = cmds.polyCylinder(r=22, h=145, sx=12, sy=1, sz=1, name="UE_Dummy_Body")[0]
            cmds.move(0, 72.5, 0, body)
            head = cmds.polySphere(r=16, sx=12, sy=8, name="UE_Dummy_Head")[0]
            cmds.move(0, 162.5, 0, head)
            dummy_grp = cmds.group(body, head, name=self.ref_dummy_grp)
            cmds.inViewMessage(amg='<hl>未找到 SM_Pose.fbx</hl>，已生成临时参考人偶。', pos='topCenter', fade=True)

        cmds.setAttr(f"{dummy_grp}.overrideEnabled", 1)
        cmds.setAttr(f"{dummy_grp}.overrideDisplayType", 2)

        src_cam, _ = self.find_target_camera()
        if src_cam:
            cam_pos = cmds.xform(src_cam, query=True, worldSpace=True, translation=True)
            cmds.xform(dummy_grp, worldSpace=True, translation=[cam_pos[0], cam_pos[1], cam_pos[2]])

        self.fix_viewport_clipping()

    def remove_ue_dummy(self, *args):
        if cmds.objExists(self.ref_dummy_grp):
            cmds.delete(self.ref_dummy_grp)
        if cmds.namespace(exists="SM_POSE_REF"):
            cmds.namespace(removeNamespace="SM_POSE_REF", mergeNamespaceWithRoot=True)

    def do_native_ctrl_g(self, *args):
        sel = cmds.ls(selection=True, long=True) or []
        if not sel:
            cmds.confirmDialog(title="提示", message="请先在视口或大纲中【全选】需要缩放的相机和所有碎模块！", button=["好的"], icon="information")
            return

        valid_items = [i for i in sel if self.ref_dummy_grp not in i]
        if not valid_items:
            return

        cmds.select(valid_items, replace=True)
        mel.eval('doGroup 0 1 1;')
        
        created_grp = cmds.ls(selection=True)[0]
        if cmds.objExists(self.interactive_scale_grp):
            cmds.delete(self.interactive_scale_grp)
        self.interactive_scale_grp = cmds.rename(created_grp, "UE_Interactive_Scale_Pivot_Grp")
        self.original_grp_pos = cmds.xform(self.interactive_scale_grp, query=True, worldSpace=True, translation=True)

        cur_val = cmds.intSliderGrp(self.scale_slider, query=True, value=True)
        cmds.setAttr(f"{self.interactive_scale_grp}.scaleX", float(cur_val))
        cmds.setAttr(f"{self.interactive_scale_grp}.scaleY", float(cur_val))
        cmds.setAttr(f"{self.interactive_scale_grp}.scaleZ", float(cur_val))

        self.fix_viewport_clipping()
        cmds.inViewMessage(amg='已完成<hl>原生 Ctrl+G 打组</hl>！调整缩放值即可缩放。', pos='topCenter', fade=True)

    def on_scale_slider_committed(self, val):
        if val > cmds.intSliderGrp(self.scale_slider, query=True, maxValue=True):
            cmds.intSliderGrp(self.scale_slider, edit=True, maxValue=val * 2)

        if not cmds.objExists(self.interactive_scale_grp):
            sel = cmds.ls(selection=True) or []
            if sel:
                self.do_native_ctrl_g()
            else:
                return

        if cmds.objExists(self.interactive_scale_grp):
            cmds.setAttr(f"{self.interactive_scale_grp}.scaleX", float(val))
            cmds.setAttr(f"{self.interactive_scale_grp}.scaleY", float(val))
            cmds.setAttr(f"{self.interactive_scale_grp}.scaleZ", float(val))
            self.fix_viewport_clipping()

    def set_scale_val(self, val):
        if val > cmds.intSliderGrp(self.scale_slider, query=True, maxValue=True):
            cmds.intSliderGrp(self.scale_slider, edit=True, maxValue=val * 2)
        cmds.intSliderGrp(self.scale_slider, edit=True, value=int(val))
        self.on_scale_slider_committed(val)

    def browse_dir(self, *args):
        mel.eval(f'''
            global proc int setUEExportCustomDirCallback(string $filePath, string $fileType) {{
                python("cmds.textField('{self.path_field}', edit=True, text='" + $filePath + "')");
                return 1;
            }}
            fileBrowserDialog 
                -mode 4 
                -fileCommand "setUEExportCustomDirCallback" 
                -actionName "选择目录" 
                -operationMode "Import" 
                -dialogStyle 1;
        ''')

    def find_target_camera(self):
        default_cams = ['persp', 'top', 'front', 'side']
        selected = cmds.ls(selection=True, long=True) or []

        for item in selected:
            if cmds.nodeType(item) == 'camera':
                p = cmds.listRelatives(item, parent=True, fullPath=True)
                return (p[0], item) if p else (item, item)
            shapes = cmds.listRelatives(item, shapes=True, fullPath=True) or []
            for s in shapes:
                if cmds.nodeType(s) == 'camera':
                    return item, s
            desc = cmds.listRelatives(item, allDescendents=True, fullPath=True) or []
            for d in desc:
                if cmds.nodeType(d) == 'camera':
                    p = cmds.listRelatives(d, parent=True, fullPath=True)
                    return (p[0], d) if p else (d, d)

        all_cams = cmds.ls(type='camera', long=True) or []
        for c in all_cams:
            p = cmds.listRelatives(c, parent=True, fullPath=True)
            if p:
                name_short = p[0].split('|')[-1]
                if name_short not in default_cams and "SM_POSE" not in name_short:
                    return p[0], c

        return None, None

    def is_true_zoom_camera(self, cam_shape, start_frame, end_frame):
        focal_keys = cmds.keyframe(cam_shape, attribute='focalLength', query=True, keyframeCount=True)
        if not focal_keys or focal_keys <= 1:
            return False

        key_values = cmds.keyframe(cam_shape, attribute='focalLength', query=True, valueChange=True) or []
        if key_values:
            max_v = max(key_values)
            min_v = min(key_values)
            if abs(max_v - min_v) > 0.001:
                return True
        return False

    def do_export(self, *args):
        shot = cmds.textFieldGrp(self.shot_field, query=True, text=True).strip()
        if not shot:
            cmds.confirmDialog(title="输入缺失", message="请在上方输入有效的【镜头号 (Shot)】后再执行导出！", button=["确定"], icon="warning")
            return

        orig_start = cmds.intFieldGrp(self.scene_frame_grp, query=True, value1=True)
        orig_end = cmds.intFieldGrp(self.scene_frame_grp, query=True, value2=True)
        
        plate_start = cmds.intFieldGrp(self.plate_frame_grp, query=True, value1=True)
        plate_end = cmds.intFieldGrp(self.plate_frame_grp, query=True, value2=True)
        
        export_mesh = cmds.checkBox(self.export_mesh_chk, query=True, value=True)
        export_dir = cmds.textField(self.path_field, query=True, text=True).strip()
        
        scale_val = cmds.intSliderGrp(self.scale_slider, query=True, value=True)
        if cmds.objExists(self.interactive_scale_grp):
            try:
                scale_val = int(round(cmds.getAttr(f"{self.interactive_scale_grp}.scaleX")))
            except:
                pass

        if not export_dir or not os.path.exists(export_dir):
            cmds.confirmDialog(title="路径错误", message="导出目录不存在，请点击浏览重新选择！", button=["确定"], icon="critical")
            return

        src_cam, src_cam_shape = self.find_target_camera()
        if not src_cam:
            cmds.confirmDialog(title="未找到相机", message="全场景未找到摄像机节点，请先框选相机！", button=["确定"], icon="critical")
            return

        duration = orig_end - orig_start + 1
        offset_val = 1 - orig_start

        if cmds.objExists(self.interactive_scale_grp):
            cmds.setAttr(f"{self.interactive_scale_grp}.scaleX", float(scale_val))
            cmds.setAttr(f"{self.interactive_scale_grp}.scaleY", float(scale_val))
            cmds.setAttr(f"{self.interactive_scale_grp}.scaleZ", float(scale_val))

        src_cam, src_cam_shape = self.find_target_camera()

        attrs = ['tx', 'ty', 'tz', 'rx', 'ry', 'rz', 'sx', 'sy', 'sz', 'v']
        for a in attrs:
            try: cmds.setAttr(f"{src_cam}.{a}", lock=False)
            except: pass

        new_cam_nodes = cmds.camera()
        temp_cam = new_cam_nodes[0]
        new_cam_shape = new_cam_nodes[1]

        constraint = cmds.parentConstraint(src_cam, temp_cam, maintainOffset=False)[0]
        cmds.bakeResults(
            temp_cam,
            time=(orig_start, orig_end),
            simulation=True,
            sampleBy=1,
            disableImplicitControl=True,
            shape=False
        )
        if cmds.objExists(constraint):
            cmds.delete(constraint)

        allowed_attrs = ['translateX', 'translateY', 'translateZ', 'rotateX', 'rotateY', 'rotateZ']
        animatable_trans = cmds.listAnimatable(temp_cam) or []
        for anim_plug in animatable_trans:
            attr_short = anim_plug.split('.')[-1]
            if attr_short not in allowed_attrs:
                cmds.cutKey(anim_plug, clear=True)

        for sa in ['sx', 'sy', 'sz']:
            cmds.setAttr(f"{temp_cam}.{sa}", 1.0)
        cmds.setAttr(f"{temp_cam}.v", 1)

        cmds.cutKey(new_cam_shape, clear=True)
        is_zoom = self.is_true_zoom_camera(src_cam_shape, orig_start, orig_end)

        if is_zoom:
            cmds.copyKey(src_cam_shape, attribute='focalLength', time=(orig_start, orig_end))
            cmds.pasteKey(new_cam_shape, attribute='focalLength', option='replace')
            if offset_val != 0:
                cmds.keyframe(new_cam_shape, attribute='focalLength', edit=True, relative=True, timeChange=offset_val)
        else:
            fl_val = cmds.getAttr(f"{src_cam_shape}.focalLength")
            fl_conn = cmds.listConnections(f"{new_cam_shape}.focalLength", source=True, destination=False, plugs=True) or []
            for c in fl_conn:
                cmds.disconnectAttr(c, f"{new_cam_shape}.focalLength")
            cmds.setAttr(f"{new_cam_shape}.focalLength", fl_val)

        try:
            h_ap = cmds.getAttr(f"{src_cam_shape}.horizontalFilmAperture")
            v_ap = cmds.getAttr(f"{src_cam_shape}.verticalFilmAperture")
            cmds.setAttr(f"{new_cam_shape}.horizontalFilmAperture", h_ap)
            cmds.setAttr(f"{new_cam_shape}.verticalFilmAperture", v_ap)
        except:
            pass

        if offset_val != 0:
            cmds.keyframe(temp_cam, edit=True, relative=True, timeChange=offset_val)

        final_cam_name = f"Cam{shot}_{plate_start}_{plate_end}"
        if cmds.objExists(final_cam_name):
            cmds.delete(final_cam_name)
        final_cam = cmds.rename(temp_cam, final_cam_name)

        fbx_name = f"cam{shot}_{plate_start}_{plate_end}.fbx"
        cam_fbx_path = os.path.join(export_dir, fbx_name).replace('\\', '/')

        if not cmds.pluginInfo('fbxmaya', query=True, loaded=True):
            cmds.loadPlugin('fbxmaya')

        cmds.select(final_cam, replace=True)
        mel.eval('FBXResetExport;')
        mel.eval('FBXExportBakeComplexAnimation -v false;')
        mel.eval('FBXExportInputConnections -v false;')
        mel.eval('FBXExportEmbeddedTextures -v false;')
        mel.eval(f'FBXExport -f "{cam_fbx_path}" -s true;')

        mesh_fbx_path = None
        if export_mesh:
            export_models = []
            if cmds.objExists(self.interactive_scale_grp):
                children = cmds.listRelatives(self.interactive_scale_grp, children=True, fullPath=True) or []
                export_models = [c for c in children if src_cam not in c and self.ref_dummy_grp not in c]
            else:
                selected_items = cmds.ls(selection=True) or []
                export_models = [item for item in selected_items if item != final_cam and self.ref_dummy_grp not in item]

            if export_models:
                cmds.select(export_models, replace=True)
                mesh_fbx_path = os.path.join(export_dir, f"{shot}_model_ref.fbx").replace('\\', '/')
                mel.eval(f'FBXExport -f "{mesh_fbx_path}" -s true;')

        self.remove_ue_dummy()
        cmds.deleteUI(self.win)
        
        current_fps = self.get_readable_fps()

        msg = f"导出已完成！\n\n"
        msg += f"相机节点与文件: {fbx_name}\n"
        msg += f"保存目录: {cam_fbx_path}\n\n"
        msg += f"【状态校验】\n"
        msg += f"• 关键帧白名单: 100% 仅保留 Translate 与 Rotate 动画\n"
        msg += f"• 焦距状态: {'动态变焦 (已平移对齐变焦曲线)' if is_zoom else '纯净定焦 (已断连全部关键帧，静态纯数值)'}\n"
        msg += f"• 帧率核对: {current_fps}\n"
        msg += f"• 相机命名: 严格对齐素材规范 ({plate_start} ~ {plate_end})\n"
        msg += f"• 内部动画: 已自动平移至 1 ~ {duration} 帧 (对齐 UE 0001)\n"
        msg += f"• 缩放状态: 真实缩放系数为 {scale_val}x (已继承场景状态)\n"
        if mesh_fbx_path:
            msg += f"• 参考简模: {mesh_fbx_path}\n"

        cmds.confirmDialog(title="发布成功", message=msg, button=["完成"])
        subprocess.Popen(f'explorer "{os.path.normpath(export_dir)}"')

def main():
    MayaToUECamExporterUI()

if __name__ == '__main__':
    main()