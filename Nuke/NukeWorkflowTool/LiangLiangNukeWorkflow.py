# -*- coding: utf-8 -*-
"""
LiangLiang Nuke Pipeline Workflow (平铺原生直连·Raw Data 自动联动版)
-------------------------------------------------------------------------
- 1. 彻底取消 Group 封装：全部节点平铺在主节点图，Keylight 参数零延迟实时生效
- 2. ColorMode_Switch 提供下拉菜单，与 Read 节点的 raw data 原生双向联动：
     * 默认预设：[电影机灰片 (LogC -> Linear)]，Read 的 raw data 自动打勾
     * 切换为：[标准普通素材 (sRGB / 直通)] 时，Read 的 raw data 自动取消打勾
- 3. Keylight 物理端口精准接入：
     * Input 0: ColorMode_Switch (Source)
     * Input 1: Blur_InM (Holdout 圈要的补心)
     * Input 2: Blur_OutM (Garbage 圈不要的切除)
     * insideComponent 与 outsideComponent 默认保持为 None，吸色无阻碍
- 4. Write 节点的 output transform 严格精准指定为 "default (sRGB)"
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

    # =========================================================================
    # 模块 1：实拍预处理与输出底板 (平铺原生架构 + 智能 Raw 联动)
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

        # -------------------------------------------------------------
        # 1. 读入实拍素材 (默认勾选 raw)
        # -------------------------------------------------------------
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

        # -------------------------------------------------------------
        # 2. 色彩转换与切换控制节点 (与 Read 节点 raw data 联动)
        # -------------------------------------------------------------
        col_convert = nuke.createNode("Colorspace", inpanel=False)
        col_convert.setInput(0, read_plate)
        col_convert.setName(f"Colorspace_LogC_to_Linear_{shot}")
        valid_in = self._get_valid_colorspace_value(col_convert['colorspace_in'], ["AlexaV3LogC", "LogC", "linear"])
        valid_out = self._get_valid_colorspace_value(col_convert['colorspace_out'], ["linear", "scene_linear", "ACEScg", "Linear"])
        if valid_in: col_convert['colorspace_in'].setValue(valid_in)
        if valid_out: col_convert['colorspace_out'].setValue(valid_out)
        col_convert.setXYpos(120, 80)

        color_switch = nuke.createNode("Switch", inpanel=False)
        color_switch.setName(f"ColorMode_Switch_{shot}")
        color_switch.setInput(0, read_plate)   # 0: 直通 (标准普通素材)
        color_switch.setInput(1, col_convert)  # 1: LogC -> Linear 转正

        # 添加可视化下拉菜单
        mode_knob = nuke.Enumeration_Knob("color_mode", "素材色彩模式", [
            "标准普通素材 (sRGB / 直通)", 
            "电影机灰片 (LogC -> Linear 转正)"
        ])
        mode_knob.setValue(1) # 默认预设为电影灰片模式
        color_switch.addKnob(mode_knob)
        color_switch['which'].setExpression("color_mode")
        color_switch.setXYpos(0, 160)

        # 【核心联动绑定】：Read 的 raw data 自动跟随色彩模式切换
        # 当 color_mode == 1 (灰片模式) 时 raw 为 True；当 color_mode == 0 (普通素材) 时 raw 为 False
        if 'raw' in read_plate.knobs():
            read_plate['raw'].setExpression(f"{color_switch.name()}.which == 1")

        # -------------------------------------------------------------
        # 3. 预留 Roto 遮罩与羽化节点
        # -------------------------------------------------------------
        holdout_roto = nuke.createNode("Roto", inpanel=False)
        holdout_roto.setInput(0, read_plate)
        holdout_roto.setName(f"Holdout_Roto_KEEP_{shot}")
        holdout_roto['label'].setValue("【圈要的: 身体发灰处圈选补实心】")
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
        garbage_roto['label'].setValue("【圈不要的: 穿帮灯具/四周杂物圈选切除】")
        garbage_roto.setXYpos(440, 0)

        blur_outm = nuke.createNode("Blur", inpanel=False)
        blur_outm.setInput(0, garbage_roto)
        blur_outm.setName(f"Blur_OutM_{shot}")
        blur_outm['channels'].setValue("alpha")
        blur_outm['size'].setValue(6.0)
        blur_outm.setXYpos(440, 80)

        # -------------------------------------------------------------
        # 4. 原生 Keylight 节点 (直接平铺在主图，参数实时生效)
        # -------------------------------------------------------------
        kl = nuke.createNode("OFXuk.co.thefoundry.keylight.keylight_v201", inpanel=False)
        kl.setName(f"Keyer_Alpha_{shot}")
        kl.setXYpos(260, 180)

        # 严格物理端口连接
        kl.setInput(0, color_switch)  # Input 0: Source
        kl.setInput(1, blur_inm)      # Input 1: InM (Holdout)
        kl.setInput(2, blur_outm)     # Input 2: OutM (Garbage)

        # 遮罩组件默认设为 "None"，保障自由吸色绝不锁死
        if "insideComponent" in kl.knobs():
            kl["insideComponent"].setValue("None")
        if "outsideComponent" in kl.knobs():
            kl["outsideComponent"].setValue("None")

        # 参数初始值与安全视图模式
        for cw in ['clipwhite', 'clipWhite', 'clip_white']:
            if cw in kl.knobs(): kl[cw].setValue(1.0); break

        for cb in ['clipblack', 'clipBlack', 'clip_black']:
            if cb in kl.knobs(): kl[cb].setValue(0.0); break

        for sh in ['show', 'view']:
            if sh in kl.knobs(): kl[sh].setValue("Final Result"); break

        # -------------------------------------------------------------
        # 5. Copy Alpha -> Premult -> Write 输出
        # -------------------------------------------------------------
        copy_alpha = nuke.createNode("Copy", inpanel=False)
        copy_alpha.setName(f"Copy_Alpha_{shot}")
        copy_alpha.setInput(0, color_switch) # 0: RGB
        copy_alpha.setInput(1, kl)           # 1: Keylight Alpha
        copy_alpha['from0'].setValue("rgba.alpha")
        copy_alpha['to0'].setValue("rgba.alpha")
        copy_alpha.setXYpos(0, 260)

        premult = nuke.createNode("Premult", inpanel=False)
        premult.setName(f"Premult_{shot}")
        premult.setInput(0, copy_alpha)
        premult.setXYpos(0, 330)

        # Write 节点输出 PNG (严格锁定 default (sRGB))
        png_out_pattern = f"{target_bg_dir}/bg_{shot}_####.png"
        write_ue = nuke.createNode("Write", inpanel=False)
        write_ue.setInput(0, premult)
        write_ue.setName(f"Write_Final_PNG_{shot}")
        write_ue['file'].setValue(png_out_pattern)
        write_ue['channels'].setValue("rgba")
        write_ue['file_type'].setValue("png")
        write_ue['datatype'].setValue("8 bit")
        self._set_safe_write_colorspace(write_ue, ["default (sRGB)", "Output - sRGB", "sRGB", "default"])
        write_ue.setXYpos(0, 410)

        # 背景框清晰整理
        bd = nuke.createNode("BackdropNode", inpanel=False)
        bd['label'].setValue(f"<center><b>Shot {shot} 抠像底板生成 (平铺直观·原生高响应版)</b></center>")
        bd['note_font_size'].setValue(16)
        bd['tile_color'].setValue(0x1a402500)
        bd.setXYpos(-40, -50)
        bd['bdwidth'].setValue(640)
        bd['bdheight'].setValue(520)

        nuke.scriptSave()

        # 视口连在 Keyer_Alpha 上，方便直接吸取背景色
        viewer = nuke.activeViewer()
        if viewer:
            viewer.node().setInput(0, kl)

        nuke.show(kl)
        nuke.message("【节点网络已平铺生成】\n\n👉 操作指南:\n1. 节点完全直观平铺：双击 Keyer_Alpha 可直接调节 Clip White/Black，拖动实时响应；\n2. 色彩联动：双击 ColorMode_Switch 切换模式，Read 节点的 Raw Data 会自动联动开/关；\n3. 遮罩应用：画好 Roto 后，在 Keyer_Alpha 中将 insideComponent 设为 Alpha (补心)，outsideComponent 设为 Inverted Alpha (切杂物)；\n4. Write 输出已锁定为 [default (sRGB)]，随时可点 Render 输出！")

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

        start_x = 700
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