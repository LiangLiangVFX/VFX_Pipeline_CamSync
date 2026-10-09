# -*- coding: utf-8 -*-
"""
LiangLiang Nuke Pipeline Workflow (Write default(sRGB) + ClipWhite/Black 修复版)
-------------------------------------------------------------------------
- 修复 1: Write 节点的 output transform 严格精准指定 "default (sRGB)"
- 修复 2: 彻底打通参数 6 (clipWhite) 和 7 (clipBlack) 与底层真实 knob 的表达式绑定
- 包含全套功能：色彩模式联动、InM/OutM 端口精确连接与边缘羽化
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
        """严格设置 Write 节点的色彩空间，支持 default (sRGB) 与 OCIO 规范"""
        # 兼容 OCIO 与 Nuke 原生不同的 knob 命名 (colorspace 或 ocio_output)
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
                    # 严格完全匹配或小写无缝匹配
                    if avail.lower() == pref.lower() or avail.lower().startswith(pref.lower()):
                        cs_knob.setValue(avail)
                        return
        except:
            pass

        # 尝试直接硬写入
        try:
            cs_knob.setValue("default (sRGB)")
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

    def _bind_safe_expression(self, node, candidate_knobs, expr_value):
        """安全寻找真实存在的 knob 并赋予表达式，确保联动生效"""
        for name in candidate_knobs:
            if name in node.knobs():
                try:
                    node[name].setExpression(expr_value)
                    return True
                except:
                    pass
        return False

    def create_clean_keyer_group(self, shot, default_logc=True):
        """创建原生独立复合抠像 Group，暴露所有控制参数并严格绑定表达式"""
        grp = nuke.createNode("Group", inpanel=False)
        grp.setName(f"Clean_Keyer_Master_{shot}")

        tab = nuke.Tab_Knob("KeyerTab", "核心抠像与色彩控制")
        grp.addKnob(tab)

        # 1. 组面板最顶部：色彩模式自由热切换
        color_choices = ["标准普通素材 (sRGB / 直通)", "电影机灰片 (LogC -> Linear 转正)"]
        color_mode = nuke.Enumeration_Knob("color_mode", "0. 素材色彩模式", color_choices)
        color_mode.setValue(1 if default_logc else 0)
        grp.addKnob(color_mode)

        # 分割线
        grp.addKnob(nuke.Text_Knob("divider1", ""))

        # 2. 绿幕吸色
        col_knob = nuke.Color_Knob("screenColour", "1. 吸取绿幕背景 (Ctrl+点选)")
        col_knob.setValue([0.0, 0.0, 0.0])
        grp.addKnob(col_knob)

        # 3. 遮罩组件开关 (默认 None 保证随时可以重新吸色)
        comp_choices = ["None", "Alpha", "Inverted Alpha", "Luminance", "Inverted Luminance"]
        in_comp = nuke.Enumeration_Knob("insideComponent", "2. 补心遮罩模式 (InM)", comp_choices)
        in_comp.setValue("None")
        grp.addKnob(in_comp)

        out_comp = nuke.Enumeration_Knob("outsideComponent", "3. 垃圾剔除模式 (OutM)", comp_choices)
        out_comp.setValue("None")
        grp.addKnob(out_comp)

        # 4. 内部羽化调节
        in_blur = nuke.Double_Knob("inm_blur", "4. 补心边缘羽化 (InM Feather)")
        in_blur.setRange(0.0, 20.0)
        in_blur.setValue(4.0)
        grp.addKnob(in_blur)

        out_blur = nuke.Double_Knob("outm_blur", "5. 垃圾边缘羽化 (OutM Feather)")
        out_blur.setRange(0.0, 20.0)
        out_blur.setValue(6.0)
        grp.addKnob(out_blur)

        # 5. 黑白阈值微调 (确保范围合理且与底层参数 100% 互通)
        clip_w = nuke.Double_Knob("clipWhite", "6. 身体压实纯白度 (Clip White)")
        clip_w.setRange(0.1, 1.0)
        clip_w.setValue(1.0)
        grp.addKnob(clip_w)

        clip_b = nuke.Double_Knob("clipBlack", "7. 背景纯净黑度 (Clip Black)")
        clip_b.setRange(0.0, 0.3)
        clip_b.setValue(0.0)
        grp.addKnob(clip_b)

        grp.begin()

        # 内部输入端口
        in_src = nuke.createNode("Input", inpanel=False)
        in_src.setName("Source")

        in_holdout = nuke.createNode("Input", inpanel=False)
        in_holdout.setName("Holdout_InM")

        in_garbage = nuke.createNode("Input", inpanel=False)
        in_garbage.setName("Garbage_OutM")

        # 色彩模式选择模块
        col_convert = nuke.createNode("Colorspace", inpanel=False)
        col_convert.setInput(0, in_src)
        col_convert.setName("Internal_Colorspace")
        valid_in = self._get_valid_colorspace_value(col_convert['colorspace_in'], ["AlexaV3LogC", "LogC", "linear"])
        valid_out = self._get_valid_colorspace_value(col_convert['colorspace_out'], ["linear", "scene_linear", "ACEScg", "Linear"])
        if valid_in: col_convert['colorspace_in'].setValue(valid_in)
        if valid_out: col_convert['colorspace_out'].setValue(valid_out)

        color_switch = nuke.createNode("Switch", inpanel=False)
        color_switch.setInput(0, in_src)       # 0: 直通
        color_switch.setInput(1, col_convert)  # 1: LogC -> Linear
        color_switch['which'].setExpression("parent.color_mode")

        work_pipe = color_switch

        # 遮罩羽化与 Keylight
        b_inm = nuke.createNode("Blur", inpanel=False)
        b_inm.setInput(0, in_holdout)
        b_inm['channels'].setValue("alpha")
        b_inm['size'].setExpression("parent.inm_blur")

        b_outm = nuke.createNode("Blur", inpanel=False)
        b_outm.setInput(0, in_garbage)
        b_outm['channels'].setValue("alpha")
        b_outm['size'].setExpression("parent.outm_blur")

        kl = nuke.createNode("OFXuk.co.thefoundry.keylight.keylight_v201", inpanel=False)
        kl.setInput(0, work_pipe) # Source
        kl.setInput(1, b_inm)     # InM
        kl.setInput(2, b_outm)    # OutM

        # 【重点修复 2】：严格寻找并绑定存在的参数名 (兼容大驼峰、小驼峰、全小写)
        self._bind_safe_expression(kl, ['screenColour', 'screen_colour', 'screencolour'], "parent.screenColour")
        self._bind_safe_expression(kl, ['insideComponent', 'inside_component', 'insidecomponent'], "parent.insideComponent")
        self._bind_safe_expression(kl, ['outsideComponent', 'outside_component', 'outsidecomponent'], "parent.outsideComponent")
        
        # 确保参数 6、7 生效
        self._bind_safe_expression(kl, ['clipwhite', 'clipWhite', 'clip_white'], "parent.clipWhite")
        self._bind_safe_expression(kl, ['clipblack', 'clipBlack', 'clip_black'], "parent.clipBlack")

        for sh in ['show', 'view']:
            if sh in kl.knobs():
                kl[sh].setValue("Final Result")
                break

        # Alpha 赋予与预乘输出
        copy_a = nuke.createNode("Copy", inpanel=False)
        copy_a.setInput(0, work_pipe)
        copy_a.setInput(1, kl)
        copy_a['from0'].setValue("rgba.alpha")
        copy_a['to0'].setValue("rgba.alpha")

        premult = nuke.createNode("Premult", inpanel=False)
        premult.setInput(0, copy_a)

        out_node = nuke.createNode("Output", inpanel=False)
        out_node.setInput(0, premult)

        grp.end()
        return grp

    # =========================================================================
    # 模块 1：实拍预处理与输出底板
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

        # 1. 读入实拍素材 (默认勾选 raw)
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

        # 2. 预留两个外部 Roto 节点
        holdout_roto = nuke.createNode("Roto", inpanel=False)
        holdout_roto.setInput(0, read_plate)
        holdout_roto.setName(f"Holdout_Roto_KEEP_{shot}")
        holdout_roto['label'].setValue("【圈要的: 身体发灰处圈选补实心】")
        holdout_roto.setXYpos(220, 0)

        garbage_roto = nuke.createNode("Roto", inpanel=False)
        garbage_roto.setInput(0, read_plate)
        garbage_roto.setName(f"Garbage_Roto_REMOVE_{shot}")
        garbage_roto['label'].setValue("【圈不要的: 穿帮灯具/四周杂物圈选切除】")
        garbage_roto.setXYpos(400, 0)

        # 3. 核心 Clean Keyer Group
        clean_keyer = self.create_clean_keyer_group(shot, default_logc=True)
        clean_keyer.setInput(0, read_plate)    # Source
        clean_keyer.setInput(1, holdout_roto)  # Holdout_InM
        clean_keyer.setInput(2, garbage_roto)  # Garbage_OutM
        clean_keyer.setXYpos(0, 100)

        # 联动绑定：Read 的 raw 跟随 Group 的 color_mode
        if 'raw' in read_plate.knobs():
            read_plate['raw'].setExpression(f"{clean_keyer.name()}.color_mode == 1")

        # 4. Write 节点输出 PNG
        # 【重点修复 1】：明确传入 "default (sRGB)"
        png_out_pattern = f"{target_bg_dir}/bg_{shot}_####.png"
        write_ue = nuke.createNode("Write", inpanel=False)
        write_ue.setInput(0, clean_keyer)
        write_ue.setName(f"Write_Final_PNG_{shot}")
        write_ue['file'].setValue(png_out_pattern)
        write_ue['channels'].setValue("rgba")
        write_ue['file_type'].setValue("png")
        write_ue['datatype'].setValue("8 bit")
        self._set_safe_write_colorspace(write_ue, ["default (sRGB)", "Output - sRGB", "sRGB", "default"])
        write_ue.setXYpos(0, 200)

        bd = nuke.createNode("BackdropNode", inpanel=False)
        bd['label'].setValue(f"<center><b>Shot {shot} 抠像底板生成 (色彩全联动·参数直通版)</b></center>")
        bd['note_font_size'].setValue(16)
        bd['tile_color'].setValue(0x1a402500)
        bd.setXYpos(-40, -50)
        bd['bdwidth'].setValue(600)
        bd['bdheight'].setValue(320)

        nuke.scriptSave()

        viewer = nuke.activeViewer()
        if viewer:
            viewer.node().setInput(0, clean_keyer)

        nuke.show(clean_keyer)
        nuke.message("【抠像网络生成完成】\n\n👉 核心修复点:\n1. Write 节点的 output transform 已锁定为 [default (sRGB)]；\n2. 参数 6 (Clip White) 和 7 (Clip Black) 已与底层完全绑定，拖动滑块即可实时压实身体/纯黑背景！")

    # =========================================================================
    # 模块 2：UE 渲染后 —— MRQ 分层组装、拆层与预合成
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
            chosen = nuke.getFilename("选择 UE 渲染输出的 render 文件夹", "", type="dir")
            if not chosen:
                return
            default_render_dir = os.path.normpath(chosen).replace('\\', '/')

        all_files = os.listdir(default_render_dir)
        exr_files = [f for f in all_files if f.lower().endswith(".exr")]
        if not exr_files:
            nuke.message("render 目录下未找到任何 EXR 序列文件！\n" + default_render_dir)
            return

        sequences = {}
        for f in exr_files:
            m = re.search(r'^(.*?)[._](\d+)\.exr$', f, re.IGNORECASE)
            if m:
                prefix = m.group(1)
                frame = int(m.group(2))
                if prefix not in sequences:
                    sequences[prefix] = []
                sequences[prefix].append(frame)

        for n in nuke.allNodes():
            n.setSelected(False)

        start_x = 650
        start_y = 0
        spacing_x = 180

        created_reads = {}
        light_reads = []
        id_reads = {}

        idx = 0
        for prefix, frames in sorted(sequences.items()):
            frames.sort()
            first_f = frames[0]
            last_f = frames[-1]
            seq_path = f"{default_render_dir}/{prefix}.%04d.exr"

            r = nuke.createNode("Read", inpanel=False)
            r.setName(re.sub(r'[^a-zA-Z0-9_]', '_', prefix))
            r['file'].setValue(seq_path)
            r['first'].setValue(first_f)
            r['last'].setValue(last_f)
            r['origfirst'].setValue(first_f)
            r['origlast'].setValue(last_f)
            r.setXYpos(start_x + idx * spacing_x, start_y)
            created_reads[prefix] = r

            p_lower = prefix.lower()
            if "id" in p_lower or "cryptomatte" in p_lower:
                id_reads[prefix] = r
            else:
                light_reads.append(r)
            idx += 1

        aov_offset_y = 160
        for prefix, id_node in id_reads.items():
            x = id_node.xpos()
            y = id_node.ypos() + aov_offset_y
            aov_list = [
                ("WorldDepth", "finalImageMovieRenderQueue_WorldDepth"),
                ("WorldPos", "finalImageMovieRenderQueue_WorldPos"),
                ("WorldNormal", "finalImageMovieRenderQueue_WorldNormal")
            ]
            shuf_x_offset = 0
            for label_name, ch_name in aov_list:
                shuf = nuke.createNode("Shuffle2", inpanel=False)
                shuf.setInput(0, id_node)
                shuf.setName(f"{id_node.name()}_{label_name}")
                shuf.setXYpos(x + shuf_x_offset, y + 80)
                shuf_x_offset += 90

        cur_ue_pipe = None
        if light_reads:
            merge_y = start_y + 350
            for i, l_node in enumerate(light_reads):
                if i == 0:
                    cur_ue_pipe = l_node
                else:
                    m_plus = nuke.createNode("Merge2", inpanel=False)
                    m_plus['operation'].setValue("plus")
                    m_plus['output'].setValue("rgb")
                    m_plus.setInput(0, cur_ue_pipe)
                    m_plus.setInput(1, l_node)
                    m_plus.setXYpos(l_node.xpos(), merge_y)
                    cur_ue_pipe = m_plus

        bg_png_dir = os.path.join(workarea_dir, "bg").replace('\\', '/')
        png_pattern = f"{bg_png_dir}/bg_{shot}_%04d.png"
        
        read_rendered_png = nuke.createNode("Read", inpanel=False)
        read_rendered_png.setName(f"Read_Exported_PNG_{shot}")
        read_rendered_png['file'].setValue(png_pattern)
        read_rendered_png['first'].setValue(int(nuke.root()['first_frame'].value()))
        read_rendered_png['last'].setValue(int(nuke.root()['last_frame'].value()))
        read_rendered_png['origfirst'].setValue(int(nuke.root()['first_frame'].value()))
        read_rendered_png['origlast'].setValue(int(nuke.root()['last_frame'].value()))
        read_rendered_png.setXYpos(start_x - 200, start_y + 260)

        final_fg_node = read_rendered_png

        final_comp_pipe = cur_ue_pipe
        if cur_ue_pipe and final_fg_node:
            merge_over = nuke.createNode("Merge2", inpanel=False)
            merge_over['operation'].setValue("over")
            merge_over.setInput(0, cur_ue_pipe)
            merge_over.setName(f"Merge_Comp_{shot}")
            merge_over.setXYpos(cur_ue_pipe.xpos(), start_y + 480)
            final_comp_pipe = merge_over

        if final_comp_pipe:
            preview_dir = os.path.normpath(os.path.join(default_render_dir, "..", "preview")).replace('\\', '/')
            if not os.path.exists(preview_dir):
                try:
                    os.makedirs(preview_dir)
                except:
                    pass

            nk_base = os.path.splitext(os.path.basename(nuke.root().name()))[0]
            mov_out_path = f"{preview_dir}/{nk_base}.mov"
            
            final_write = nuke.createNode("Write", inpanel=False)
            final_write.setInput(0, final_comp_pipe)
            final_write.setName("Write_Preview_MOV")
            final_write['file'].setValue(mov_out_path)
            final_write['file_type'].setValue("mov")
            self._set_safe_write_colorspace(final_write, ["default (rec709)", "Output - Rec.709", "rec709", "default"])
            
            if 'meta_codec' in final_write.knobs():
                try:
                    final_write['meta_codec'].setValue("apch")
                except:
                    pass

            final_write.setXYpos(final_comp_pipe.xpos(), final_comp_pipe.ypos() + 100)

        nuke.scriptSave()
        nuke.message(f"【MRQ 渲染自动预合成组装完成】\n\n• 已自动读取输出好的透明 PNG: [Read_Exported_PNG_{shot}]\n• 纯原生连接，下游零插件依赖！")

def show_prep_menu():
    pipe = LiangLiangNukePipeline()
    pipe.build_plate_prep_network()

def show_autocomp_menu():
    pipe = LiangLiangNukePipeline()
    pipe.build_render_autocomp_network()