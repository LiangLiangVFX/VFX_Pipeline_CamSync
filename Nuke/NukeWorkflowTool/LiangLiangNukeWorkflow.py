# -*- coding: utf-8 -*-
"""
LiangLiang Nuke Pipeline Workflow (工业级极简正交布局版·单多层智能合一)
-------------------------------------------------------------------------
- 模块 1: 实拍预处理与输出UE底板 (X: -40~580 墨绿框, 2048*1152/25fps 工程锁定, default (sRGB))
- 模块 2: UE 预合成主干区 (X: 720~1260 藏蓝框):
  * 单层流 (背景 + Actor ID + Material ID 完整 3 层): Read_UE_BG -> TimeOffset(1000) -> Grade -> CC -> Merge -> Write
  * 多层流 (含 env/key/fill/fog 等): 链式 Plus 加法树, Fog 专用 Keyer(Luma Key), 180° 水平直线对接
- 模块 3: 分层 AOV 与 Cryptomatte 提取区 (X: 1400~2260 金黄框):
  * Y=240 水平一线排开: Depth, Normal, Pos (带缩略图) 与两个 Cryptomatte, 零遮挡零挤压
- 水印标记: 右下角自动附带 [模版由脚本自动生成 v1.0.0]
Author: LiangLiangArtist
Contact: liangliangvfx@gmail.com
"""

import os
import re
import nuke

class LiangLiangNukePipeline(object):
    def __init__(self):
        pass

    def get_current_pipeline_context(self):
        """解析平台生成的工程信息与目录结构"""
        script_path = nuke.root().name()
        if not script_path or script_path == "Root":
            nuke.message("⚠️ 请先在 Nuke 中打开平台在 workarea 生成的工程文件！\n例如: ..._ep28_2160_ue_zl_v001.nk")
            return None, None, None, None

        norm_path = os.path.normpath(script_path).replace('\\', '/')
        workarea_dir = os.path.dirname(norm_path)
        nk_filename = os.path.basename(norm_path)

        ep_match = re.search(r'(ep\d+)', nk_filename, re.IGNORECASE)
        ep = ep_match.group(1).lower() if ep_match else "ep"

        shot_match = re.search(r'ep\d+[_\-](\d{3,5})', nk_filename, re.IGNORECASE)
        if shot_match:
            shot = shot_match.group(1)
        else:
            nums = re.findall(r'(\d{3,5})', nk_filename)
            shot = nums[-1] if nums else "2110"

        shot_root_dir = ""
        check_dir = workarea_dir
        for _ in range(4):
            if os.path.basename(check_dir).lower() == "workarea":
                parent = os.path.basename(os.path.dirname(check_dir)).lower()
                if parent == "ue":
                    shot_root_dir = os.path.dirname(os.path.dirname(check_dir)).replace('\\', '/')
                    break
            check_dir = os.path.dirname(check_dir)

        return ep, shot, workarea_dir, shot_root_dir

    def _setup_project_root_settings(self, first_frame=None, last_frame=None):
        """严格统一工程设置: 2048*1152, 25fps, 对齐帧范围"""
        fmt_name = "2048x1152_Film"
        target_fmt_str = "2048 1152 1.0 2048x1152_Film"
        try:
            nuke.addFormat(target_fmt_str)
        except:
            pass

        root = nuke.root()
        try:
            root['format'].setValue(fmt_name)
        except:
            try:
                root['format'].setValue("2048 1152")
            except:
                pass

        root['fps'].setValue(25.0)

        if first_frame is not None and last_frame is not None:
            root['first_frame'].setValue(int(first_frame))
            root['last_frame'].setValue(int(last_frame))

    def _create_watermark_note(self, xpos, ypos):
        """在指定坐标生成专属水印签名节点"""
        for n in nuke.allNodes("StickyNote"):
            if "Pipeline_Watermark" in n.name():
                nuke.delete(n)

        note = nuke.createNode("StickyNote", inpanel=False)
        note.setName("Pipeline_Watermark")
        note['label'].setValue("<font color='#888888' size='3'><b>模版由脚本自动生成 v1.0.0</b></font>")
        note['note_font_size'].setValue(11)
        note.setXYpos(xpos, ypos)
        return note

    def _set_safe_write_colorspace(self, write_node, preferred_spaces):
        """严格设置 Write 节点的色彩空间，优先匹配 default (sRGB)"""
        cs_knob = None
        for k_name in ['colorspace', 'out_colorspace', 'ocio_output']:
            if k_name in write_node.knobs():
                cs_knob = write_node[k_name]
                break

        if not cs_knob:
            return

        try:
            available = cs_knob.values()
            for pref in preferred_spaces:
                for avail in available:
                    if pref.lower() == avail.lower():
                        cs_knob.setValue(avail)
                        return
            for pref in preferred_spaces:
                for avail in available:
                    if pref.lower() in avail.lower():
                        cs_knob.setValue(avail)
                        return
        except:
            pass

        try:
            cs_knob.setValue(preferred_spaces[0])
        except:
            pass

    def _get_valid_colorspace_value(self, knob, preferred_candidates):
        try:
            available_values = knob.values()
            for cand in preferred_candidates:
                for avail in available_values:
                    if avail.lower() == cand.lower():
                        return avail
            return knob.value()
        except:
            return None

    # =========================================================================
    # 防重复与旧节点清理逻辑
    # =========================================================================
    def _cleanup_module1_nodes(self):
        m1_names = [
            "Read_Plate", "Colorspace_LogC_to_Linear", "ColorMode_Switch",
            "Holdout_Roto_KEEP", "Blur_InM", "Garbage_Roto_REMOVE", "Blur_OutM",
            "Keyer_Alpha", "Copy_Alpha", "Premult_Plate", "Write_Final_PNG"
        ]
        for name in m1_names:
            n = nuke.toNode(name)
            if n: nuke.delete(n)
        for bd in nuke.allNodes("BackdropNode"):
            lbl = bd['label'].value()
            if "实拍预处理" in lbl or "模块一" in lbl:
                nuke.delete(bd)

    def _cleanup_module2_nodes(self):
        m2_fixed = [
            "Read_UE_BG", "TimeOffset_UE_BG", "Grade_UE_BG", "ColorCorrect_UE_BG",
            "Merge_Comp_Over", "HorizonWriteNode", "Read_Actor_ID", "TimeOffset_Actor_ID",
            "Cryptomatte_Actor", "Read_Material_ID", "TimeOffset_Material_ID", "Dot_Material_ID",
            "FinalImageMovieRenderQueue_WorldDepth_Shuffel",
            "FinalImageMovieRenderQueue_WorldNormal_Shuffel",
            "FinalImageMovieRenderQueue_WorldPos_Shuffel",
            "Cryptomatte_Material"
        ]
        for name in m2_fixed:
            n = nuke.toNode(name)
            if n: nuke.delete(n)

        # 扫描并清理 X >= 650 范围内的多层加法树动态节点
        for n in nuke.allNodes():
            if any(n.name().startswith(p) for p in ["Merge_Plus_", "Merge_Screen_", "Keyer_Fog_", "Grade_", "TimeOffset_", "Read_"]):
                if n.xpos() >= 650:
                    nuke.delete(n)

        for bd in nuke.allNodes("BackdropNode"):
            lbl = bd['label'].value()
            if any(kw in lbl for kw in ["UE 预合成主干区", "分层 AOV 与 Cryptomatte"]):
                nuke.delete(bd)

    # =========================================================================
    # 模块 1：实拍预处理与输出UE底板 (Zone 1: X: -40 ~ 580)
    # =========================================================================
    def build_plate_prep_network(self):
        ep, shot, workarea_dir, shot_root_dir = self.get_current_pipeline_context()
        if not workarea_dir:
            return

        if nuke.toNode("Read_Plate") or nuke.toNode("Write_Final_PNG"):
            if not nuke.ask("⚠️ 检测到当前工程中已存在「实拍预处理与输出UE底板」节点！\n\n是否清除旧节点并重新构建？\n(点击 Yes 将自动清理旧节点重新生成，点击 No 取消操作)"):
                return
            self._cleanup_module1_nodes()

        filter_exts = "*.exr *.dpx *.tif *.tiff *.png *.jpg *.jpeg *.mov *.mp4 *.mxf"
        chosen_file = nuke.getFilename(f"【选择 Shot {shot} 实拍原始素材 (序列任选一张或视频文件)】", filter_exts)
        if not chosen_file:
            return

        chosen_file = os.path.normpath(chosen_file).replace('\\', '/')
        file_dir = os.path.dirname(chosen_file)
        base_name = os.path.basename(chosen_file)
        name_ext = os.path.splitext(base_name)[1].lower()

        video_exts = ('.mov', '.mp4', '.mxf', '.avi')
        is_video = name_ext in video_exts

        seq_pattern = chosen_file
        first_f = 1001
        last_f = 1039

        if is_video:
            seq_pattern = chosen_file
            temp_read = nuke.nodes.Read(file=seq_pattern)
            first_f = int(temp_read['first'].value())
            last_f = int(temp_read['last'].value())
            nuke.delete(temp_read)
        else:
            ext_files = [f for f in os.listdir(file_dir) if f.lower().endswith(name_ext)]
            ext_files.sort()
            if not ext_files:
                nuke.message("所选目录未检测到有效素材序列！")
                return

            m_first = re.search(r'(\d+)' + re.escape(name_ext) + r'$', ext_files[0], re.IGNORECASE)
            m_last = re.search(r'(\d+)' + re.escape(name_ext) + r'$', ext_files[-1], re.IGNORECASE)

            if m_first and m_last:
                first_f = int(m_first.group(1))
                last_f = int(m_last.group(1))
                pad_len = len(m_first.group(1))
                seq_pattern = re.sub(r'(\d+)' + re.escape(name_ext) + r'$', f"%0{pad_len}d{name_ext}", chosen_file, flags=re.IGNORECASE)
            else:
                first_f = 1001
                last_f = first_f + len(ext_files) - 1

        target_bg_dir = os.path.join(workarea_dir, "bg").replace('\\', '/')
        if not os.path.exists(target_bg_dir):
            try: os.makedirs(target_bg_dir)
            except: pass

        self._setup_project_root_settings(first_frame=first_f, last_frame=last_f)

        for n in nuke.allNodes():
            n.setSelected(False)

        # 1. 读入实拍素材 (X: 0, Y: 0)
        read_plate = nuke.createNode("Read", inpanel=False)
        read_plate.setName("Read_Plate")
        read_plate['file'].setValue(seq_pattern)
        read_plate['first'].setValue(first_f)
        read_plate['last'].setValue(last_f)
        read_plate['origfirst'].setValue(first_f)
        read_plate['origlast'].setValue(last_f)
        if 'raw' in read_plate.knobs():
            read_plate['raw'].setValue(True)
        read_plate.setXYpos(0, 0)

        # 2. 色彩转换与切换分支 (垂直与正交分布)
        col_convert = nuke.createNode("Colorspace", inpanel=False)
        col_convert.setInput(0, read_plate)
        col_convert.setName("Colorspace_LogC_to_Linear")
        valid_in = self._get_valid_colorspace_value(col_convert['colorspace_in'], ["AlexaV3LogC", "LogC", "linear"])
        valid_out = self._get_valid_colorspace_value(col_convert['colorspace_out'], ["linear", "scene_linear", "ACEScg", "Linear"])
        if valid_in: col_convert['colorspace_in'].setValue(valid_in)
        if valid_out: col_convert['colorspace_out'].setValue(valid_out)
        col_convert.setXYpos(140, 60)

        color_switch = nuke.createNode("Switch", inpanel=False)
        color_switch.setName("ColorMode_Switch")
        color_switch.setInput(0, read_plate)
        color_switch.setInput(1, col_convert)
        mode_knob = nuke.Enumeration_Knob("color_mode", "素材色彩模式", [
            "标准普通素材 (sRGB / 直通)", 
            "电影机灰片 (LogC -> Linear 转正)"
        ])
        mode_knob.setValue(1)
        color_switch.addKnob(mode_knob)
        color_switch['which'].setExpression("color_mode")
        color_switch.setXYpos(0, 130)

        if 'raw' in read_plate.knobs():
            read_plate['raw'].setExpression(f"{color_switch.name()}.which == 1")

        # 3. 遮罩支路 (整齐展开，纵向安全间距)
        holdout_roto = nuke.createNode("Roto", inpanel=False)
        holdout_roto.setInput(0, read_plate)
        holdout_roto.setName("Holdout_Roto_KEEP")
        holdout_roto['label'].setValue("【圈要的: 补实心】")
        holdout_roto.setXYpos(280, 0)

        blur_inm = nuke.createNode("Blur", inpanel=False)
        blur_inm.setInput(0, holdout_roto)
        blur_inm.setName("Blur_InM")
        blur_inm['channels'].setValue("alpha")
        blur_inm['size'].setValue(4.0)
        blur_inm.setXYpos(280, 80)

        garbage_roto = nuke.createNode("Roto", inpanel=False)
        garbage_roto.setInput(0, read_plate)
        garbage_roto.setName("Garbage_Roto_REMOVE")
        garbage_roto['label'].setValue("【圈不要的: 切杂物】")
        garbage_roto.setXYpos(440, 0)

        blur_outm = nuke.createNode("Blur", inpanel=False)
        blur_outm.setInput(0, garbage_roto)
        blur_outm.setName("Blur_OutM")
        blur_outm['channels'].setValue("alpha")
        blur_outm['size'].setValue(6.0)
        blur_outm.setXYpos(440, 80)

        # 4. Keylight (固定 Y = 220)
        kl = nuke.createNode("OFXuk.co.thefoundry.keylight.keylight_v201", inpanel=False)
        kl.setName("Keyer_Alpha")
        kl.setInput(0, color_switch)
        kl.setInput(1, blur_inm)
        kl.setInput(2, blur_outm)
        kl.setXYpos(280, 220)

        if "insideComponent" in kl.knobs():
            kl["insideComponent"].setValue("None")
        if "outsideComponent" in kl.knobs():
            kl["outsideComponent"].setValue("None")

        for cw in ['clipwhite', 'clipWhite', 'clip_white']:
            if cw in kl.knobs(): kl[cw].setValue(1.0); break

        for cb in ['clipblack', 'clipBlack', 'clip_black']:
            if cb in kl.knobs(): kl[cb].setValue(0.0); break

        for sh in ['show', 'view']:
            if sh in kl.knobs(): kl[sh].setValue("Final Result"); break

        # 5. Copy -> Premult -> Write (与 Keylight 在 Y=220 严格水平对接)
        copy_alpha = nuke.createNode("Copy", inpanel=False)
        copy_alpha.setName("Copy_Alpha")
        copy_alpha.setInput(0, color_switch)
        copy_alpha.setInput(1, kl)
        copy_alpha['from0'].setValue("rgba.alpha")
        copy_alpha['to0'].setValue("rgba.alpha")
        copy_alpha.setXYpos(0, 220)

        premult = nuke.createNode("Premult", inpanel=False)
        premult.setName("Premult_Plate")
        premult.setInput(0, copy_alpha)
        premult.setXYpos(0, 320)

        png_out_pattern = f"{target_bg_dir}/bg_{shot}_####.png"
        write_ue = nuke.createNode("Write", inpanel=False)
        write_ue.setInput(0, premult)
        write_ue.setName("Write_Final_PNG")
        write_ue['file'].setValue(png_out_pattern)
        write_ue['channels'].setValue("rgba")
        write_ue['file_type'].setValue("png")
        write_ue['datatype'].setValue("8 bit")

        self._set_safe_write_colorspace(write_ue, ["default (sRGB)", "default", "sRGB", "Output - sRGB"])

        open_script = (
            "import os, subprocess;\n"
            "f_path = nuke.thisNode()['file'].evaluate();\n"
            "d_path = os.path.dirname(f_path);\n"
            "if os.path.exists(d_path):\n"
            "    os.startfile(d_path) if os.name == 'nt' else subprocess.Popen(['open', d_path])"
        )
        write_ue['afterRender'].setValue(open_script)

        btn_open = nuke.PyScript_Knob("btn_open_bg_dir", "  📂 打开输出文件夹  ", open_script)
        write_ue.addKnob(btn_open)

        write_ue.setXYpos(0, 420)

        # 墨绿卡片规整包裹 (X: -40 ~ 580, Y: -60 ~ 600)
        bd = nuke.createNode("BackdropNode", inpanel=False)
        bd['label'].setValue(f"<center><b><font size='4'>Shot {shot} 实拍预处理与输出UE底板</font></b></center>")
        bd['note_font_size'].setValue(14)
        bd['tile_color'].setValue(0x1a402500)
        bd.setXYpos(-40, -60)
        bd['bdwidth'].setValue(620)
        bd['bdheight'].setValue(660)

        self._create_watermark_note(xpos=340, ypos=520)

        nuke.scriptSave()

        viewer = nuke.activeViewer()
        if viewer:
            viewer.node().setInput(0, kl)

        nuke.show(kl)
        nuke.message(
            f"【✅ 实拍预处理节点已构建完成】\n\n"
            f"⚙️ 工程设置已校准锁定:\n"
            f"• 画面尺寸: 2048 × 1152 (1.0)\n"
            f"• 帧率设置: 25 fps\n"
            f"• 帧数范围: {first_f} - {last_f} 帧\n\n"
            f"📦 节点特性确认:\n"
            f"• [Write_Final_PNG]: 色彩空间已锁定为 default (sRGB)\n"
            f"• [自动弹窗]: 渲染完成后会自动打开输出文件夹 (面板亦有快捷按钮)\n"
            f"• [安全防护]: 已集成重复创建检测，再次点击可自动安全重构\n\n"
            f"👉 下一步操作指南:\n"
            f"1. 双击 ColorMode_Switch 确认素材色彩模式；\n"
            f"2. 双击 Keyer_Alpha 吸取背景色，微调 Screen Matte 控制白黑切值；\n"
            f"3. 画好 Roto 遮罩补心或切除杂物后，选中 Write_Final_PNG 点击「Render」输出透明 PNG 底板！"
        )

    # =========================================================================
    # AOV 拆层辅助工具
    # =========================================================================
    def _create_single_aov_shuffle(self, target_node, layer_name, node_name, xpos, ypos):
        try:
            nuke.tcl(f"add_layer {{{layer_name} {layer_name}.red {layer_name}.green {layer_name}.blue {layer_name}.alpha}}")
        except:
            pass

        shuf = nuke.createNode("Shuffle", inpanel=False)
        shuf.setInput(0, target_node)
        shuf.setName(node_name)
        if 'in' in shuf.knobs():
            shuf['in'].setValue(layer_name)
        elif 'in1' in shuf.knobs():
            shuf['in1'].setValue(layer_name)

        if 'postage_stamp' in shuf.knobs():
            shuf['postage_stamp'].setValue(True)

        shuf.setXYpos(xpos, ypos)
        return shuf

    def _create_cryptomatte_node(self, target_node, node_name, xpos, ypos):
        try:
            crypto = nuke.createNode("Cryptomatte", inpanel=False)
        except:
            crypto = nuke.createNode("NoOp", inpanel=False)
            crypto['label'].setValue("Cryptomatte")
        crypto.setInput(0, target_node)
        crypto.setName(node_name)
        crypto.setXYpos(xpos, ypos)
        return crypto

    def _find_matching_layer(self, node, keyword):
        try:
            channels = node.channels()
            layers = list(set([c.split('.')[0] for c in channels]))
            for lyr in layers:
                if f"World{keyword.capitalize()}" in lyr:
                    return lyr
            for lyr in layers:
                if keyword.lower() in lyr.lower():
                    return lyr
        except:
            pass
        return f"FinalImageMovieRenderQueue_World{keyword.capitalize()}"

    def _scan_exr_sequences(self, render_dir):
        all_files = os.listdir(render_dir)
        exr_files = [f for f in all_files if f.lower().endswith(".exr")]
        if not exr_files:
            return {}

        sequences = {}
        for f in exr_files:
            m = re.search(r'^(.*?)([._])(\d+)\.exr$', f, re.IGNORECASE)
            if m:
                prefix = m.group(1)
                sep = m.group(2)
                digits = m.group(3)
                frame = int(digits)
                pad = len(digits)
                if prefix not in sequences:
                    sequences[prefix] = {
                        "frames": [],
                        "sep": sep,
                        "pad": pad
                    }
                sequences[prefix]["frames"].append(frame)
        return sequences

    def _clean_layer_name(self, raw_name):
        n = re.sub(r'^(cam\d+_|ep\d+_|shot\d+_)', '', raw_name, flags=re.IGNORECASE)
        return re.sub(r'[^a-zA-Z0-9_]', '_', n)

    def _build_right_id_network(self, default_render_dir, actor_seq, material_seq, shot, id_start_x=1400):
        """Zone 3: 构建右侧独立 AOV 与 Cryptomatte 提取区 (X: 1400 ~ 2260, Y=240 水平一字拉齐)"""
        # A. Actor ID (Read 1480,0 -> TimeOffset 1480,80 -> Crypto 1480,240)
        actor_col_x = id_start_x + 80
        if actor_seq:
            p, d = actor_seq
            frames = sorted(d["frames"])
            seq_path = f"{default_render_dir}/{p}{d['sep']}%0{d['pad']}d.exr"

            r_actor = nuke.createNode("Read", inpanel=False)
            r_actor.setName("Read_Actor_ID")
            r_actor['file'].setValue(seq_path)
            r_actor['first'].setValue(frames[0]); r_actor['last'].setValue(frames[-1])
            r_actor['origfirst'].setValue(frames[0]); r_actor['origlast'].setValue(frames[-1])
            r_actor.setXYpos(actor_col_x, 0)

            t_actor = nuke.createNode("TimeOffset", inpanel=False)
            t_actor.setInput(0, r_actor)
            t_actor.setName("TimeOffset_Actor_ID")
            t_actor['time_offset'].setValue(1000)
            t_actor.setXYpos(actor_col_x, 80)

            self._create_cryptomatte_node(t_actor, "Cryptomatte_Actor", actor_col_x, 240)

        # B. Material ID (Read 1860,0 -> TimeOffset 1860,80 -> Dot 1894,150 -> 4个下挂节点在 Y=240 并列展开)
        mat_col_x = id_start_x + 460
        if material_seq:
            p, d = material_seq
            frames = sorted(d["frames"])
            seq_path = f"{default_render_dir}/{p}{d['sep']}%0{d['pad']}d.exr"

            r_mat = nuke.createNode("Read", inpanel=False)
            r_mat.setName("Read_Material_ID")
            r_mat['file'].setValue(seq_path)
            r_mat['first'].setValue(frames[0]); r_mat['last'].setValue(frames[-1])
            r_mat['origfirst'].setValue(frames[0]); r_mat['origlast'].setValue(frames[-1])
            r_mat.setXYpos(mat_col_x, 0)

            t_mat = nuke.createNode("TimeOffset", inpanel=False)
            t_mat.setInput(0, r_mat)
            t_mat.setName("TimeOffset_Material_ID")
            t_mat['time_offset'].setValue(1000)
            t_mat.setXYpos(mat_col_x, 80)

            dot_mat = nuke.createNode("Dot", inpanel=False)
            dot_mat.setInput(0, t_mat)
            dot_mat.setName("Dot_Material_ID")
            dot_mat.setXYpos(mat_col_x + 34, 150)

            depth_layer = self._find_matching_layer(r_mat, "depth")
            normal_layer = self._find_matching_layer(r_mat, "normal")
            pos_layer = self._find_matching_layer(r_mat, "pos")

            # 4个节点水平间距 120~140px，缩略图预览之间留有宽裕呼吸空间
            self._create_single_aov_shuffle(
                dot_mat, depth_layer, "FinalImageMovieRenderQueue_WorldDepth_Shuffel", mat_col_x - 200, 240
            )
            self._create_single_aov_shuffle(
                dot_mat, normal_layer, "FinalImageMovieRenderQueue_WorldNormal_Shuffel", mat_col_x - 80, 240
            )
            self._create_single_aov_shuffle(
                dot_mat, pos_layer, "FinalImageMovieRenderQueue_WorldPos_Shuffel", mat_col_x + 40, 240
            )
            self._create_cryptomatte_node(
                dot_mat, "Cryptomatte_Material", mat_col_x + 180, 240
            )

        # 金黄色卡片规整包裹 (X: 1400 ~ 2260, Y: -60 ~ 480)
        bd_right = nuke.createNode("BackdropNode", inpanel=False)
        bd_right['label'].setValue("<center><b><font size='5' color='#ffcc00'>分层 AOV 与 Cryptomatte (供合成提取)</font></b><br>ID / Material (WorldDepth, WorldPos, WorldNormal)</center>")
        bd_right['note_font_size'].setValue(14)
        bd_right['tile_color'].setValue(0x55440000)
        bd_right.setXYpos(id_start_x, -60)
        bd_right['bdwidth'].setValue(860)
        bd_right['bdheight'].setValue(540)

        self._create_watermark_note(xpos=id_start_x + 600, ypos=400)

    # =========================================================================
    # 模块 2：UE 渲染分层自动预合成与 ID 拆层 (Zone 2: X: 720 ~ 1260)
    # =========================================================================
    def build_unified_autocomp_network(self):
        ep, shot, workarea_dir, shot_root_dir = self.get_current_pipeline_context()
        if not workarea_dir:
            return

        if nuke.toNode("HorizonWriteNode") or nuke.toNode("Read_UE_BG"):
            if not nuke.ask("⚠️ 检测到当前工程中已存在「UE渲染分层预合成」节点！\n\n是否清除旧节点并重新构建？\n(点击 Yes 将自动清理旧节点重新生成，点击 No 取消操作)"):
                return
            self._cleanup_module2_nodes()

        default_render_dir = ""
        detected_version = "最新版"
        if shot_root_dir:
            publish_dir = os.path.normpath(os.path.join(shot_root_dir, "ue", "publish")).replace('\\', '/')
            if os.path.exists(publish_dir):
                v_dirs = [
                    d for d in os.listdir(publish_dir)
                    if re.match(r'^v\d+$', d, re.IGNORECASE) and os.path.isdir(os.path.join(publish_dir, d))
                ]
                if v_dirs:
                    v_dirs.sort(key=lambda x: int(re.search(r'\d+', x).group(0)))
                    latest_v = v_dirs[-1]
                    test_render = os.path.normpath(os.path.join(publish_dir, latest_v, "render")).replace('\\', '/')
                    if os.path.exists(test_render):
                        default_render_dir = test_render
                        detected_version = latest_v

        if not default_render_dir or not os.path.exists(default_render_dir):
            chosen = nuke.getFilename("选择 UE 渲染输出的 render 文件夹 (或序列任选一张图片)", "", type="dir")
            if not chosen:
                return
            default_render_dir = os.path.normpath(chosen).replace('\\', '/')

        if os.path.isfile(default_render_dir):
            default_render_dir = os.path.dirname(default_render_dir).replace('\\', '/')

        if not os.path.isdir(default_render_dir):
            nuke.message(f"所选路径不是有效文件夹！\n{default_render_dir}")
            return

        sequences = self._scan_exr_sequences(default_render_dir)
        if not sequences:
            nuke.message("render 目录下未找到任何 EXR 序列文件！\n" + default_render_dir)
            return

        self._setup_project_root_settings()

        for n in nuke.allNodes():
            n.setSelected(False)

        # 1. 深度分类：精准提取 Actor ID 与 Material ID
        actor_seq = None
        material_seq = None
        unclassified = {}

        for prefix, data in sequences.items():
            p_lower = prefix.lower()
            if any(k in p_lower for k in ["material", "shd"]) or re.search(r'(^|[._])mat([._]|$)', p_lower):
                material_seq = (prefix, data)
            elif "actor" in p_lower:
                actor_seq = (prefix, data)
            else:
                unclassified[prefix] = data

        content_layers = {}
        for prefix, data in unclassified.items():
            p_lower = prefix.lower()
            if "id" in p_lower:
                if not actor_seq:
                    actor_seq = (prefix, data)
                elif not material_seq:
                    material_seq = (prefix, data)
                else:
                    content_layers[prefix] = data
            else:
                content_layers[prefix] = data

        if len(sequences) == 3 and actor_seq and not material_seq and len(content_layers) == 2:
            sorted_items = sorted(content_layers.items(), key=lambda x: len(x[0]))
            material_seq = sorted_items[1]
            content_layers = {sorted_items[0][0]: sorted_items[0][1]}

        if not content_layers:
            nuke.message("未在目录中检测到任何镜头渲染画面或灯光分层！")
            return

        # 2. 单层 vs 多层 智能研判
        light_keywords = ['env', 'key', 'fill', 'sky', 'fog', 'heightfog', 'easyfog', 'emi', 'emission', 'lgt']
        is_multi = False

        if len(content_layers) > 1:
            is_multi = True
        else:
            single_name = list(content_layers.keys())[0].lower()
            if any(k in single_name for k in light_keywords):
                is_multi = True
            else:
                is_multi = False

        # 中区主干网格: 主干列 X=800, 支路列 X=1080
        trunk_x = 800
        branch_x = 1080

        # =====================================================================
        # 分支 A：单层装配流程 (背景 + Actor ID + Material ID 完整 3 层)
        # =====================================================================
        if not is_multi:
            prefix, data = list(content_layers.items())[0]
            frames = sorted(data["frames"])
            seq_path = f"{default_render_dir}/{prefix}{data['sep']}%0{data['pad']}d.exr"

            r_bg = nuke.createNode("Read", inpanel=False)
            r_bg.setName("Read_UE_BG")
            r_bg['file'].setValue(seq_path)
            r_bg['first'].setValue(frames[0]); r_bg['last'].setValue(frames[-1])
            r_bg['origfirst'].setValue(frames[0]); r_bg['origlast'].setValue(frames[-1])
            r_bg.setXYpos(trunk_x, 0)

            t_offset = nuke.createNode("TimeOffset", inpanel=False)
            t_offset.setInput(0, r_bg)
            t_offset.setName("TimeOffset_UE_BG")
            t_offset['time_offset'].setValue(1000)
            t_offset.setXYpos(trunk_x, 80)

            grade_node = nuke.createNode("Grade", inpanel=False)
            grade_node.setInput(0, t_offset)
            grade_node.setName("Grade_UE_BG")
            grade_node.setXYpos(trunk_x, 160)

            cc_node = nuke.createNode("ColorCorrect", inpanel=False)
            cc_node.setInput(0, grade_node)
            cc_node.setName("ColorCorrect_UE_BG")
            cc_node.setXYpos(trunk_x, 240)

            cur_comp_pipe = cc_node
            over_y = 320  # 与模块一 Premult_Plate (0, 320) 严格水平对齐！

            fg_pipe = None
            for n in nuke.allNodes("Premult"):
                if "Premult_Plate" in n.name() or f"Premult_{shot}" in n.name():
                    fg_pipe = n
                    break

            if not fg_pipe:
                bg_png_dir = os.path.join(workarea_dir, "bg").replace('\\', '/')
                png_pattern = f"{bg_png_dir}/bg_{shot}_%04d.png"
                read_fg = nuke.createNode("Read", inpanel=False)
                read_fg.setName("Read_Exported_PNG")
                read_fg['file'].setValue(png_pattern)
                read_fg['first'].setValue(int(nuke.root()['first_frame'].value()))
                read_fg['last'].setValue(int(nuke.root()['last_frame'].value()))
                read_fg['origfirst'].setValue(int(nuke.root()['first_frame'].value()))
                read_fg['origlast'].setValue(int(nuke.root()['last_frame'].value()))
                read_fg.setXYpos(trunk_x - 160, over_y)
                fg_pipe = read_fg

            final_merge = nuke.createNode("Merge2", inpanel=False)
            final_merge['operation'].setValue("over")
            final_merge.setInput(0, cur_comp_pipe)
            final_merge.setInput(1, fg_pipe)
            final_merge.setName("Merge_Comp_Over")
            final_merge.setXYpos(trunk_x, over_y)

            preview_dir = os.path.normpath(os.path.join(default_render_dir, "..", "preview")).replace('\\', '/')
            if not os.path.exists(preview_dir):
                try: os.makedirs(preview_dir)
                except: pass

            nk_base = os.path.splitext(os.path.basename(nuke.root().name()))[0]
            mov_out_path = f"{preview_dir}/{nk_base}.mov"

            h_write = nuke.createNode("Write", inpanel=False)
            h_write.setInput(0, final_merge)
            h_write.setName("HorizonWriteNode")
            h_write['file'].setValue(mov_out_path)
            h_write['file_type'].setValue("mov")
            self._set_safe_write_colorspace(h_write, ["rec709", "Output - Rec.709", "default (rec709)", "default"])

            for k in [
                ("mov64_format", "mov (QuickTime / MOV)"),
                ("mov64_codec", "appr"),
                ("mov_prores_codec_profile", "ProRes 4:2:2 HQ 10-bit")
            ]:
                if k[0] in h_write.knobs():
                    try: h_write[k[0]].setValue(k[1])
                    except: pass

            tab_horizon = nuke.Tab_Knob("horizon", "Horizon Studio Beta")
            h_write.addKnob(tab_horizon)
            fmt_preset = nuke.Enumeration_Knob("format_preset", "Format Preset", [
                "mov_444", "exr_raw", "exr_aces", "jpg_709", "mov_709", "mov_aces", "ngr_proxy", "ngr_fullres"
            ])
            fmt_preset.setValue("mov_709")
            h_write.addKnob(fmt_preset)
            h_write.setXYpos(trunk_x, 420)  # 与模块一 Write_Final_PNG (0, 420) 严格水平对齐！

            # 藏蓝卡片规整包裹 (X: 720 ~ 1260, Y: -60 ~ 580)
            bd_mid = nuke.createNode("BackdropNode", inpanel=False)
            bd_mid['label'].setValue(f"<center><b><font size='4'>Shot {shot} UE 预合成主干区</font></b></center>")
            bd_mid['note_font_size'].setValue(14)
            bd_mid['tile_color'].setValue(0x1b2d4400)
            bd_mid.setXYpos(trunk_x - 80, -60)
            bd_mid['bdwidth'].setValue(540)
            bd_mid['bdheight'].setValue(640)

            # Zone 3: AOV 拆层区 (从 X=1400 开始，保持 140px 超宽安全间隙)
            self._build_right_id_network(default_render_dir, actor_seq, material_seq, shot, id_start_x=1400)

            nuke.scriptSave()
            viewer = nuke.activeViewer()
            if viewer and final_merge:
                viewer.node().setInput(0, final_merge)

            nuke.message(
                f"【✅ 单层预合成网络构建完成】\n\n"
                f"🏷️ 自动版本判定: 已加载 [{detected_version}] 版本序列\n"
                f"📦 已加载分层清单 (包含镜头背景与完整拆层):\n"
                f"• [Read_UE_BG]: 镜头背景层已载入 ({prefix})\n"
                f"• [Read_Actor_ID]: Actor ID 层已载入并在右区展开 Cryptomatte\n"
                f"• [Read_Material_ID]: Material 材质层已载入并在右区拆出 Depth / Normal / Pos 与 Cryptomatte\n"
                f"• [全层 TimeOffset]: 所有 UE 渲染层均已自动挂载 TimeOffset(1000)\n"
                f"• [Merge_Comp_Over]: 实拍透明底板与 UE 背景压合 (Over 叠加)\n"
                f"• [HorizonWriteNode]: 标准审阅输出 (Apple ProRes 422 HQ / rec709)\n\n"
                f"👉 下一步操作指南:\n"
                f"1. 双击 Grade_UE_BG 或 ColorCorrect_UE_BG 调节环境色温色调；\n"
                f"2. 局部精修: 从右侧金色框的 Material 节点及 AOV 提取通道做景深/位置调色；\n"
                f"3. 局部选区提取: 从右侧金色框的 Cryptomatte 提取人物或具体材质选区；\n"
                f"4. 成片输出: 确认效果无误后，双击 HorizonWriteNode 节点，点击「Render」输出成片 MOV！"
            )

        # =====================================================================
        # 分支 B：多层装配流程 (多灯光分层 + Fog 雾气流 + 完整 ID 拆层)
        # =====================================================================
        else:
            def _get_layer_rank(p_name):
                p = p_name.lower()
                if "sky" in p: return 10
                if "env" in p: return 20
                if "key" in p: return 30
                if "fill" in p: return 40
                if "emi" in p or "emission" in p: return 50
                if "fog" in p: return 90
                return 60

            sorted_lights = sorted(content_layers.items(), key=lambda item: _get_layer_rank(item[0]))

            # 基底层 (Read -> TimeOffset -> Grade)
            base_prefix, base_data = sorted_lights[0]
            base_frames = sorted(base_data["frames"])
            base_seq_path = f"{default_render_dir}/{base_prefix}{base_data['sep']}%0{base_data['pad']}d.exr"
            clean_base = self._clean_layer_name(base_prefix)

            r_base = nuke.createNode("Read", inpanel=False)
            r_base.setName(f"Read_{clean_base}")
            r_base['file'].setValue(base_seq_path)
            r_base['first'].setValue(base_frames[0]); r_base['last'].setValue(base_frames[-1])
            r_base['origfirst'].setValue(base_frames[0]); r_base['origlast'].setValue(base_frames[-1])
            r_base.setXYpos(trunk_x, 0)

            t_base = nuke.createNode("TimeOffset", inpanel=False)
            t_base.setInput(0, r_base)
            t_base.setName(f"TimeOffset_{clean_base}")
            t_base['time_offset'].setValue(1000)
            t_base.setXYpos(trunk_x, 70)

            g_base = nuke.createNode("Grade", inpanel=False)
            g_base.setInput(0, t_base)
            g_base.setName(f"Grade_{clean_base}")
            g_base.setXYpos(trunk_x, 140)

            cur_pipe_node = g_base
            cur_trunk_y = 140
            created_light_names = [clean_base]

            # 链式组装其余灯光分层 (每路灯光与主干 Merge 严格 180° 水平直线对接)
            for prefix, data in sorted_lights[1:]:
                frames = sorted(data["frames"])
                seq_path = f"{default_render_dir}/{prefix}{data['sep']}%0{data['pad']}d.exr"
                clean_name = self._clean_layer_name(prefix)
                created_light_names.append(clean_name)
                is_fog = "fog" in prefix.lower()

                if is_fog:
                    # 雾气拥有 4 个节点，预留 240px 垂直安全步长，消除上下挤压
                    merge_y = cur_trunk_y + 240

                    r_fog = nuke.createNode("Read", inpanel=False)
                    r_fog.setName(f"Read_{clean_name}")
                    r_fog['file'].setValue(seq_path)
                    r_fog['first'].setValue(frames[0]); r_fog['last'].setValue(frames[-1])
                    r_fog['origfirst'].setValue(frames[0]); r_fog['origlast'].setValue(frames[-1])
                    r_fog.setXYpos(branch_x, merge_y - 180)

                    t_fog = nuke.createNode("TimeOffset", inpanel=False)
                    t_fog.setInput(0, r_fog)
                    t_fog.setName(f"TimeOffset_{clean_name}")
                    t_fog['time_offset'].setValue(1000)
                    t_fog.setXYpos(branch_x, merge_y - 120)

                    keyer_fog = nuke.createNode("Keyer", inpanel=False)
                    keyer_fog.setInput(0, t_fog)
                    keyer_fog.setName(f"Keyer_Fog_Alpha")
                    keyer_fog['operation'].setValue("luminance key")
                    try: keyer_fog['range'].setValue([0.012, 0.33, 1.0, 1.0])
                    except: pass
                    keyer_fog.setXYpos(branch_x, merge_y - 60)

                    g_fog = nuke.createNode("Grade", inpanel=False)
                    g_fog.setInput(0, keyer_fog)
                    g_fog.setName(f"Grade_{clean_name}")
                    g_fog.setXYpos(branch_x, merge_y)

                    # 水平 180° 正交直线对接进入主干
                    m_fog = nuke.createNode("Merge2", inpanel=False)
                    m_fog['operation'].setValue("screen")
                    m_fog['output'].setValue("rgb")
                    m_fog.setInput(0, cur_pipe_node)
                    m_fog.setInput(1, g_fog)
                    m_fog.setName(f"Merge_Screen_{clean_name}")
                    m_fog.setXYpos(trunk_x, merge_y)

                    cur_pipe_node = m_fog
                    cur_trunk_y = merge_y
                else:
                    # 普通灯光 3 级节点，预留 180px 垂直安全步长
                    merge_y = cur_trunk_y + 180

                    r_branch = nuke.createNode("Read", inpanel=False)
                    r_branch.setName(f"Read_{clean_name}")
                    r_branch['file'].setValue(seq_path)
                    r_branch['first'].setValue(frames[0]); r_branch['last'].setValue(frames[-1])
                    r_branch['origfirst'].setValue(frames[0]); r_branch['origlast'].setValue(frames[-1])
                    r_branch.setXYpos(branch_x, merge_y - 120)

                    t_branch = nuke.createNode("TimeOffset", inpanel=False)
                    t_branch.setInput(0, r_branch)
                    t_branch.setName(f"TimeOffset_{clean_name}")
                    t_branch['time_offset'].setValue(1000)
                    t_branch.setXYpos(branch_x, merge_y - 60)

                    g_branch = nuke.createNode("Grade", inpanel=False)
                    g_branch.setInput(0, t_branch)
                    g_branch.setName(f"Grade_{clean_name}")
                    g_branch.setXYpos(branch_x, merge_y)

                    # 水平 180° 正交直线对接进入主干
                    m_node = nuke.createNode("Merge2", inpanel=False)
                    m_node['operation'].setValue("plus")
                    m_node['output'].setValue("rgb")
                    m_node.setInput(0, cur_pipe_node)
                    m_node.setInput(1, g_branch)
                    m_node.setName(f"Merge_Plus_{clean_name}")
                    m_node.setXYpos(trunk_x, merge_y)

                    cur_pipe_node = m_node
                    cur_trunk_y = merge_y

            # 叠合实拍底板
            over_y = cur_trunk_y + 160
            fg_pipe = None
            for n in nuke.allNodes("Premult"):
                if "Premult_Plate" in n.name() or f"Premult_{shot}" in n.name():
                    fg_pipe = n
                    break

            if not fg_pipe:
                bg_png_dir = os.path.join(workarea_dir, "bg").replace('\\', '/')
                png_pattern = f"{bg_png_dir}/bg_{shot}_%04d.png"
                read_fg = nuke.createNode("Read", inpanel=False)
                read_fg.setName("Read_Exported_PNG")
                read_fg['file'].setValue(png_pattern)
                read_fg['first'].setValue(int(nuke.root()['first_frame'].value()))
                read_fg['last'].setValue(int(nuke.root()['last_frame'].value()))
                read_fg['origfirst'].setValue(int(nuke.root()['first_frame'].value()))
                read_fg['origlast'].setValue(int(nuke.root()['last_frame'].value()))
                read_fg.setXYpos(trunk_x - 160, over_y)
                fg_pipe = read_fg

            final_merge = nuke.createNode("Merge2", inpanel=False)
            final_merge['operation'].setValue("over")
            final_merge.setInput(0, cur_pipe_node)
            final_merge.setInput(1, fg_pipe)
            final_merge.setName("Merge_Comp_Over")
            final_merge.setXYpos(trunk_x, over_y)

            # 输出审阅节点
            preview_dir = os.path.normpath(os.path.join(default_render_dir, "..", "preview")).replace('\\', '/')
            if not os.path.exists(preview_dir):
                try: os.makedirs(preview_dir)
                except: pass

            nk_base = os.path.splitext(os.path.basename(nuke.root().name()))[0]
            mov_out_path = f"{preview_dir}/{nk_base}.mov"

            h_write = nuke.createNode("Write", inpanel=False)
            h_write.setInput(0, final_merge)
            h_write.setName("HorizonWriteNode")
            h_write['file'].setValue(mov_out_path)
            h_write['file_type'].setValue("mov")
            self._set_safe_write_colorspace(h_write, ["rec709", "Output - Rec.709", "default (rec709)", "default"])

            for k in [
                ("mov64_format", "mov (QuickTime / MOV)"),
                ("mov64_codec", "appr"),
                ("mov_prores_codec_profile", "ProRes 4:2:2 HQ 10-bit")
            ]:
                if k[0] in h_write.knobs():
                    try: h_write[k[0]].setValue(k[1])
                    except: pass

            tab_horizon = nuke.Tab_Knob("horizon", "Horizon Studio Beta")
            h_write.addKnob(tab_horizon)
            fmt_preset = nuke.Enumeration_Knob("format_preset", "Format Preset", [
                "mov_444", "exr_raw", "exr_aces", "jpg_709", "mov_709", "mov_aces", "ngr_proxy", "ngr_fullres"
            ])
            fmt_preset.setValue("mov_709")
            h_write.addKnob(fmt_preset)
            h_write.setXYpos(trunk_x, over_y + 90)

            # 藏蓝卡片规整包裹 (X: 720 ~ 1260)
            bd_mid = nuke.createNode("BackdropNode", inpanel=False)
            bd_mid['label'].setValue(f"<center><b><font size='4'>Shot {shot} UE 预合成主干区</font></b></center>")
            bd_mid['note_font_size'].setValue(14)
            bd_mid['tile_color'].setValue(0x1b2d4400)
            bd_mid.setXYpos(trunk_x - 80, -60)
            bd_mid['bdwidth'].setValue(540)
            bd_mid['bdheight'].setValue(over_y + 220)

            # Zone 3: AOV 拆层区 (从 X=1400 开始，保持 140px 超宽安全间隙)
            self._build_right_id_network(default_render_dir, actor_seq, material_seq, shot, id_start_x=1400)

            nuke.scriptSave()
            viewer = nuke.activeViewer()
            if viewer and final_merge:
                viewer.node().setInput(0, final_merge)

            lights_str = "、".join(created_light_names)
            nuke.message(
                f"【✅ 多层渲染分层预合成装配完成】\n\n"
                f"🏷️ 自动版本判定: 已加载 [{detected_version}] 版本序列\n"
                f"📦 已加载分层清单 (共 {len(created_light_names)} 个通道):\n"
                f"• 灯光通道: {lights_str}\n"
                f"• [全层 TimeOffset]: 每个分层均已挂载 TimeOffset(1000)，解决 0001 起始帧偏移\n"
                f"• [Fog 专用处理]: 雾气支路已配置 Keyer(Luminance Key) 提取通道与 Grade 调色\n"
                f"• [链式加法树]: 每一路灯光水平直角汇入主干 Merge(plus)\n"
                f"• [右区金黄卡片]: 独立生成 Actor/Material Cryptomatte 与 P/N/Z 通道\n\n"
                f"👉 下一步操作指南:\n"
                f"1. 独立灯光调色: 双击右侧平行排布的 Grade_Key、Grade_Fill 等节点，自由调节每盏灯光强弱与色调；\n"
                f"2. 雾气与消光微调: 双击 Keyer_Fog_Alpha 微调雾气提取范围，双击 Grade_Fog 调整雾气浓度；\n"
                f"3. 局部选区提取: 从右侧金色框的 Cryptomatte 或 AOV 节点引出连线做局部材质精修；\n"
                f"4. 成片审阅导出: 确认合成无误后，双击 HorizonWriteNode 节点，点击「Render」输出成片 MOV！"
            )


# =========================================================================
# 菜单统一接口 (二合一纯净版)
# =========================================================================
def show_prep_menu():
    pipe = LiangLiangNukePipeline()
    pipe.build_plate_prep_network()

def show_autocomp_menu():
    pipe = LiangLiangNukePipeline()
    pipe.build_unified_autocomp_network()