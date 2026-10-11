# -*- coding: utf-8 -*-
"""
LiangLiang Nuke Pipeline Workflow (工业级极简正交布局版)
-------------------------------------------------------------------------
- 模块 1: 实拍预处理与输出UE底板 (直角正交连线 + Raw Data 联动 + default (sRGB))
- 模块 2: UE渲染分层（单层）自动预合成与ID拆层:
  * 背景主干: Read_BG -> TimeOffset(1000) -> Grade -> ColorCorrect -> Merge(Over) -> HorizonWriteNode
  * 独立拆层: 右侧金黄框展示 "分层 AOV 与 Cryptomatte (供合成提取)"，Material 提取 Depth/Normal/Pos 及 Actor/SHD Cryptomatte
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

    def _set_safe_write_colorspace(self, write_node, preferred_spaces):
        """严格设置 Write 节点的色彩空间"""
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
                    if pref.lower() == avail.lower() or pref.lower() in avail.lower():
                        cs_knob.setValue(avail)
                        return
        except:
            pass

        try:
            cs_knob.setValue(preferred_spaces[0])
        except:
            pass

    def _get_valid_colorspace_value(self, knob, preferred_candidates):
        """严格从 Nuke 节点当前支持的色彩列表里抓取有效参数名"""
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
    # 模块 1：实拍预处理与输出UE底板 (绝对直角正交连线布局)
    # =========================================================================
    def build_plate_prep_network(self):
        ep, shot, workarea_dir, shot_root_dir = self.get_current_pipeline_context()
        if not workarea_dir:
            return

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
            try:
                os.makedirs(target_bg_dir)
            except:
                pass

        nuke.root()['first_frame'].setValue(first_f)
        nuke.root()['last_frame'].setValue(last_f)
        nuke.root()['fps'].setValue(25.0)

        for n in nuke.allNodes():
            n.setSelected(False)

        # 1. 读入实拍素材 (顶层 X: 0, Y: 0)
        read_plate = nuke.createNode("Read", inpanel=False)
        read_plate.setName(f"Read_Plate_{shot}")
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
        col_convert.setName(f"Colorspace_LogC_to_Linear_{shot}")
        valid_in = self._get_valid_colorspace_value(col_convert['colorspace_in'], ["AlexaV3LogC", "LogC", "linear"])
        valid_out = self._get_valid_colorspace_value(col_convert['colorspace_out'], ["linear", "scene_linear", "ACEScg", "Linear"])
        if valid_in: col_convert['colorspace_in'].setValue(valid_in)
        if valid_out: col_convert['colorspace_out'].setValue(valid_out)
        col_convert.setXYpos(120, 50)

        color_switch = nuke.createNode("Switch", inpanel=False)
        color_switch.setName(f"ColorMode_Switch_{shot}")
        color_switch.setInput(0, read_plate)   # 垂直直通
        color_switch.setInput(1, col_convert)  # 灰片分支
        mode_knob = nuke.Enumeration_Knob("color_mode", "素材色彩模式", [
            "标准普通素材 (sRGB / 直通)", 
            "电影机灰片 (LogC -> Linear 转正)"
        ])
        mode_knob.setValue(1)
        color_switch.addKnob(mode_knob)
        color_switch['which'].setExpression("color_mode")
        color_switch.setXYpos(0, 110)

        if 'raw' in read_plate.knobs():
            read_plate['raw'].setExpression(f"{color_switch.name()}.which == 1")

        # 3. 遮罩支路 (纵向排列，完全垂直对齐)
        holdout_roto = nuke.createNode("Roto", inpanel=False)
        holdout_roto.setInput(0, read_plate)
        holdout_roto.setName(f"Holdout_Roto_KEEP_{shot}")
        holdout_roto['label'].setValue("【圈要的: 补实心】")
        holdout_roto.setXYpos(260, 0)

        blur_inm = nuke.createNode("Blur", inpanel=False)
        blur_inm.setInput(0, holdout_roto)
        blur_inm.setName(f"Blur_InM_{shot}")
        blur_inm['channels'].setValue("alpha")
        blur_inm['size'].setValue(4.0)
        blur_inm.setXYpos(260, 80)

        garbage_roto = nuke.createNode("Roto", inpanel=False)
        garbage_roto.setInput(0, read_plate)
        garbage_roto.setName(f"Garbage_Roto_REMOVE_{shot}")
        garbage_roto['label'].setValue("【圈不要的: 切杂物】")
        garbage_roto.setXYpos(420, 0)

        blur_outm = nuke.createNode("Blur", inpanel=False)
        blur_outm.setInput(0, garbage_roto)
        blur_outm.setName(f"Blur_OutM_{shot}")
        blur_outm['channels'].setValue("alpha")
        blur_outm['size'].setValue(6.0)
        blur_outm.setXYpos(420, 80)

        # 4. Keylight (固定 Y = 200)
        kl = nuke.createNode("OFXuk.co.thefoundry.keylight.keylight_v201", inpanel=False)
        kl.setName(f"Keyer_Alpha_{shot}")
        kl.setInput(0, color_switch)  # Source
        kl.setInput(1, blur_inm)      # InM 垂直向下直连
        kl.setInput(2, blur_outm)     # OutM 正交连入
        kl.setXYpos(260, 200)

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

        # 5. Copy -> Premult -> Write (与 Keylight 保持水平 T 字对齐)
        copy_alpha = nuke.createNode("Copy", inpanel=False)
        copy_alpha.setName(f"Copy_Alpha_{shot}")
        copy_alpha.setInput(0, color_switch)  # 垂直自上方 0, 110 直下
        copy_alpha.setInput(1, kl)            # 水平自右侧 260, 200 直进
        copy_alpha['from0'].setValue("rgba.alpha")
        copy_alpha['to0'].setValue("rgba.alpha")
        copy_alpha.setXYpos(0, 200)

        premult = nuke.createNode("Premult", inpanel=False)
        premult.setName(f"Premult_{shot}")
        premult.setInput(0, copy_alpha)
        premult.setXYpos(0, 300)  # 垂直落位于 Y = 300，与模块二 Merge 保持水平对齐

        png_out_pattern = f"{target_bg_dir}/bg_{shot}_####.png"
        write_ue = nuke.createNode("Write", inpanel=False)
        write_ue.setInput(0, premult)
        write_ue.setName(f"Write_Final_PNG_{shot}")
        write_ue['file'].setValue(png_out_pattern)
        write_ue['channels'].setValue("rgba")
        write_ue['file_type'].setValue("png")
        write_ue['datatype'].setValue("8 bit")
        self._set_safe_write_colorspace(write_ue, ["default (sRGB)", "Output - sRGB", "sRGB", "default"])
        write_ue.setXYpos(0, 400)

        # 墨绿框规整包裹
        bd = nuke.createNode("BackdropNode", inpanel=False)
        bd['label'].setValue(f"<center><b><font size='4'>Shot {shot} 实拍预处理与输出UE底板</font></b></center>")
        bd['note_font_size'].setValue(14)
        bd['tile_color'].setValue(0x1a402500)
        bd.setXYpos(-60, -60)
        bd['bdwidth'].setValue(580)
        bd['bdheight'].setValue(540)

        nuke.scriptSave()

        viewer = nuke.activeViewer()
        if viewer:
            viewer.node().setInput(0, kl)

        nuke.show(kl)
        nuke.message("【实拍预处理与输出UE底板已生成】\n\n👉 连线已彻底规整:\n• Copy 与 Keylight 在 Y=200 保持水平正交对接；\n• 输出节点与 Premult 保持垂直对齐！")

    # =========================================================================
    # 模块 2 辅助函数：创建带缩略图的 AOV 提取节点
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

    # =========================================================================
    # 模块 2：UE 渲染分层（单层）自动预合成与 ID 拆层
    # =========================================================================
    def build_render_autocomp_network(self):
        ep, shot, workarea_dir, shot_root_dir = self.get_current_pipeline_context()
        if not workarea_dir:
            return

        default_render_dir = ""
        if shot_root_dir:
            cand_render = os.path.normpath(os.path.join(shot_root_dir, "ue", "publish", "v001", "render")).replace('\\', '/')
            if os.path.exists(cand_render):
                default_render_dir = cand_render

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

        all_files = os.listdir(default_render_dir)
        exr_files = [f for f in all_files if f.lower().endswith(".exr")]
        if not exr_files:
            nuke.message("render 目录下未找到任何 EXR 序列文件！\n" + default_render_dir)
            return

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

        if not sequences:
            nuke.message("未解析到符合命名规则的 EXR 序列文件！\n" + default_render_dir)
            return

        for n in nuke.allNodes():
            n.setSelected(False)

        bg_seq = None
        actor_seq = None
        material_seq = None

        for prefix, data in sequences.items():
            p_lower = prefix.lower()
            if "actor" in p_lower:
                actor_seq = (prefix, data)
            elif any(k in p_lower for k in ["material", "shd"]):
                material_seq = (prefix, data)
            else:
                if not bg_seq:
                    bg_seq = (prefix, data)

        # -------------------------------------------------------------
        # 1. 中区背景主合成干线 (垂直自 X: 800, Y: 0 直下)
        # -------------------------------------------------------------
        comp_x = 800
        comp_tail = None

        if bg_seq:
            p, d = bg_seq
            frames = sorted(d["frames"])
            seq_path = f"{default_render_dir}/{p}{d['sep']}%0{d['pad']}d.exr"

            r_bg = nuke.createNode("Read", inpanel=False)
            r_bg.setName(f"Read_UE_BG_{shot}")
            r_bg['file'].setValue(seq_path)
            r_bg['first'].setValue(frames[0]); r_bg['last'].setValue(frames[-1])
            r_bg['origfirst'].setValue(frames[0]); r_bg['origlast'].setValue(frames[-1])
            r_bg.setXYpos(comp_x, 0)

            t_offset = nuke.createNode("TimeOffset", inpanel=False)
            t_offset.setInput(0, r_bg)
            t_offset.setName(f"TimeOffset_{shot}")
            t_offset['time_offset'].setValue(1000)
            t_offset.setXYpos(comp_x, 75)

            grade_node = nuke.createNode("Grade", inpanel=False)
            grade_node.setInput(0, t_offset)
            grade_node.setName(f"Grade_BG_{shot}")
            grade_node.setXYpos(comp_x, 150)

            cc_node = nuke.createNode("ColorCorrect", inpanel=False)
            cc_node.setInput(0, grade_node)
            cc_node.setName(f"ColorCorrect_BG_{shot}")
            cc_node.setXYpos(comp_x, 225)

            comp_tail = cc_node

        # -------------------------------------------------------------
        # 2. 与实拍底板水平正交连接 (从 Premult Y=300 平直到达 Merge Y=300)
        # -------------------------------------------------------------
        fg_pipe = None
        for n in nuke.allNodes("Premult"):
            if f"Premult_{shot}" in n.name():
                fg_pipe = n
                break

        if not fg_pipe:
            bg_png_dir = os.path.join(workarea_dir, "bg").replace('\\', '/')
            png_pattern = f"{bg_png_dir}/bg_{shot}_%04d.png"
            read_fg = nuke.createNode("Read", inpanel=False)
            read_fg.setName(f"Read_Exported_PNG_{shot}")
            read_fg['file'].setValue(png_pattern)
            read_fg['first'].setValue(int(nuke.root()['first_frame'].value()))
            read_fg['last'].setValue(int(nuke.root()['last_frame'].value()))
            read_fg['origfirst'].setValue(int(nuke.root()['first_frame'].value()))
            read_fg['origlast'].setValue(int(nuke.root()['last_frame'].value()))
            read_fg.setXYpos(640, 300)
            fg_pipe = read_fg

        final_merge = None
        if comp_tail and fg_pipe:
            final_merge = nuke.createNode("Merge2", inpanel=False)
            final_merge['operation'].setValue("over")
            final_merge.setInput(0, comp_tail)  # B: UE 背景 (垂直从上方来)
            final_merge.setInput(1, fg_pipe)    # A: 实拍底板 (水平从左侧平直接入)
            final_merge.setName(f"Merge_Comp_Over_{shot}")
            final_merge.setXYpos(comp_x, 300)
        else:
            final_merge = comp_tail if comp_tail else fg_pipe

        # 3. 输出审阅节点 HorizonWriteNode
        if final_merge:
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

            h_write.setXYpos(comp_x, 400)

        bd_mid = nuke.createNode("BackdropNode", inpanel=False)
        bd_mid['label'].setValue(f"<center><b><font size='4'>Shot {shot} UE 预合成主干区</font></b><br>UE 背景调色与实拍叠加</center>")
        bd_mid['note_font_size'].setValue(14)
        bd_mid['tile_color'].setValue(0x1b2d4400)
        bd_mid.setXYpos(680, -60)
        bd_mid['bdwidth'].setValue(380)
        bd_mid['bdheight'].setValue(540)

        # -------------------------------------------------------------
        # 4. 右区 AOV 与 Cryptomatte 提取区 (精确按图片设定提示)
        # -------------------------------------------------------------
        id_start_x = 1180

        # Actor ID
        if actor_seq:
            p, d = actor_seq
            frames = sorted(d["frames"])
            seq_path = f"{default_render_dir}/{p}{d['sep']}%0{d['pad']}d.exr"

            r_actor = nuke.createNode("Read", inpanel=False)
            r_actor.setName(f"Read_Actor_ID_{shot}")
            r_actor['file'].setValue(seq_path)
            r_actor['first'].setValue(frames[0]); r_actor['last'].setValue(frames[-1])
            r_actor['origfirst'].setValue(frames[0]); r_actor['origlast'].setValue(frames[-1])
            r_actor.setXYpos(id_start_x, 0)

            self._create_cryptomatte_node(r_actor, f"Cryptomatte_Actor_{shot}", id_start_x, 160)

        # Material ID
        mat_x = 1580
        if material_seq:
            p, d = material_seq
            frames = sorted(d["frames"])
            seq_path = f"{default_render_dir}/{p}{d['sep']}%0{d['pad']}d.exr"

            r_mat = nuke.createNode("Read", inpanel=False)
            r_mat.setName(f"Read_Material_ID_{shot}")
            r_mat['file'].setValue(seq_path)
            r_mat['first'].setValue(frames[0]); r_mat['last'].setValue(frames[-1])
            r_mat['origfirst'].setValue(frames[0]); r_mat['origlast'].setValue(frames[-1])
            r_mat.setXYpos(mat_x, 0)

            depth_layer = self._find_matching_layer(r_mat, "depth")
            normal_layer = self._find_matching_layer(r_mat, "normal")
            pos_layer = self._find_matching_layer(r_mat, "pos")

            self._create_single_aov_shuffle(
                r_mat, depth_layer, "FinalImageMovieRenderQueue_WorldDepth_Shuffel", mat_x - 180, 160
            )
            self._create_single_aov_shuffle(
                r_mat, normal_layer, "FinalImageMovieRenderQueue_WorldNormal_Shuffel", mat_x - 60, 160
            )
            self._create_single_aov_shuffle(
                r_mat, pos_layer, "FinalImageMovieRenderQueue_WorldPos_Shuffel", mat_x + 60, 160
            )
            self._create_cryptomatte_node(
                r_mat, f"Cryptomatte_Material_{shot}", mat_x + 180, 160
            )

        # 精确按图片设定提示: "分层 AOV 与 Cryptomatte (供合成提取)"
        bd_right = nuke.createNode("BackdropNode", inpanel=False)
        bd_right['label'].setValue("<center><b><font size='5' color='#ffcc00'>分层 AOV 与 Cryptomatte (供合成提取)</font></b><br>ID / Material (WorldDepth, WorldPos, WorldNormal)</center>")
        bd_right['note_font_size'].setValue(14)
        bd_right['tile_color'].setValue(0x55440000)
        bd_right.setXYpos(1120, -60)
        bd_right['bdwidth'].setValue(740)
        bd_right['bdheight'].setValue(320)

        nuke.scriptSave()

        viewer = nuke.activeViewer()
        if viewer and final_merge:
            viewer.node().setInput(0, final_merge)

        nuke.message(f"【预合成组装完成】\n\n👉 优化点:\n1. 实拍底板与 UE 背景保持直角正交连线；\n2. 右侧 ID 拆层区标签已更新为「分层 AOV 与 Cryptomatte (供合成提取)」！")

# =========================================================================
# 菜单统一接口 (仅保留核心的两项功能)
# =========================================================================
def show_prep_menu():
    pipe = LiangLiangNukePipeline()
    pipe.build_plate_prep_network()

def show_autocomp_menu():
    pipe = LiangLiangNukePipeline()
    pipe.build_render_autocomp_network()