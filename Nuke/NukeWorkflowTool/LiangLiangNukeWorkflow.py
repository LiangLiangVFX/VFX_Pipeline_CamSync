# -*- coding: utf-8 -*-
"""
LiangLiang Nuke Pipeline Workflow (工业级极简正交布局版·横向四模块对齐 + RVM/MatAnyone2双AI引擎)
-------------------------------------------------------------------------
模块从左至右顺序：
1. 实拍预处理与输出UE底板 (X: -60 ~ 580)
2. 【AI 抠像与修补模块】MatAnyone 2 (CVPR 2026) 发丝级 (X: 680 ~ 1240)
3. UE 预合成主干区 [单层/多层自适应] (X: 1340 ~ 1960)
4. 分层 AOV 与 Cryptomatte (供合成提取) (X: 2060 ~ 2980)
-------------------------------------------------------------------------
Author: LiangLiangArtist
Contact: liangliangvfx@gmail.com
"""

import os
import re
import threading
import subprocess
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
        fmt_name = "2048x1152_Film"
        target_fmt_str = "2048 1152 1.0 2048x1152_Film"
        try:
            nuke.addFormat(target_fmt_str)
        except Exception:
            pass

        root = nuke.root()
        try:
            root['format'].setValue(fmt_name)
        except Exception:
            try:
                root['format'].setValue("2048 1152")
            except Exception:
                pass

        root['fps'].setValue(25.0)
        if first_frame is not None and last_frame is not None:
            root['first_frame'].setValue(int(first_frame))
            root['last_frame'].setValue(int(last_frame))

    def _update_watermark_position(self):
        """
        将『模版由脚本自动生成 v1.0.0』统一放置在上方所有模块背板的正下方，绝不与任何节点或背板重叠
        """
        for n in nuke.allNodes("StickyNote"):
            if "Pipeline_Watermark" in n.name():
                nuke.delete(n)

        max_bottom_y = 600
        min_left_x = -60
        bds = nuke.allNodes("BackdropNode")
        if bds:
            min_left_x = min([int(b.xpos()) for b in bds])
            max_bottom_y = max([int(b.ypos() + b['bdheight'].value()) for b in bds])

        note = nuke.createNode("StickyNote", inpanel=False)
        note.setName("Pipeline_Watermark")
        note['label'].setValue("<font color='#888888' size='3'><b>模版由脚本自动生成 v1.0.0</b></font>")
        note['note_font_size'].setValue(11)
        note.setXYpos(min_left_x, max_bottom_y + 50)
        return note

    def _connect_viewer1(self, target_node, xpos=None, ypos=None):
        """统一获取或创建 Viewer1 并连接到目标节点正下方"""
        if not target_node:
            return None
        viewer_node = nuke.toNode("Viewer1")
        if not viewer_node:
            all_viewers = nuke.allNodes("Viewer")
            viewer_node = all_viewers[0] if all_viewers else nuke.createNode("Viewer", inpanel=False)
            viewer_node.setName("Viewer1")
        viewer_node.setInput(0, target_node)
        vx = xpos if xpos is not None else int(target_node.xpos())
        vy = ypos if ypos is not None else int(target_node.ypos() + 90)
        viewer_node.setXYpos(vx, vy)
        return viewer_node

    def _set_safe_write_colorspace(self, write_node, preferred_spaces):
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
        except Exception:
            pass
        try:
            cs_knob.setValue(preferred_spaces[0])
        except Exception:
            pass

    def _get_valid_colorspace_value(self, knob, preferred_candidates):
        try:
            available_values = knob.values()
            for cand in preferred_candidates:
                for avail in available_values:
                    if avail.lower() == cand.lower():
                        return avail
            return knob.value()
        except Exception:
            return None

    # =========================================================================
    # 模块 1 (最左 X: -60 ~ 580)：实拍预处理与输出UE底板
    # =========================================================================
    def build_plate_prep_network(self):
        ep, shot, workarea_dir, shot_root_dir = self.get_current_pipeline_context()
        if not workarea_dir:
            return

        if nuke.toNode("Read_Plate") or nuke.toNode("Write_Final_PNG"):
            if not nuke.ask("⚠️ 检测到当前工程已存在「实拍预处理」节点！\n\n是否清除旧节点并重新构建？"):
                return
            for name in ["Read_Plate", "Colorspace_LogC_to_Linear", "ColorMode_Switch",
                         "Holdout_Roto_KEEP", "Blur_InM", "Garbage_Roto_REMOVE", "Blur_OutM",
                         "Keyer_Alpha", "Copy_Alpha", "Premult_Plate", "Write_Final_PNG", "Backdrop_PlatePrep"]:
                n = nuke.toNode(name)
                if n:
                    nuke.delete(n)
            for bd in nuke.allNodes("BackdropNode"):
                if "实拍预处理" in bd['label'].value():
                    nuke.delete(bd)

        filter_exts = "*.exr *.dpx *.tif *.tiff *.png *.jpg *.jpeg *.mov *.mp4 *.mxf"
        chosen_file = nuke.getFilename(f"【选择 Shot {shot} 实拍原始素材】", filter_exts)
        if not chosen_file:
            return

        chosen_file = os.path.normpath(chosen_file).replace('\\', '/')
        file_dir = os.path.dirname(chosen_file)
        base_name = os.path.basename(chosen_file)
        name_ext = os.path.splitext(base_name)[1].lower()

        video_exts = ('.mov', '.mp4', '.mxf', '.avi')
        is_video = name_ext in video_exts
        seq_pattern = chosen_file
        first_f, last_f = 1001, 1039

        if is_video:
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
            try:
                os.makedirs(target_bg_dir)
            except Exception:
                pass

        self._setup_project_root_settings(first_frame=first_f, last_frame=last_f)

        for n in nuke.allNodes():
            n.setSelected(False)

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

        col_convert = nuke.createNode("Colorspace", inpanel=False)
        col_convert.setInput(0, read_plate)
        col_convert.setName("Colorspace_LogC_to_Linear")
        valid_in = self._get_valid_colorspace_value(col_convert['colorspace_in'], ["AlexaV3LogC", "LogC", "linear"])
        valid_out = self._get_valid_colorspace_value(col_convert['colorspace_out'], ["linear", "scene_linear", "ACEScg", "Linear"])
        if valid_in:
            col_convert['colorspace_in'].setValue(valid_in)
        if valid_out:
            col_convert['colorspace_out'].setValue(valid_out)
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

        holdout_roto = nuke.createNode("Roto", inpanel=False)
        holdout_roto.setInput(0, read_plate)
        holdout_roto.setName("Holdout_Roto_KEEP")
        holdout_roto['label'].setValue("【圈要的: 补实心 / AI首帧引导】")
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
            if cw in kl.knobs():
                kl[cw].setValue(1.0)
                break
        for cb in ['clipblack', 'clipBlack', 'clip_black']:
            if cb in kl.knobs():
                kl[cb].setValue(0.0)
                break
        for sh in ['show', 'view']:
            if sh in kl.knobs():
                kl[sh].setValue("Final Result")
                break

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

        bd = nuke.createNode("BackdropNode", inpanel=False)
        bd.setName("Backdrop_PlatePrep")
        bd['label'].setValue(f"<center><b><font size='4'>Shot {shot} 实拍预处理与输出UE底板</font></b></center>")
        bd['note_font_size'].setValue(14)
        bd['tile_color'].setValue(0x1a402500)
        bd.setXYpos(-60, -60)
        bd['bdwidth'].setValue(640)
        bd['bdheight'].setValue(660)
        if 'z_order' in bd.knobs():
            bd['z_order'].setValue(-1)

        self._update_watermark_position()
        nuke.scriptSave()

        self._connect_viewer1(kl, xpos=280, ypos=320)
        nuke.show(kl)
        nuke.message(f"【✅ 实拍预处理网络就绪】\n\n• 尺寸规格: 2048x1152 / 25fps\n• 帧数范围: {first_f} - {last_f}\n• 输出配置: default (sRGB) + 渲染完自动弹窗")

    # =========================================================================
    # 模块 4 (最右 X: 2060 ~ 2980)：分层 AOV 与 Cryptomatte (供合成提取)
    # =========================================================================
    def _create_single_aov_shuffle(self, target_node, layer_name, node_name, xpos, ypos):
        try:
            nuke.tcl(f"add_layer {{{layer_name} {layer_name}.red {layer_name}.green {layer_name}.blue {layer_name}.alpha}}")
        except Exception:
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
        except Exception:
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
        except Exception:
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
                prefix, sep, digits = m.group(1), m.group(2), m.group(3)
                frame, pad = int(digits), len(digits)
                if prefix not in sequences:
                    sequences[prefix] = {"frames": [], "sep": sep, "pad": pad}
                sequences[prefix]["frames"].append(frame)
        return sequences

    def _clean_layer_name(self, raw_name):
        n = re.sub(r'^(cam\d+_|ep\d+_|shot\d+_)', '', raw_name, flags=re.IGNORECASE)
        return re.sub(r'[^a-zA-Z0-9_]', '_', n)

    def _build_right_id_network(self, default_render_dir, actor_seq, material_seq, shot, id_start_x=2060):
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
            t_actor.setXYpos(actor_col_x, 90)
            self._create_cryptomatte_node(t_actor, "Cryptomatte_Actor", actor_col_x, 260)

        mat_col_x = id_start_x + 520
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
            t_mat.setXYpos(mat_col_x, 90)

            dot_mat = nuke.createNode("Dot", inpanel=False)
            dot_mat.setInput(0, t_mat)
            dot_mat.setName("Dot_Material_ID")
            dot_mat.setXYpos(mat_col_x + 34, 165)

            depth_layer = self._find_matching_layer(r_mat, "depth")
            normal_layer = self._find_matching_layer(r_mat, "normal")
            pos_layer = self._find_matching_layer(r_mat, "pos")

            # 拉开 4 个节点的横向间距至 160px，彻底避免长节点名重叠
            self._create_single_aov_shuffle(dot_mat, depth_layer, "FinalImageMovieRenderQueue_WorldDepth_Shuffel", mat_col_x - 240, 260)
            self._create_single_aov_shuffle(dot_mat, normal_layer, "FinalImageMovieRenderQueue_WorldNormal_Shuffel", mat_col_x - 80, 260)
            self._create_single_aov_shuffle(dot_mat, pos_layer, "FinalImageMovieRenderQueue_WorldPos_Shuffel", mat_col_x + 80, 260)
            self._create_cryptomatte_node(dot_mat, "Cryptomatte_Material", mat_col_x + 240, 260)

        bd_right = nuke.createNode("BackdropNode", inpanel=False)
        bd_right.setName("Backdrop_AOV_ID")
        bd_right['label'].setValue("<center><b><font size='4' color='#ffcc00'>分层 AOV 与 Cryptomatte (供合成提取)</font></b><br>ID / Material (WorldDepth, WorldPos, WorldNormal)</center>")
        bd_right['note_font_size'].setValue(14)
        bd_right['tile_color'].setValue(0x55440000)
        bd_right.setXYpos(id_start_x, -60)
        bd_right['bdwidth'].setValue(920)
        bd_right['bdheight'].setValue(660)
        if 'z_order' in bd_right.knobs():
            bd_right['z_order'].setValue(-1)

    # =========================================================================
    # 模块 3 (左三 X: 1340 ~ 1960)：UE 渲染分层自动预合成与 ID 拆层 (兼容单层与多层)
    # =========================================================================
    def _find_best_foreground_premult(self, shot, workarea_dir, fallback_x, fallback_y):
        """
        优先连接 AI 模块的 Premult_MatAnyone2；若未使用 AI 模块则连接 Premult_Plate
        """
        pm_ai = nuke.toNode("Premult_MatAnyone2")
        if pm_ai:
            return pm_ai
        pm_plate = nuke.toNode("Premult_Plate")
        if pm_plate:
            return pm_plate
        for n in nuke.allNodes("Premult"):
            if f"Premult_{shot}" in n.name():
                return n

        bg_png_dir = os.path.join(workarea_dir, "bg").replace('\\', '/')
        png_pattern = f"{bg_png_dir}/bg_{shot}_%04d.png"
        read_fg = nuke.createNode("Read", inpanel=False)
        read_fg.setName("Read_Exported_PNG")
        read_fg['file'].setValue(png_pattern)
        read_fg['first'].setValue(int(nuke.root()['first_frame'].value()))
        read_fg['last'].setValue(int(nuke.root()['last_frame'].value()))
        read_fg['origfirst'].setValue(int(nuke.root()['first_frame'].value()))
        read_fg['origlast'].setValue(int(nuke.root()['last_frame'].value()))
        read_fg.setXYpos(fallback_x, fallback_y)
        return read_fg

    def build_unified_autocomp_network(self):
        ep, shot, workarea_dir, shot_root_dir = self.get_current_pipeline_context()
        if not workarea_dir:
            return

        if nuke.toNode("HorizonWriteNode") or nuke.toNode("Read_UE_BG"):
            if not nuke.ask("⚠️ 检测到当前工程已存在「UE 预合成」节点！\n\n是否清除旧节点并重新构建？"):
                return
            for name in ["Read_UE_BG", "TimeOffset_UE_BG", "Grade_UE_BG", "ColorCorrect_UE_BG",
                         "Merge_Comp_Over", "HorizonWriteNode", "Read_Exported_PNG",
                         "Read_Actor_ID", "TimeOffset_Actor_ID", "Cryptomatte_Actor",
                         "Read_Material_ID", "TimeOffset_Material_ID", "Dot_Material_ID",
                         "FinalImageMovieRenderQueue_WorldDepth_Shuffel",
                         "FinalImageMovieRenderQueue_WorldNormal_Shuffel",
                         "FinalImageMovieRenderQueue_WorldPos_Shuffel",
                         "Cryptomatte_Material", "Backdrop_UE_Comp", "Backdrop_AOV_ID"]:
                n = nuke.toNode(name)
                if n:
                    nuke.delete(n)
            # 仅清理 X >= 1300 (模块3和模块4区域) 的动态分层节点，绝不误伤左侧 AI 模块 (X: 680~1240)
            ai_protected = {"Read_MatAnyone2_Alpha", "Shuffle_AI_Alpha", "Grade_AI_Hair",
                            "FilterErode_AI_Edge", "Blur_AI_Edge", "Copy_MatAnyone2_Alpha",
                            "Premult_MatAnyone2", "Read_AI_RVM_Plate"}
            for n in nuke.allNodes():
                if n.name() not in ai_protected and n.xpos() >= 1300:
                    if any(n.name().startswith(p) for p in ["Merge_Plus_", "Merge_Screen_", "Keyer_Fog_", "Grade_", "TimeOffset_", "Read_"]):
                        nuke.delete(n)
            for bd in nuke.allNodes("BackdropNode"):
                if any(kw in bd['label'].value() for kw in ["UE 预合成主干区", "分层 AOV 与 Cryptomatte"]):
                    nuke.delete(bd)

        default_render_dir = ""
        detected_version = "最新版"
        if shot_root_dir:
            publish_dir = os.path.normpath(os.path.join(shot_root_dir, "ue", "publish")).replace('\\', '/')
            if os.path.exists(publish_dir):
                v_dirs = [d for d in os.listdir(publish_dir) if re.match(r'^v\d+$', d, re.IGNORECASE) and os.path.isdir(os.path.join(publish_dir, d))]
                if v_dirs:
                    v_dirs.sort(key=lambda x: int(re.search(r'\d+', x).group(0)))
                    latest_v = v_dirs[-1]
                    test_render = os.path.normpath(os.path.join(publish_dir, latest_v, "render")).replace('\\', '/')
                    if os.path.exists(test_render):
                        default_render_dir = test_render
                        detected_version = latest_v

        if not default_render_dir or not os.path.exists(default_render_dir):
            chosen = nuke.getFilename("选择 UE 渲染输出的 render 文件夹", "", type="dir")
            if not chosen:
                return
            default_render_dir = os.path.normpath(chosen).replace('\\', '/')

        if os.path.isfile(default_render_dir):
            default_render_dir = os.path.dirname(default_render_dir).replace('\\', '/')

        sequences = self._scan_exr_sequences(default_render_dir)
        if not sequences:
            nuke.message("render 目录下未找到任何 EXR 序列文件！\n" + default_render_dir)
            return

        self._setup_project_root_settings()
        for n in nuke.allNodes():
            n.setSelected(False)

        actor_seq, material_seq = None, None
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

        light_keywords = ['env', 'key', 'fill', 'sky', 'fog', 'heightfog', 'easyfog', 'emi', 'emission', 'lgt']
        is_multi = len(content_layers) > 1 or any(k in list(content_layers.keys())[0].lower() for k in light_keywords)

        # 模块 3 位于模块 2 (AI模块 X: 680~1240) 右侧，从 X=1340 开始
        bd_mid_x = 1340
        trunk_x = 1520
        branch_x = 1780
        id_module_x = 2060

        # 单层分支
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
            over_y = 330

            # 自动优先连接 Premult_MatAnyone2 (如果走了 AI 模块)
            fg_pipe = self._find_best_foreground_premult(shot, workarea_dir, trunk_x - 140, over_y)

            final_merge = nuke.createNode("Merge2", inpanel=False)
            final_merge['operation'].setValue("over")
            final_merge.setInput(0, cur_comp_pipe)
            final_merge.setInput(1, fg_pipe)
            final_merge.setName("Merge_Comp_Over")
            final_merge.setXYpos(trunk_x, over_y)

            preview_dir = os.path.normpath(os.path.join(default_render_dir, "..", "preview")).replace('\\', '/')
            if not os.path.exists(preview_dir):
                try:
                    os.makedirs(preview_dir)
                except Exception:
                    pass
            nk_base = os.path.splitext(os.path.basename(nuke.root().name()))[0]
            mov_out_path = f"{preview_dir}/{nk_base}.mov"

            h_write = nuke.createNode("Write", inpanel=False)
            h_write.setInput(0, final_merge)
            h_write.setName("HorizonWriteNode")
            h_write['file'].setValue(mov_out_path)
            h_write['file_type'].setValue("mov")
            self._set_safe_write_colorspace(h_write, ["rec709", "Output - Rec.709", "default (rec709)", "default"])
            for k in [("mov64_format", "mov (QuickTime / MOV)"), ("mov64_codec", "appr"), ("mov_prores_codec_profile", "ProRes 4:2:2 HQ 10-bit")]:
                if k[0] in h_write.knobs():
                    try:
                        h_write[k[0]].setValue(k[1])
                    except Exception:
                        pass
            tab_horizon = nuke.Tab_Knob("horizon", "Horizon Studio Beta")
            h_write.addKnob(tab_horizon)
            fmt_preset = nuke.Enumeration_Knob("format_preset", "Format Preset", ["mov_444", "exr_raw", "exr_aces", "jpg_709", "mov_709", "mov_aces", "ngr_proxy", "ngr_fullres"])
            fmt_preset.setValue("mov_709")
            h_write.addKnob(fmt_preset)
            h_write.setXYpos(trunk_x, 420)

            bd_mid = nuke.createNode("BackdropNode", inpanel=False)
            bd_mid.setName("Backdrop_UE_Comp")
            bd_mid['label'].setValue(f"<center><b><font size='4'>Shot {shot} UE 预合成主干区</font></b></center>")
            bd_mid['note_font_size'].setValue(14)
            bd_mid['tile_color'].setValue(0x1b2d4400)
            bd_mid.setXYpos(bd_mid_x, -60)
            bd_mid['bdwidth'].setValue(620)
            bd_mid['bdheight'].setValue(660)
            if 'z_order' in bd_mid.knobs():
                bd_mid['z_order'].setValue(-1)

            self._build_right_id_network(default_render_dir, actor_seq, material_seq, shot, id_start_x=id_module_x)
            # HorizonWriteNode 后面直接接 Viewer1
            self._connect_viewer1(h_write, xpos=trunk_x, ypos=520)
            self._update_watermark_position()
            nuke.scriptSave()

            nuke.message(f"【✅ 单层预合成网络构建完成】\n\n版本: [{detected_version}]\n前景已自动连接: [{fg_pipe.name()}]\nHorizonWriteNode 后已自动挂载 Viewer1。")

        # 多层分支
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

            for prefix, data in sorted_lights[1:]:
                frames = sorted(data["frames"])
                seq_path = f"{default_render_dir}/{prefix}{data['sep']}%0{data['pad']}d.exr"
                clean_name = self._clean_layer_name(prefix)
                is_fog = "fog" in prefix.lower()

                if is_fog:
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
                    keyer_fog.setName("Keyer_Fog_Alpha")
                    keyer_fog['operation'].setValue("luminance key")
                    try:
                        keyer_fog['range'].setValue([0.012, 0.33, 1.0, 1.0])
                    except Exception:
                        pass
                    keyer_fog.setXYpos(branch_x, merge_y - 60)

                    g_fog = nuke.createNode("Grade", inpanel=False)
                    g_fog.setInput(0, keyer_fog)
                    g_fog.setName(f"Grade_{clean_name}")
                    g_fog.setXYpos(branch_x, merge_y)

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

                    m_node = nuke.createNode("Merge2", inpanel=False)
                    m_node['operation'].setValue("plus")
                    m_node['output'].setValue("rgb")
                    m_node.setInput(0, cur_pipe_node)
                    m_node.setInput(1, g_branch)
                    m_node.setName(f"Merge_Plus_{clean_name}")
                    m_node.setXYpos(trunk_x, merge_y)
                    cur_pipe_node = m_node
                    cur_trunk_y = merge_y

            over_y = cur_trunk_y + 160
            # 自动优先连接 Premult_MatAnyone2 (如果走了 AI 模块)
            fg_pipe = self._find_best_foreground_premult(shot, workarea_dir, trunk_x - 140, over_y)

            final_merge = nuke.createNode("Merge2", inpanel=False)
            final_merge['operation'].setValue("over")
            final_merge.setInput(0, cur_pipe_node)
            final_merge.setInput(1, fg_pipe)
            final_merge.setName("Merge_Comp_Over")
            final_merge.setXYpos(trunk_x, over_y)

            preview_dir = os.path.normpath(os.path.join(default_render_dir, "..", "preview")).replace('\\', '/')
            if not os.path.exists(preview_dir):
                try:
                    os.makedirs(preview_dir)
                except Exception:
                    pass
            nk_base = os.path.splitext(os.path.basename(nuke.root().name()))[0]
            mov_out_path = f"{preview_dir}/{nk_base}.mov"

            h_write = nuke.createNode("Write", inpanel=False)
            h_write.setInput(0, final_merge)
            h_write.setName("HorizonWriteNode")
            h_write['file'].setValue(mov_out_path)
            h_write['file_type'].setValue("mov")
            self._set_safe_write_colorspace(h_write, ["rec709", "Output - Rec.709", "default (rec709)", "default"])
            for k in [("mov64_format", "mov (QuickTime / MOV)"), ("mov64_codec", "appr"), ("mov_prores_codec_profile", "ProRes 4:2:2 HQ 10-bit")]:
                if k[0] in h_write.knobs():
                    try:
                        h_write[k[0]].setValue(k[1])
                    except Exception:
                        pass
            tab_horizon = nuke.Tab_Knob("horizon", "Horizon Studio Beta")
            h_write.addKnob(tab_horizon)
            fmt_preset = nuke.Enumeration_Knob("format_preset", "Format Preset", ["mov_444", "exr_raw", "exr_aces", "jpg_709", "mov_709", "mov_aces", "ngr_proxy", "ngr_fullres"])
            fmt_preset.setValue("mov_709")
            h_write.addKnob(fmt_preset)
            h_write.setXYpos(trunk_x, over_y + 90)

            bd_mid = nuke.createNode("BackdropNode", inpanel=False)
            bd_mid.setName("Backdrop_UE_Comp")
            bd_mid['label'].setValue(f"<center><b><font size='4'>Shot {shot} UE 预合成主干区</font></b></center>")
            bd_mid['note_font_size'].setValue(14)
            bd_mid['tile_color'].setValue(0x1b2d4400)
            bd_mid.setXYpos(bd_mid_x, -60)
            bd_mid['bdwidth'].setValue(620)
            bd_mid['bdheight'].setValue(over_y + 280)
            if 'z_order' in bd_mid.knobs():
                bd_mid['z_order'].setValue(-1)

            self._build_right_id_network(default_render_dir, actor_seq, material_seq, shot, id_start_x=id_module_x)
            # HorizonWriteNode 后面直接接 Viewer1
            self._connect_viewer1(h_write, xpos=trunk_x, ypos=over_y + 180)
            self._update_watermark_position()
            nuke.scriptSave()

            nuke.message(f"【✅ 多层预合成网络构建完成】\n\n版本: [{detected_version}]\n前景已自动连接: [{fg_pipe.name()}]\nHorizonWriteNode 后已自动挂载 Viewer1。")


# =========================================================================
# AI 双引擎调度核心 (模块 2 位于左二 X: 680 ~ 1240，正交无重叠)
# =========================================================================
class AIMattingDispatcher(object):
    def __init__(self):
        self.suite_root = self._locate_suite_root()

    def _locate_suite_root(self):
        # 1. 优先读取环境变量 LL_AI_SUITE_ROOT (由 AI_VFX_Pipeline_Suite 一键注册脚本写入)
        env_root = os.environ.get("LL_AI_SUITE_ROOT", "")
        
        # 2. 自动探测当前脚本所在仓库 (VFX_Pipeline_CamSync) 隔壁的同级目录
        curr_script_dir = os.path.dirname(os.path.abspath(__file__)).replace('\\', '/')
        sibling_root = os.path.abspath(os.path.join(curr_script_dir, "../../../AI_VFX_Pipeline_Suite")).replace('\\', '/')
        
        user_github_dir = os.path.expanduser("~/Documents/GitHub/AI_VFX_Pipeline_Suite").replace('\\', '/')
        
        cand_roots = [
            env_root,
            sibling_root,
            user_github_dir,
            "C:/Users/zhaoliang/Documents/GitHub/AI_VFX_Pipeline_Suite",
            "D:/GitHub/AI_VFX_Pipeline_Suite",
            "E:/GitHub/AI_VFX_Pipeline_Suite",
            "D:/AI_VFX_Pipeline_Suite",
            "E:/AI_VFX_Pipeline_Suite",
            "C:/AI_VFX_Pipeline_Suite",
            "X:/filmserver/pipeline/AI_VFX_Pipeline_Suite"
        ]
        for r in cand_roots:
            if not r:
                continue
            r_clean = r.strip().strip('"').replace('\\', '/')
            py_exe = os.path.join(r_clean, "python_embeded/python.exe").replace('\\', '/')
            if os.path.exists(py_exe):
                return r_clean
            py_exe_legacy = os.path.join(r_clean, "ComfyUI_windows_portable/python_embeded/python.exe").replace('\\', '/')
            if os.path.exists(py_exe_legacy):
                return r_clean
        return None

    def _get_python_exe(self):
        if not self.suite_root:
            return None
        p1 = os.path.join(self.suite_root, "python_embeded/python.exe").replace('\\', '/')
        if os.path.exists(p1):
            return p1
        return os.path.join(self.suite_root, "ComfyUI_windows_portable/python_embeded/python.exe").replace('\\', '/')

    def _get_clean_ai_env(self, py_exe):
        """清洗 Nuke 注入的环境变量，防止底层 DLL 冲突并强制开启 UTF-8 编码"""
        clean_env = os.environ.copy()
        for bad_key in [
            "PYTHONPATH", "PYTHONHOME", "NUKE_PATH", "NUKE_TEMP_DIR",
            "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "OCIO"
        ]:
            clean_env.pop(bad_key, None)

        py_dir = os.path.normpath(os.path.dirname(py_exe))
        torch_lib = os.path.normpath(os.path.join(py_dir, "Lib", "site-packages", "torch", "lib"))
        scripts_dir = os.path.normpath(os.path.join(py_dir, "Scripts"))

        raw_paths = clean_env.get("PATH", "").split(os.pathsep)
        filtered_paths = [
            p for p in raw_paths
            if "nuke" not in p.lower() and "foundry" not in p.lower()
        ]
        priority_paths = [torch_lib, py_dir, scripts_dir]
        clean_env["PATH"] = os.pathsep.join(priority_paths + filtered_paths)
        clean_env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
        clean_env["PYTHONNOUSERSITE"] = "1"
        clean_env["PYTHONIOENCODING"] = "utf-8"
        clean_env["PYTHONUTF8"] = "1"
        return clean_env

    def _detect_sequence_pattern(self, folder_path, prefix_filter="", ext=".png"):
        if not os.path.exists(folder_path):
            return None, None, None
        files = [
            f for f in os.listdir(folder_path)
            if f.lower().endswith(ext.lower()) and (not prefix_filter or f.lower().startswith(prefix_filter.lower()))
        ]
        if not files:
            return None, None, None
        files.sort()
        m_first = re.search(r'^(.*?)(\d+)' + re.escape(ext) + r'$', files[0], re.IGNORECASE)
        m_last = re.search(r'^(.*?)(\d+)' + re.escape(ext) + r'$', files[-1], re.IGNORECASE)
        if m_first and m_last:
            prefix = m_first.group(1)
            first_f, last_f = int(m_first.group(2)), int(m_last.group(2))
            pad_len = len(m_first.group(2))
            pattern = os.path.join(folder_path, f"{prefix}%0{pad_len}d{ext}").replace('\\', '/')
            return pattern, first_f, last_f
        return None, None, None

    # =========================================================================
    # 模块 2 (左二 X: 680 ~ 1240)：【AI 抠像与修补模块】MatAnyone 2 (CVPR 2026) 发丝级
    # =========================================================================
    def _import_matanyone2_nodes(self, roto_dir, prefix_str):
        """
        在「实拍预处理」右侧 (X: 680 ~ 1240) 构建纯净无 Roto 硬边的 AI 发丝级抠像模块：
        - 去掉 Roto 节点，保留 Read -> Shuffle -> Grade -> FilterErode -> Blur 柔边微调链
        - B 端通过正交拐点 Dot_AI_MainB 承接左侧实拍预处理的 Copy_Alpha
        - 自动把 Merge_Comp_Over (单/多层 UE 预合成) 前景连过来，并在 HorizonWriteNode 后接 Viewer1
        """
        alpha_pat, a_first, a_last = self._detect_sequence_pattern(roto_dir, prefix_filter=f"{prefix_str}_alpha_", ext=".png")
        if not alpha_pat:
            alpha_pat, a_first, a_last = self._detect_sequence_pattern(roto_dir, prefix_filter="matanyone2_alpha_", ext=".png")

        if not alpha_pat:
            nuke.message(f"在目录中未找到 MatAnyone 2 Alpha 序列：\n{roto_dir}")
            return False

        for n in nuke.allNodes():
            n.setSelected(False)

        # 1. 清理旧的 AI 节点与背板（包含之前残留的 Roto 修补节点）
        ai_node_names = (
            "Backdrop_MatAnyone2",
            "Read_MatAnyone2_Alpha",
            "Shuffle_AI_Alpha",
            "Roto_AI_Fix",
            "Roto_AI_Keep",
            "Merge_AI_Keep",
            "Roto_AI_Remove",
            "Merge_AI_Remove",
            "Grade_AI_Hair",
            "FilterErode_AI_Edge",
            "Blur_AI_Edge",
            "Copy_MatAnyone2_Alpha",
            "Premult_MatAnyone2",
            "Dot_AI_MainB",
            "Read_MatAnyone2_RGBA",
            "Shuffle_MatAnyone2_Alpha"
        )
        for old_name in ai_node_names:
            old_n = nuke.toNode(old_name)
            if old_n:
                nuke.delete(old_n)

        # 2. 定位左侧「实拍预处理」的 Copy_Alpha 节点作为 B 端输入源
        b_stream_node = nuke.toNode("Copy_Alpha") or nuke.toNode("ColorMode_Switch") or nuke.toNode("Read_Plate")

        # 模块 2 固定在模块 1 右侧 (X: 680 ~ 1240, Y: -60 ~ 600)，与所有模块平齐且零重叠
        bd_x = 680
        bd_y = -60
        base_x = 760     # 模块 2 左侧 B 端主干列 X 坐标
        branch_x = 1000  # 模块 2 右侧 A 端 Alpha 精修列 X 坐标

        # =====================================================================
        # 3. 构建 A 端：MatAnyone 2 Alpha 读取 + 纯净柔边修饰链 (无生硬 Roto 节点)
        # =====================================================================
        # (1) 读取 MatAnyone 2 Alpha 序列
        ra = nuke.createNode("Read", inpanel=False)
        ra.setName("Read_MatAnyone2_Alpha")
        ra['file'].setValue(alpha_pat)
        ra['first'].setValue(a_first); ra['last'].setValue(a_last)
        ra['origfirst'].setValue(a_first); ra['origlast'].setValue(a_last)
        if 'raw' in ra.knobs():
            ra['raw'].setValue(True)
        ra['label'].setValue("MatAnyone 2 发丝Alpha")
        ra.setXYpos(branch_x, 0)

        # (2) Shuffle：将单通道灰度图 (Red) 转为标准 Alpha 通道
        shuf = nuke.createNode("Shuffle", inpanel=False)
        shuf.setName("Shuffle_AI_Alpha")
        shuf.setInput(0, ra)
        if 'alpha' in shuf.knobs():
            shuf['alpha'].setValue('red')
        shuf['label'].setValue("Red -> Alpha")
        shuf.setXYpos(branch_x, 95)

        # (3) Grade：提亮/压实发丝灰阶 (默认直通)
        grade_hair = nuke.createNode("Grade", inpanel=False)
        grade_hair.setName("Grade_AI_Hair")
        grade_hair.setInput(0, shuf)
        grade_hair['channels'].setValue("alpha")
        if 'white_clamp' in grade_hair.knobs():
            grade_hair['white_clamp'].setValue(True)
        grade_hair['label'].setValue("提亮发丝灰阶 (默认1.0)\n调高 white/gamma 增强发丝")
        grade_hair.setXYpos(branch_x, 170)

        # (4) FilterErode：缩边/扩边 (默认 size=0)
        erode_edge = nuke.createNode("FilterErode", inpanel=False)
        erode_edge.setName("FilterErode_AI_Edge")
        erode_edge.setInput(0, grade_hair)
        erode_edge['channels'].setValue("alpha")
        erode_edge['size'].setValue(0.0)
        if 'filter' in erode_edge.knobs():
            erode_edge['filter'].setValue("gaussian")
        erode_edge['label'].setValue("缩边/扩边 (默认0)\n正数内缩 / 负数外扩")
        erode_edge.setXYpos(branch_x, 245)

        # (5) Blur：边缘柔化 (默认 size=0)
        blur_edge = nuke.createNode("Blur", inpanel=False)
        blur_edge.setName("Blur_AI_Edge")
        blur_edge.setInput(0, erode_edge)
        blur_edge['channels'].setValue("alpha")
        blur_edge['size'].setValue(0.0)
        blur_edge['label'].setValue("边缘柔化 (默认0)")
        blur_edge.setXYpos(branch_x, 320)

        # =====================================================================
        # 4. 构建 B 端主干汇合点：Dot_AI_MainB -> Copy_MatAnyone2_Alpha -> Premult_MatAnyone2
        # =====================================================================
        dot_b = nuke.createNode("Dot", inpanel=False)
        dot_b.setName("Dot_AI_MainB")
        if b_stream_node:
            dot_b.setInput(0, b_stream_node)
        dot_b.setXYpos(base_x + 34, 224)  # 与左侧 Copy_Alpha (Y=220) 水平正交对齐

        cp = nuke.createNode("Copy", inpanel=False)
        cp.setName("Copy_MatAnyone2_Alpha")
        cp.setInput(0, dot_b)       # B 端：承接 Copy_Alpha (保留上方色彩模式判断)
        cp.setInput(1, blur_edge)   # A 端：连入精修后的 AI Alpha
        cp['from0'].setValue("rgba.alpha")
        cp['to0'].setValue("rgba.alpha")
        cp['label'].setValue("拷入 MatAnyone 2 Alpha")
        cp.setXYpos(base_x, 314)

        pm = nuke.createNode("Premult", inpanel=False)
        pm.setName("Premult_MatAnyone2")
        pm.setInput(0, cp)
        pm['label'].setValue("AI 发丝抠像最终预乘输出")
        pm.setXYpos(base_x, 405)

        # =====================================================================
        # 5. 创建 Backdrop_MatAnyone2 背板（排在模块 1 右侧、模块 3 左侧）
        # =====================================================================
        bd = nuke.createNode("BackdropNode", inpanel=False)
        bd.setName("Backdrop_MatAnyone2")
        bd['label'].setValue(
            "<center><b><font size='4' color='#58a6ff'>【AI 抠像与修补模块】MatAnyone 2 (CVPR 2026) 发丝级</font></b></center>\n"
            "• <b>B 端主干</b>：承接左侧 [Copy_Alpha]（保留素材色彩空间判断）\n"
            "• <b>A 端精修</b>：Grade (提亮发丝) -> FilterErode (正数缩边/负数扩边) -> Blur (柔化)，不调即原样直通"
        )
        bd['note_font_size'].setValue(13)
        bd['tile_color'].setValue(0x1b3b4dff)
        bd.setXYpos(bd_x, bd_y)
        bd['bdwidth'].setValue(560)
        bd['bdheight'].setValue(660)
        if 'z_order' in bd.knobs():
            bd['z_order'].setValue(-1)

        # =====================================================================
        # 6. 挂载 Write_Final_PNG + 联动右侧 UE 预合成 Merge_Comp_Over + 连接 Viewer1
        # =====================================================================
        write_final = nuke.toNode("Write_Final_PNG")
        if write_final:
            write_final.setInput(0, pm)
            write_final.setXYpos(base_x, 495)

        # 如果右侧已经构建了「UE 预合成主干区」(单层或多层)，自动将 Merge_Comp_Over 前景连到 Premult_MatAnyone2
        merge_comp = nuke.toNode("Merge_Comp_Over")
        if merge_comp:
            merge_comp.setInput(1, pm)
            old_exported = nuke.toNode("Read_Exported_PNG")
            if old_exported:
                nuke.delete(old_exported)

        # 如果存在 HorizonWriteNode，把 Viewer1 接在 HorizonWriteNode 后面；否则接在 Premult_MatAnyone2 后面
        pipe_helper = LiangLiangNukePipeline()
        h_write = nuke.toNode("HorizonWriteNode")
        if h_write:
            pipe_helper._connect_viewer1(h_write, xpos=int(h_write.xpos()), ypos=int(h_write.ypos() + 90))
        else:
            pipe_helper._connect_viewer1(pm, xpos=base_x, ypos=620)

        # 更新底部水印位置，确保在所有模块下方且不重叠
        pipe_helper._update_watermark_position()

        for n in nuke.allNodes():
            n.setSelected(False)

        comp_status = "已自动连入右侧 [Merge_Comp_Over] 前景端，且 [HorizonWriteNode] 已挂载 [Viewer1]" if merge_comp else "已将 [Write_Final_PNG] 与 [Viewer1] 挂载至 [Premult_MatAnyone2] 下"
        nuke.message(
            f"【✅ MatAnyone 2 发丝级抠像模块已就绪！】\n\n"
            f"• 模块位置：排布于「实拍预处理」右侧，四大模块从左到右整齐对齐\n"
            f"• 节点链路：Read -> Shuffle -> Grade -> FilterErode -> Blur -> Copy -> Premult\n"
            f"• 合成联动：{comp_status}"
        )
        return True

    def _run_with_live_console(self, window_title, cmd_list, isolated_env, work_cwd, out_dir, on_success_cb):
        """弹出实时进度终端窗口执行 AI 任务"""
        os.makedirs(out_dir, exist_ok=True)
        runner_bat = os.path.join(out_dir, "_run_ai_progress.bat")
        cmd_str = subprocess.list2cmdline(cmd_list)

        bat_content = (
            "@echo off\n"
            "chcp 65001 >nul\n"
            f"title {window_title}\n"
            f"cd /d \"{work_cwd}\"\n"
            f"{cmd_str}\n"
            "if errorlevel 1 (\n"
            "    echo.\n"
            "    echo [运行出现异常] 请查看上方报错信息，按任意键关闭窗口...\n"
            "    pause >nul\n"
            "    exit /b 1\n"
            ")\n"
            "exit /b 0\n"
        )
        with open(runner_bat, "w", encoding="utf-8") as f:
            f.write(bat_content)

        def _worker():
            creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
            proc = subprocess.Popen(
                ["cmd.exe", "/c", os.path.normpath(runner_bat)],
                env=isolated_env,
                cwd=work_cwd,
                creationflags=creation_flags
            )
            proc.wait()
            try:
                if os.path.exists(runner_bat):
                    os.remove(runner_bat)
            except Exception:
                pass

            if proc.returncode == 0:
                nuke.executeInMainThread(on_success_cb)
            else:
                nuke.executeInMainThread(
                    nuke.message,
                    args=(f"{window_title} 运行未完成或发生中断，请检查进度窗口提示。",)
                )

        th = threading.Thread(target=_worker, name="AI_Console_Thread")
        th.daemon = True
        th.start()

    # =========================================================================
    # 引擎 1: RVM 全自动快速抠像
    # =========================================================================
    def execute_rvm_auto(self):
        pipe = LiangLiangNukePipeline()
        ep, shot, workarea_dir, _ = pipe.get_current_pipeline_context()
        if not workarea_dir:
            return

        py_exe = self._get_python_exe()
        if not py_exe or not os.path.exists(py_exe):
            nuke.message("未检测到 [AI_VFX_Pipeline_Suite/python_embeded] 便携沙盒！")
            return

        input_folder = ""
        read_plate = nuke.toNode("Read_Plate")
        if read_plate and read_plate['file'].value():
            input_folder = os.path.dirname(read_plate['file'].value()).replace('\\', '/')
        if not input_folder or not os.path.exists(input_folder):
            chosen = nuke.getFilename(f"【选择 Shot {shot} 需抠像的实拍序列任一张】", "*.exr *.dpx *.png *.jpg")
            if not chosen:
                return
            input_folder = os.path.dirname(chosen).replace('\\', '/')

        out_dir = os.path.join(workarea_dir, "bg", "ai_rvm_matte").replace('\\', '/')
        cli_py = os.path.join(self.suite_root, "rvm/run_rvm_cli.py").replace('\\', '/')
        model_pth = os.path.join(self.suite_root, "rvm/models/rvm_resnet50.pth").replace('\\', '/')

        cmd = [
            os.path.normpath(py_exe),
            os.path.normpath(cli_py),
            "--input", os.path.normpath(input_folder),
            "--output", os.path.normpath(out_dir),
            "--model", os.path.normpath(model_pth),
            "--downsample", "0.5"
        ]

        isolated_env = self._get_clean_ai_env(py_exe)
        work_cwd = os.path.normpath(os.path.dirname(py_exe))

        def _on_finished():
            if os.name == "nt" and os.path.exists(out_dir):
                try:
                    subprocess.Popen(["explorer.exe", os.path.normpath(out_dir)])
                except Exception:
                    pass
            pattern, first_f, last_f = self._detect_sequence_pattern(out_dir, ext=".png")
            if not pattern:
                nuke.message(f"RVM 运算完毕，但在目标目录未找到序列：\n{out_dir}")
                return
            for n in nuke.allNodes():
                n.setSelected(False)
            old_n = nuke.toNode("Read_AI_RVM_Plate")
            if old_n:
                nuke.delete(old_n)
            r = nuke.createNode("Read", inpanel=False)
            r.setName("Read_AI_RVM_Plate")
            r['file'].setValue(pattern)
            r['first'].setValue(first_f); r['last'].setValue(last_f)
            r['origfirst'].setValue(first_f); r['origlast'].setValue(last_f)
            r.setXYpos(760, 0)
            pipe._connect_viewer1(r, xpos=760, ypos=110)
            nuke.message(f"【RVM 发丝级底板提取完成】\n\n已载入节点: [Read_AI_RVM_Plate]\n帧范围: {first_f} - {last_f}")

        self._run_with_live_console(
            window_title=f"Shot {shot} - RVM 全自动发丝抠像进度",
            cmd_list=cmd,
            isolated_env=isolated_env,
            work_cwd=work_cwd,
            out_dir=out_dir,
            on_success_cb=_on_finished
        )

    # =========================================================================
    # 引擎 2: MatAnyone 2 (CVPR 2026) 发丝级目标锁定视频抠像
    # =========================================================================
    def execute_sam2_tracking(self):
        pipe = LiangLiangNukePipeline()
        ep, shot, workarea_dir, _ = pipe.get_current_pipeline_context()
        if not workarea_dir:
            return

        py_exe = self._get_python_exe()
        if not py_exe or not os.path.exists(py_exe):
            nuke.message("未检测到 [AI_VFX_Pipeline_Suite/python_embeded] 便携沙盒！")
            return

        roto_dir = os.path.join(workarea_dir, "roto", "matanyone2").replace('\\', '/')
        os.makedirs(roto_dir, exist_ok=True)
        prefix_str = f"mat2_{shot}"

        read_plate = nuke.toNode("Read_Plate")
        default_first_f = int(nuke.root()['first_frame'].value())
        if read_plate and 'first' in read_plate.knobs():
            default_first_f = int(read_plate['first'].value())

        sel_nodes = [n for n in nuke.selectedNodes() if n.Class() in ("Roto", "RotoPaint", "Read", "Merge2", "ChannelMerge")]

        p = nuke.Panel(f"Shot {shot} - MatAnyone 2 (CVPR 2026) 发丝级目标抠像")
        p.setWidth(560)
        p.addEnumerationPulldown(
            "运行与首帧模式",
            "1_全自动只抠人(无需画Roto) "
            "2_只保留Roto圈内的人(在Holdout_Roto_KEEP画圈) "
            "3_从人身上挖掉Roto区域(在Garbage_Roto_REMOVE画圈) "
            "4_人加上Roto模块区域(在Holdout_Roto_KEEP画道具) "
            "5_完全按Roto区域抠像(在Holdout_Roto_KEEP画任意物体) "
            "6_直接导回已生成的序列(自动挂好Write与Viewer1)"
        )
        p.addSingleLineInput("起始运算帧(填帧号可从中途补救重算)", str(default_first_f))
        p.addSingleLineInput("首帧发丝精修迭代(Warmup)", "10")
        p.addSingleLineInput("边缘软化半径(Erode/Dilate)", "10")
        if not p.show():
            return

        choice = str(p.value("运行与首帧模式")).strip()
        start_f_str = str(p.value("起始运算帧(填帧号可从中途补救重算)")).strip()
        warmup_val = str(p.value("首帧发丝精修迭代(Warmup)")).strip() or "10"
        kernel_val = str(p.value("边缘软化半径(Erode/Dilate)")).strip() or "10"

        try:
            guide_frame = int(start_f_str)
        except Exception:
            guide_frame = default_first_f

        if choice.startswith("6_"):
            if os.name == "nt" and os.path.exists(roto_dir):
                try:
                    subprocess.Popen(["explorer.exe", os.path.normpath(roto_dir)])
                except Exception:
                    pass
            self._import_matanyone2_nodes(roto_dir, prefix_str)
            return

        mode_map = {
            "1_": "auto",
            "2_": "intersect",
            "3_": "subtract",
            "4_": "union",
            "5_": "replace"
        }
        mask_mode = mode_map.get(choice[:2], "auto")

        input_folder = ""
        if read_plate and read_plate['file'].value():
            input_folder = os.path.dirname(read_plate['file'].value()).replace('\\', '/')
        if not input_folder or not os.path.exists(input_folder):
            chosen = nuke.getFilename(f"【选择 Shot {shot} 实拍拆帧图片序列任一张】", "*.png *.jpg *.jpeg *.tif *.tiff")
            if not chosen:
                return
            input_folder = os.path.dirname(chosen).replace('\\', '/')

        first_mask_path = ""
        if mask_mode != "auto":
            if sel_nodes:
                roto_node = sel_nodes[0]
            elif mask_mode == "subtract":
                roto_node = nuke.toNode("Garbage_Roto_REMOVE") or nuke.toNode("Holdout_Roto_KEEP")
            else:
                roto_node = nuke.toNode("Holdout_Roto_KEEP")

            if not roto_node:
                nuke.message(
                    f"你选择了【{choice}】\n\n"
                    f"未找到 Holdout_Roto_KEEP 或 Garbage_Roto_REMOVE 节点，请先在画布中创建并选中一个 Roto 节点！"
                )
                return

            first_mask_path = os.path.join(roto_dir, f"_nuke_roto_frame_{guide_frame}.png").replace('\\', '/')

            reformat = nuke.createNode("Reformat", inpanel=False)
            reformat.setInput(0, roto_node)
            if read_plate and 'format' in read_plate.knobs():
                reformat['format'].setValue(read_plate['format'].value())

            w_temp = nuke.createNode("Write", inpanel=False)
            w_temp.setInput(0, reformat)
            w_temp['channels'].setValue("alpha")
            w_temp['file'].setValue(first_mask_path)
            w_temp['file_type'].setValue("png")
            nuke.execute(w_temp, guide_frame, guide_frame)
            nuke.delete(w_temp)
            nuke.delete(reformat)

        cli_py = os.path.join(self.suite_root, "matanyone2/run_matanyone2_cli.py").replace('\\', '/')
        cmd = [
            os.path.normpath(py_exe),
            os.path.normpath(cli_py),
            "--input", os.path.normpath(input_folder),
            "--output", os.path.normpath(roto_dir),
            "--mask_mode", mask_mode,
            "--prefix", prefix_str,
            "--warmup", warmup_val,
            "--erode_kernel", kernel_val,
            "--dilate_kernel", kernel_val,
            "--start_at", str(guide_frame)
        ]
        if first_mask_path and os.path.exists(first_mask_path):
            cmd.extend(["--mask", os.path.normpath(first_mask_path)])

        isolated_env = self._get_clean_ai_env(py_exe)
        work_cwd = os.path.normpath(os.path.dirname(cli_py))

        def _on_finished():
            self._import_matanyone2_nodes(roto_dir, prefix_str)

        self._run_with_live_console(
            window_title=f"Shot {shot} - MatAnyone 2 实时抠像进度 ({choice})",
            cmd_list=cmd,
            isolated_env=isolated_env,
            work_cwd=work_cwd,
            out_dir=roto_dir,
            on_success_cb=_on_finished
        )


# =========================================================================
# 菜单统一接口定义
# =========================================================================
def show_prep_menu():
    pipe = LiangLiangNukePipeline()
    pipe.build_plate_prep_network()

def show_autocomp_menu():
    pipe = LiangLiangNukePipeline()
    pipe.build_unified_autocomp_network()

def show_ai_rvm_menu():
    dispatcher = AIMattingDispatcher()
    dispatcher.execute_rvm_auto()

def show_ai_sam2_menu():
    dispatcher = AIMattingDispatcher()
    dispatcher.execute_sam2_tracking()