# -*- coding: utf-8 -*-
"""
UE5.3/5.4 影视级镜头分层裂变与 Movie Render Queue (MRQ) 自动化调度中心 v5.8 Studio Pro
-------------------------------------------------------------------------
核心特性：
1. [每个镜头 Sequence 渲染完成即刻自动弹出对应输出文件夹 (v5.8 核心升级)]：
   - 彻底修复旧版 _LL_MRQ_MONITOR_HANDLE 跨版本未注销导致只弹最后一个目录的问题；
   - 双通道实时监听 (on_individual_job_finished_delegate + Slate Tick 镜头进度追踪)：
     队列中每渲染完一个镜头 Sequence，立即自动弹出该镜头对应的 .../publish/vXXX/render 文件夹，
     全部渲染结束时自动兜底补齐弹出队列中所有已渲染镜头的输出目录！
2. [多镜头批量渲染输出路径与相机视角 100% 独立隔离]：
   - 每个 Job 通过 get_configuration().copy_from(preset_asset) 独立深拷贝预设配置并各自锁定专属的 output_directory；
   - 入列与拆层时自动校验并锁定每个序列的 Camera Cut 轨道绑定至当前镜头专属的 CineCameraActor。
3. [直接替换当前版本时不删除已渲染图片 + 创建分层后 UE 内容浏览器自动定位 + Bilibili #19a3d6 图标]。
-------------------------------------------------------------------------
Author: LiangLiangArtist
Contact: liangliangvfx@gmail.com
"""

import os
import re
import sys
import json
import shutil
import ctypes
import subprocess
import webbrowser
import unreal

TOOL_VERSION_TAG    = "5.8"

# =========================================================================
# 创作者与社交主页配置 (点击 UI 底部对应图标直接跳转)
# =========================================================================
AUTHOR_NAME         = "LiangLiangArtist"
AUTHOR_EMAIL        = "liangliangvfx@gmail.com"
AUTHOR_GITHUB_URL   = "https://github.com/LiangLiangVFX"
AUTHOR_YOUTUBE_URL  = "https://www.youtube.com/@zhaol2259"
AUTHOR_BILIBILI_URL = "https://space.bilibili.com/75504176"

CONFIG_FILE_PATH = os.path.normpath(os.path.join(unreal.Paths.project_saved_dir(), "UECamWorkflowConfig.json"))

# 标准子关卡后缀与存放规范
SUBLEVEL_ROLE_SPECS = [
    ("scence",    "scence",      "Map/Scence", "场景模型层 (scence)",     "静态网格体(StaticMesh)、地形(Landscape)、建筑、植被 (不移动模型)"),
    ("env",       "env_lgt",     "Map/Light",  "环境天光层 (env)",        "仅存放天光 (SkyLight)"),
    ("key",       "key_lgt",     "Map/Light",  "主方向光层 (key)",        "仅存放主平行光 (DirectionalLight 太阳光/月光)"),
    ("sky",       "sky_lgt",     "Map/Light",  "纯天空层 (sky·不含场景)", "天空球 (SM_SkySphere/BP_Sky)、大气 (SkyAtmosphere)、体积云"),
    ("heightfog", "heightfog",   "Map/Light",  "指数高度雾 (heightfog)",  "指数高度雾 (ExponentialHeightFog)"),
    ("fill",      "fill01_lgt",  "Map/Light",  "场景补光层 (fill)",       "场景局部补光：点光源(PointLight)、聚光灯(SpotLight)、矩形光(RectLight)"),
    ("fog",       "fog",         "Map/Light",  "半透明雾片 (fog)",        "EasyFog 雾片蓝图、局部半透明雾气面片"),
]

# 1. 官方默认渲染状态还原字典 (写入 CVar_Default_Restore)
CVAR_DEFAULT_RESTORE = {
    "ShowFlag.Diffuse": 2,
    "ShowFlag.Specular": 2,
    "ShowFlag.Translucency": 2,
    "ShowFlag.Fog": 2,
}

# 2. 指数高度雾层专属控制台变量 (写入 CVar_HeightFog_Only)
CVAR_HEIGHTFOG_LAYER = {
    "ShowFlag.Diffuse": 0,
    "ShowFlag.Specular": 0,
    "ShowFlag.Translucency": 0,
    "ShowFlag.Fog": 2,
}

# 3. 半透明雾片层专属控制台变量 (写入 CVar_EasyFog_Only)
CVAR_EASYFOG_LAYER = {
    "ShowFlag.Diffuse": 0,
    "ShowFlag.Specular": 0,
    "ShowFlag.Translucency": 2,
    "ShowFlag.Fog": 0,
}

# MRQ GameOverrides 污染变量清理黑名单 (仅用于保持 CVarPresets 雾气资产纯净，不影响 MRQ 渲染预设中的 Game Overrides 生效)
POLLUTED_MRQ_CVARS = [
    "sg.ViewDistanceQuality", "sg.AntiAliasingQuality", "sg.ShadowQuality",
    "sg.GlobalIlluminationQuality", "sg.ReflectionQuality", "sg.PostProcessQuality",
    "sg.TextureQuality", "sg.EffectsQuality", "sg.FoliageQuality",
    "sg.ShadingQuality", "sg.LandscapeQuality", "sg.ResolutionQuality",
    "r.SkeletalMeshLODBias", "r.ViewDistanceScale", "r.Shadow.RadiusThreshold",
    "r.Shadow.DistanceScale", "r.HLOD", "r.ResetRenderTargetsExtent",
    "r.LocalHeightFog", "r.PostProcessing.PropagateAlpha",
    "ShowFlag.GlobalIllumination", "ShowFlag.ReflectionEnvironment", "ShowFlag.LumenReflections"
]

DERIVED_SEQ_SUFFIXES = (
    "_env", "_key", "_sky", "_heightfog", "_expfog", "_fill", "_fog", "_easyfog",
    "_emiss", "_emi", "_id_actor", "_id_material", "_actor", "_material", "_aov", "_lgt"
)

RENDER_IMG_EXTENSIONS = ('.exr', '.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')


# =========================================================================
# 渲染完成自动弹出输出目录监听器 (支持每个镜头 Sequence 渲染完即刻弹出对应目录)
# =========================================================================
def open_folder_in_explorer(folder_path):
    if not folder_path:
        return False
    norm_p = os.path.normpath(folder_path)
    if not os.path.exists(norm_p):
        return False
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", norm_p])
        else:
            os.startfile(norm_p)
        print(f"[RenderLayer] 已自动弹出渲染输出文件夹: {norm_p}")
        return True
    except Exception:
        try:
            os.startfile(norm_p)
            return True
        except Exception:
            return False


def _extract_job_output_dir(job):
    """提取单个 MRQ Job 绑定的真实输出路径"""
    if not job:
        return ""
    try:
        cfg = job.get_configuration()
        if cfg:
            c_out = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
            if c_out and c_out.output_directory.path:
                return os.path.normpath(str(c_out.output_directory.path)).replace('\\', '/')
    except Exception:
        pass
    try:
        preset = job.get_preset_origin() if hasattr(job, "get_preset_origin") else None
        if preset:
            p_out = preset.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
            if p_out and p_out.output_directory.path:
                return os.path.normpath(str(p_out.output_directory.path)).replace('\\', '/')
    except Exception:
        pass
    return ""


def _extract_all_output_dirs_from_active_queue(only_enabled=True):
    """按队列顺序提取所有待渲染镜头的输出路径列表（去重且保持顺序）"""
    dirs = []
    try:
        mrq_sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        queue = mrq_sub.get_queue()
        if queue:
            for job in queue.get_jobs():
                if only_enabled and hasattr(job, "is_enabled") and not job.is_enabled():
                    continue
                job_dir = _extract_job_output_dir(job)
                if job_dir and job_dir not in dirs:
                    dirs.append(job_dir)
    except Exception:
        pass
    if not dirs:
        cached = list(getattr(sys, "_LL_LAST_RENDER_OUT_DIRS", []))
        if cached:
            return cached
        last_d = getattr(sys, "_LL_LAST_RENDER_OUT_DIR", "")
        if last_d:
            dirs.append(last_d)
    return dirs


def _extract_active_shot_groups_from_queue():
    """
    将当前队列中启用的 Job 按输出目录分组：
    返回 [(out_dir, [job_name_1, job_name_2, ...]), ...]
    用于精确判断每个镜头的所有分层何时渲染完毕！
    """
    groups = []
    group_map = {}
    try:
        mrq_sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        queue = mrq_sub.get_queue()
        if queue:
            for job in queue.get_jobs():
                if hasattr(job, "is_enabled") and not job.is_enabled():
                    continue
                j_dir = _extract_job_output_dir(job)
                j_name = str(job.job_name).strip()
                if not j_dir:
                    continue
                if j_dir not in group_map:
                    g_list = []
                    group_map[j_dir] = g_list
                    groups.append((j_dir, g_list))
                if j_name and j_name not in group_map[j_dir]:
                    group_map[j_dir].append(j_name)
    except Exception:
        pass
    return groups


def _count_rendered_files_for_seq_in_dir(out_dir, seq_name):
    if not out_dir or not os.path.exists(out_dir) or not seq_name:
        return 0
    prefix = f"{seq_name.lower()}."
    cnt = 0
    try:
        for f in os.listdir(out_dir):
            low_f = f.lower()
            if low_f.startswith(prefix) and low_f.endswith(RENDER_IMG_EXTENSIONS):
                cnt += 1
    except Exception:
        pass
    return cnt


def _extract_output_dir_from_active_queue():
    dirs = _extract_all_output_dirs_from_active_queue(only_enabled=False)
    return dirs[-1] if dirs else getattr(sys, "_LL_LAST_RENDER_OUT_DIR", "")


def ensure_mrq_render_finish_monitor_active(target_out_dir=""):
    if target_out_dir:
        norm_t = os.path.normpath(target_out_dir).replace('\\', '/')
        sys._LL_LAST_RENDER_OUT_DIR = norm_t
        cached_dirs = list(getattr(sys, "_LL_LAST_RENDER_OUT_DIRS", []))
        if norm_t not in cached_dirs:
            cached_dirs.append(norm_t)
        sys._LL_LAST_RENDER_OUT_DIRS = cached_dirs

    # 若之前注册的是旧版本的监控器，先强制注销并重新注册 v5.8 多镜头逐个弹出监控器
    old_handle = getattr(sys, "_LL_MRQ_MONITOR_HANDLE", None)
    old_ver = getattr(sys, "_LL_MRQ_MONITOR_VER", "")
    if old_handle is not None and old_ver == TOOL_VERSION_TAG:
        return
    if old_handle is not None:
        try:
            unreal.unregister_slate_post_tick_callback(old_handle)
        except Exception:
            pass
        sys._LL_MRQ_MONITOR_HANDLE = None

    try:
        mrq_sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        sys._LL_WAS_MRQ_RENDERING = bool(mrq_sub.is_rendering())
    except Exception:
        sys._LL_WAS_MRQ_RENDERING = False

    sys._LL_POPPED_DIRS_IN_SESSION = set()
    sys._LL_SHOT_GROUPS_SNAPSHOT = []
    sys._LL_ACTIVE_GROUP_IDX = -1

    def _mrq_watch_tick(delta_time):
        try:
            mrq_s = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
            cur_rendering = bool(mrq_s.is_rendering())
            was_rendering = getattr(sys, "_LL_WAS_MRQ_RENDERING", False)

            if cur_rendering and not was_rendering:
                # 渲染刚刚启动：记录队列中所有镜头的输出目录与初始文件数快照
                sys._LL_WAS_MRQ_RENDERING = True
                sys._LL_POPPED_DIRS_IN_SESSION = set()
                groups = _extract_active_shot_groups_from_queue()
                sys._LL_SHOT_GROUPS_SNAPSHOT = groups
                sys._LL_ACTIVE_GROUP_IDX = 0 if groups else -1

                detected_dirs = [d for d, _ in groups] or _extract_all_output_dirs_from_active_queue()
                if detected_dirs:
                    sys._LL_LAST_RENDER_OUT_DIRS = detected_dirs
                    sys._LL_LAST_RENDER_OUT_DIR = detected_dirs[-1]

                # 记录启动瞬间各目录的文件修改时间基线
                baseline_mtime = {}
                for d_path in detected_dirs:
                    newest_t = 0.0
                    if d_path and os.path.exists(d_path):
                        try:
                            for fn in os.listdir(d_path):
                                if fn.lower().endswith(RENDER_IMG_EXTENSIONS):
                                    mt = os.path.getmtime(os.path.join(d_path, fn))
                                    if mt > newest_t:
                                        newest_t = mt
                        except Exception:
                            pass
                    baseline_mtime[d_path] = newest_t
                sys._LL_RENDER_START_MTIME = baseline_mtime

            elif cur_rendering and was_rendering:
                # 渲染进行中：当检测到下一个镜头的输出目录已经开始生成新帧，说明上一个镜头已渲染完毕，立即弹出上一个镜头的文件夹！
                groups = getattr(sys, "_LL_SHOT_GROUPS_SNAPSHOT", [])
                popped = getattr(sys, "_LL_POPPED_DIRS_IN_SESSION", set())
                base_mt = getattr(sys, "_LL_RENDER_START_MTIME", {})
                if len(groups) >= 2:
                    for idx in range(len(groups) - 1):
                        prev_dir, _ = groups[idx]
                        if prev_dir in popped:
                            continue
                        # 检查后续任意镜头目录是否已经产出了新渲染帧
                        next_has_new_frame = False
                        for next_idx in range(idx + 1, len(groups)):
                            nxt_dir, _ = groups[next_idx]
                            if nxt_dir and os.path.exists(nxt_dir):
                                b_time = base_mt.get(nxt_dir, 0.0)
                                try:
                                    for fn in os.listdir(nxt_dir):
                                        if fn.lower().endswith(RENDER_IMG_EXTENSIONS):
                                            if os.path.getmtime(os.path.join(nxt_dir, fn)) > b_time + 0.5:
                                                next_has_new_frame = True
                                                break
                                except Exception:
                                    pass
                            if next_has_new_frame:
                                break
                        if next_has_new_frame:
                            popped.add(prev_dir)
                            sys._LL_POPPED_DIRS_IN_SESSION = popped
                            open_folder_in_explorer(prev_dir)

            elif not cur_rendering and was_rendering:
                # 队列全部渲染结束：弹出所有尚未弹出的镜头输出目录（确保每个渲染过的镜头目录都 100% 弹出）
                sys._LL_WAS_MRQ_RENDERING = False
                popped = getattr(sys, "_LL_POPPED_DIRS_IN_SESSION", set())
                all_dirs = _extract_all_output_dirs_from_active_queue() or getattr(sys, "_LL_LAST_RENDER_OUT_DIRS", [])
                for od in all_dirs:
                    if od and od not in popped and os.path.exists(od):
                        popped.add(od)
                        open_folder_in_explorer(od)
                sys._LL_POPPED_DIRS_IN_SESSION = popped
        except Exception:
            pass

    try:
        sys._LL_MRQ_MONITOR_HANDLE = unreal.register_slate_post_tick_callback(_mrq_watch_tick)
        sys._LL_MRQ_MONITOR_VER = TOOL_VERSION_TAG
    except Exception:
        pass


class UERenderLayerPipeline(object):
    def __init__(self):
        self.asset_sub = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
        self.actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        self.mrq_sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        self.asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        self.asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
        ensure_mrq_render_finish_monitor_active()

    def load_config(self):
        if os.path.exists(CONFIG_FILE_PATH):
            try:
                with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_config(self, cfg_data):
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE_PATH), exist_ok=True)
            with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[RenderLayer] 保存配置提示: {e}")

    def detect_project_standard_folders(self):
        world = unreal.EditorLevelLibrary.get_editor_world()
        world_pkg = world.get_path_name().split('.')[0] if world else ""

        proj_root = "/Game"
        if world_pkg.startswith("/Game/"):
            parts = [p for p in world_pkg.split('/') if p]
            if "Map" in parts:
                map_idx = parts.index("Map")
                if map_idx >= 1:
                    proj_root = "/" + "/".join(parts[:map_idx])
            elif len(parts) >= 2:
                proj_root = f"/Game/{parts[1]}"

        if proj_root == "/Game":
            content_disk = os.path.normpath(unreal.Paths.project_content_dir()).replace('\\', '/')
            if os.path.exists(content_disk):
                for d in os.listdir(content_disk):
                    full_d = os.path.join(content_disk, d)
                    if os.path.isdir(full_d):
                        sub_dirs = [sd.lower() for sd in os.listdir(full_d) if os.path.isdir(os.path.join(full_d, sd))]
                        if "map" in sub_dirs or "shot" in sub_dirs:
                            proj_root = f"/Game/{d}"
                            break

        light_dir = f"{proj_root.rstrip('/')}/Map/Light"
        scence_dir = f"{proj_root.rstrip('/')}/Map/Scence"
        shot_root_dir = f"{proj_root.rstrip('/')}/Shot"
        cvar_dir = f"{shot_root_dir}/CVarPresets"
        collection_dir = f"{shot_root_dir}/Collection"

        if not self.asset_sub.does_directory_exist(scence_dir) and self.asset_sub.does_directory_exist(f"{proj_root.rstrip('/')}/Map/Scene"):
            scence_dir = f"{proj_root.rstrip('/')}/Map/Scene"

        old_cvar_dir = f"{light_dir}/CVarPresets"
        if self.asset_sub.does_directory_exist(old_cvar_dir):
            try:
                self.asset_sub.delete_directory(old_cvar_dir)
            except Exception:
                pass

        return {
            "proj_root": proj_root,
            "light_dir": light_dir,
            "scence_dir": scence_dir,
            "shot_root_dir": shot_root_dir,
            "cvar_dir": cvar_dir,
            "collection_dir": collection_dir
        }

    def is_derived_layer_sequence_name(self, seq_short_name):
        low = str(seq_short_name).strip().lower()
        if any(low.endswith(sfx) for sfx in DERIVED_SEQ_SUFFIXES):
            return True
        if re.search(r'cam\d+_[a-zA-Z]+', low):
            return True
        return False

    def list_all_master_sequences_in_project(self):
        result_map = {}
        try:
            all_assets = self.asset_reg.get_all_assets()
            for ad in all_assets:
                cls_name = str(ad.asset_class_path.asset_name) if hasattr(ad, "asset_class_path") else str(getattr(ad, "asset_class", ""))
                if cls_name == "LevelSequence":
                    a_name = str(ad.asset_name)
                    pkg_path = str(ad.package_name)
                    if pkg_path.startswith("/Game/") and not self.is_derived_layer_sequence_name(a_name):
                        result_map[pkg_path] = a_name
        except Exception:
            pass

        items = [(name, pkg) for pkg, name in result_map.items()]
        items.sort(key=lambda x: x[0].lower())
        return items

    def get_active_master_sequence(self, master_seq_path="", allow_content_browser_selection=True):
        if master_seq_path and self.asset_sub.does_asset_exist(master_seq_path):
            return self.asset_sub.load_asset(master_seq_path)

        cand_seq = None
        try:
            cand_seq = unreal.LevelSequenceEditorBlueprintLibrary.get_current_level_sequence()
        except Exception:
            pass

        if not cand_seq and allow_content_browser_selection:
            try:
                selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
                for asset in selected_assets:
                    if isinstance(asset, unreal.LevelSequence):
                        cand_seq = asset
                        break
            except Exception:
                pass

        if not cand_seq:
            return None

        seq_name = cand_seq.get_name()
        if self.is_derived_layer_sequence_name(seq_name):
            pkg_folder = os.path.dirname(cand_seq.get_path_name().split('.')[0])
            shot_m = re.search(r'cam(\d+)', seq_name, re.IGNORECASE)
            if shot_m:
                shot_num = shot_m.group(1)
                assets_in_dir = self.asset_sub.list_assets(pkg_folder, recursive=False)
                for ap in assets_in_dir:
                    short_n = os.path.basename(ap.split('.')[0])
                    if f"cam{shot_num}" in short_n.lower() and not self.is_derived_layer_sequence_name(short_n):
                        master_cand = self.asset_sub.load_asset(ap)
                        if master_cand:
                            return master_cand

        return cand_seq

    def get_exact_timeline_range(self, level_seq):
        if not level_seq:
            return None, None, None
        start_f = int(level_seq.get_playback_start())
        end_f_exclusive = int(level_seq.get_playback_end())
        end_f_inclusive = max(start_f, end_f_exclusive - 1)
        return start_f, end_f_inclusive, end_f_exclusive

    def parse_ep_and_shot_from_seq(self, master_seq):
        seq_name = master_seq.get_name()
        pkg_path = master_seq.get_path_name()

        ep = "EP01"
        ep_m = re.search(r'(ep\d+)', pkg_path, re.IGNORECASE)
        if not ep_m:
            ep_m = re.search(r'(ep\d+)', seq_name, re.IGNORECASE)
        if ep_m:
            ep = ep_m.group(1).upper()

        shot = "1001"
        shot_m = re.search(r'cam(\d+)', seq_name, re.IGNORECASE)
        if shot_m:
            shot = shot_m.group(1)
        else:
            nums = re.findall(r'(\d{3,5})', pkg_path)
            if nums:
                shot = nums[-1]

        return ep, shot

    def sync_content_browser_to_sequences(self, seq_objects_list, shot_folder=""):
        """在 UE 内容浏览器中自动定位并高亮生成的分层 Sequence 资产"""
        try:
            asset_paths = []
            for seq_obj in (seq_objects_list or []):
                if seq_obj:
                    pkg_p = seq_obj.get_path_name().split('.')[0]
                    if pkg_p and pkg_p not in asset_paths:
                        asset_paths.append(pkg_p)
            if asset_paths:
                unreal.EditorAssetLibrary.sync_browser_to_objects(asset_paths)
            elif shot_folder:
                unreal.EditorAssetLibrary.sync_browser_to_objects([shot_folder])
        except Exception as e:
            print(f"[RenderLayer] 同步定位内容浏览器提示: {e}")

    def ensure_sequence_camera_cut_bound_to_shot(self, level_seq, shot_num, start_f, end_f_exc):
        """
        确保当前序列的 Camera Cut Track 严格绑定到当前镜头号 (如 2220 / 2180) 对应的 CineCameraActor，
        防止多镜头切换或拆层时串用其他镜头的相机视角。
        """
        if not level_seq or not shot_num:
            return
        try:
            target_cam_binding = None
            shot_str = str(shot_num).lower()
            for b in level_seq.get_bindings():
                b_name = str(b.get_name()).lower()
                if shot_str in b_name and ("cam" in b_name or "cine" in b_name):
                    target_cam_binding = b
                    break

            if not target_cam_binding:
                for act in self.actor_sub.get_all_level_actors():
                    if isinstance(act, (unreal.CineCameraActor, unreal.CameraActor)):
                        lbl = act.get_actor_label().lower()
                        if shot_str in lbl:
                            target_cam_binding = level_seq.add_possessable(act)
                            break

            if not target_cam_binding:
                return

            cam_cut_track = None
            for tr in level_seq.get_tracks():
                if isinstance(tr, unreal.MovieSceneCameraCutTrack):
                    cam_cut_track = tr
                    break

            if not cam_cut_track:
                cam_cut_track = level_seq.add_track(unreal.MovieSceneCameraCutTrack)

            sections = list(cam_cut_track.get_sections()) if cam_cut_track else []
            if not sections and cam_cut_track:
                sec = cam_cut_track.add_section()
                sec.set_range(int(start_f), int(end_f_exc))
                sections = [sec]

            binding_id = unreal.MovieSceneObjectBindingID()
            binding_id.set_editor_property("guid", target_cam_binding.get_id())

            for sec in sections:
                if hasattr(sec, "set_camera_binding_id"):
                    sec.set_camera_binding_id(binding_id)
                else:
                    sec.set_editor_property("camera_binding_id", binding_id)
        except Exception as e:
            print(f"[RenderLayer] 校验镜头相机绑定提示 ({level_seq.get_name()}): {e}")

    def _is_valid_sublevel_name(self, name_str):
        if not name_str:
            return False
        low = str(name_str).strip().lower()
        bad_prefixes = ("cvar_", "mpc_", "renderset", "aov_", "global_", "mrq_")
        if any(low.startswith(bp) for bp in bad_prefixes):
            return False
        return True

    def _is_true_world_map_asset(self, asset_path_str):
        pkg_p = str(asset_path_str).split('.')[0]
        short_n = os.path.basename(pkg_p)
        if not self._is_valid_sublevel_name(short_n):
            return False

        if pkg_p.startswith("/Game/"):
            rel_p = pkg_p[len("/Game/"):]
            content_disk = os.path.normpath(unreal.Paths.project_content_dir()).replace('\\', '/')
            umap_disk_path = os.path.join(content_disk, f"{rel_p}.umap")
            if os.path.exists(umap_disk_path):
                return True
            uasset_disk_path = os.path.join(content_disk, f"{rel_p}.uasset")
            if os.path.exists(uasset_disk_path):
                return False

        try:
            ad = self.asset_sub.find_asset_data(pkg_p)
            if ad:
                if hasattr(ad, "asset_class_path"):
                    cls_asset_name = str(ad.asset_class_path.asset_name)
                else:
                    cls_asset_name = str(getattr(ad, "asset_class", ""))
                return cls_asset_name == "World"
        except Exception:
            pass
        return False

    def organize_sublevels_in_levels_panel(self, light_level_names=None):
        world = unreal.EditorLevelLibrary.get_editor_world()
        if not world:
            return

        cand_names = list(light_level_names or [])
        try:
            for lvl in unreal.EditorLevelUtils.get_levels(world):
                if lvl and lvl.get_outer():
                    sn = lvl.get_outer().get_name()
                    low = sn.lower()
                    if any(k in low for k in ("_lgt", "env", "key", "sky", "fog", "fill")) and "scence" not in low and "scene" not in low:
                        if sn not in cand_names:
                            cand_names.append(sn)
        except Exception:
            pass

        for sub_name in cand_names:
            if not sub_name:
                continue
            try:
                stream_lvl = unreal.GameplayStatics.get_streaming_level(world, unreal.Name(sub_name))
                if stream_lvl and hasattr(stream_lvl, "set_folder_path"):
                    stream_lvl.set_folder_path(unreal.Name("Light"))
            except Exception:
                pass

    def scan_mounted_and_folder_sublevels(self, custom_light_dir="", custom_scence_dir=""):
        world = unreal.EditorLevelLibrary.get_editor_world()
        world_name = world.get_name() if world else "DefaultWorld"
        world_pkg = world.get_path_name().split('.')[0] if world else ""

        std_dirs = self.detect_project_standard_folders()
        light_dir = custom_light_dir.strip() if custom_light_dir.strip() else std_dirs["light_dir"]
        scence_dir = custom_scence_dir.strip() if custom_scence_dir.strip() else std_dirs["scence_dir"]

        mounted_sublevels = []
        try:
            persistent_name = world_name.lower()
            levels = unreal.EditorLevelUtils.get_levels(world)
            for lvl in levels:
                outer = lvl.get_outer()
                if outer:
                    short_name = outer.get_name()
                    if short_name.lower() != persistent_name and self._is_valid_sublevel_name(short_name) and short_name not in mounted_sublevels:
                        mounted_sublevels.append(short_name)
        except Exception:
            pass

        folder_map_names = []
        for check_folder in [scence_dir, light_dir]:
            if check_folder and self.asset_sub.does_directory_exist(check_folder):
                assets = self.asset_sub.list_assets(check_folder, recursive=True)
                for ap in assets:
                    pkg_p = ap.split('.')[0]
                    if pkg_p.lower() == world_pkg.lower():
                        continue
                    if self._is_true_world_map_asset(ap):
                        short_n = os.path.basename(pkg_p)
                        if short_n not in folder_map_names:
                            folder_map_names.append(short_n)

        level_actor_features = {ln: set() for ln in mounted_sublevels}
        if mounted_sublevels:
            try:
                for act in self.actor_sub.get_all_level_actors():
                    outer_lvl = act.get_outer()
                    if not outer_lvl or not outer_lvl.get_outer():
                        continue
                    lvl_short = outer_lvl.get_outer().get_name()
                    if lvl_short not in level_actor_features:
                        continue
                    role_key = self._classify_single_actor_role(act)
                    if role_key:
                        level_actor_features[lvl_short].add(role_key)
            except Exception:
                pass

        classified = {
            "scence": [], "env": [], "key": [], "sky": [],
            "heightfog": [], "fill": [], "fog": [], "others": []
        }

        all_candidate_names = list(mounted_sublevels)
        for fn in folder_map_names:
            if fn not in all_candidate_names:
                all_candidate_names.append(fn)

        for lname in all_candidate_names:
            if not self._is_valid_sublevel_name(lname):
                continue
            low = lname.lower()
            feats = level_actor_features.get(lname, set())

            if "scence" in low or "scene" in low or low.endswith("_geo") or low.endswith("_bg"):
                classified["scence"].append(lname)
            elif "heightfog" in low or "expfog" in low:
                classified["heightfog"].append(lname)
            elif "sky" in low and ("lgt" in low or "sphere" in low or low.endswith("sky")):
                classified["sky"].append(lname)
            elif "env" in low and ("lgt" in low or "light" in low or low.endswith("env")):
                classified["env"].append(lname)
            elif "key" in low and ("lgt" in low or "light" in low or low.endswith("key")):
                classified["key"].append(lname)
            elif "fill" in low:
                classified["fill"].append(lname)
            elif "fog" in low and "height" not in low:
                classified["fog"].append(lname)
            elif "heightfog" in feats:
                classified["heightfog"].append(lname)
            elif "fog" in feats:
                classified["fog"].append(lname)
            elif "key" in feats:
                classified["key"].append(lname)
            elif "env" in feats and "key" not in feats:
                classified["env"].append(lname)
            elif "sky" in feats and "scence" not in feats:
                classified["sky"].append(lname)
            elif "fill" in feats and "scence" not in feats:
                classified["fill"].append(lname)
            elif "scence" in feats:
                classified["scence"].append(lname)
            else:
                classified["others"].append(lname)

        cfg = self.load_config()
        saved_map = cfg.get("world_sublevel_map", {}).get(world_name, {})
        if saved_map and all_candidate_names:
            cleaned_saved_map = {}
            for k in ["scence", "env", "key", "sky", "heightfog", "fill", "fog"]:
                if k in saved_map and saved_map[k]:
                    valid_saved = [
                        dn for dn in saved_map[k]
                        if dn in all_candidate_names and self._is_valid_sublevel_name(dn)
                    ]
                    if valid_saved:
                        classified[k] = valid_saved
                        cleaned_saved_map[k] = valid_saved
            cfg["world_sublevel_map"][world_name] = cleaned_saved_map
            self.save_config(cfg)

        return all_candidate_names, classified, light_dir, scence_dir

    def _classify_single_actor_role(self, act):
        if not act:
            return None

        cls_name = act.get_class().get_name().lower()
        act_label = act.get_actor_label().lower()
        folder_path = str(act.get_folder_path()).lower() if hasattr(act, "get_folder_path") else ""

        if "!cam" in folder_path or "cam" in folder_path:
            return None
        if isinstance(act, (unreal.CameraActor, unreal.CineCameraActor, unreal.PostProcessVolume)) or "postprocess" in cls_name:
            return None
        if any(k in act_label for k in ["shot_root", "imageplate", "sm_ref_"]):
            return None
        if any(sys_k in cls_name for sys_k in [
            "worldsettings", "defaultphysicsvolume", "brush", "levelbounds",
            "worlddatalayers", "worldpartition", "navigationdata", "abstractnavdata",
            "gameplaydebugger", "chaos"
        ]):
            return None

        if isinstance(act, unreal.ExponentialHeightFog) or "exponentialheightfog" in cls_name:
            return "heightfog"
        if "easyfog" in act_label or "easyfog" in cls_name or "fogcard" in act_label or "fog_card" in act_label or "fogsheet" in act_label:
            return "fog"
        if isinstance(act, unreal.DirectionalLight) or "directionallight" in cls_name:
            return "key"
        if isinstance(act, unreal.SkyLight) or "skylight" in cls_name:
            return "env"
        if any(k in cls_name for k in ["skyatmosphere", "volumetriccloud"]) or any(k in act_label for k in ["skysphere", "bp_sky", "sky_sphere", "skydome"]):
            return "sky"
        if any(k in cls_name for k in ["pointlight", "spotlight", "rectlight", "light"]):
            return "fill"

        return "scence"

    def create_or_mount_light_sublevels(self, prefix_str="night_", light_dir="", scence_dir="", auto_move_lights_and_fog=False):
        world = unreal.EditorLevelLibrary.get_editor_world()
        if not world:
            return False, "无法获取当前打开的关卡世界！"

        world_pkg_path = world.get_path_name().split('.')[0]
        if world_pkg_path.startswith("/Temp/") or "Untitled" in world_pkg_path:
            return False, "当前主关卡尚未保存（处于 Untitled 状态），请先按 Ctrl+S 保存主关卡后再执行！"

        std_dirs = self.detect_project_standard_folders()
        target_light_dir = light_dir.strip().rstrip('/') if light_dir.strip() else std_dirs["light_dir"]
        target_scence_dir = scence_dir.strip().rstrip('/') if scence_dir.strip() else std_dirs["scence_dir"]

        if not self.asset_sub.does_directory_exist(target_light_dir):
            self.asset_sub.make_directory(target_light_dir)

        clean_prefix = prefix_str.strip()
        if clean_prefix and not clean_prefix.endswith("_"):
            clean_prefix += "_"

        existing_level_objs = {}
        try:
            for lvl in unreal.EditorLevelUtils.get_levels(world):
                if lvl and lvl.get_outer():
                    existing_level_objs[lvl.get_outer().get_name().lower()] = lvl
        except Exception:
            pass

        streaming_cls = getattr(unreal, "LevelStreamingAlwaysLoaded", unreal.LevelStreamingDynamic)
        created_or_loaded_map = {}
        final_mapping = {k: [] for k, _, _, _, _ in SUBLEVEL_ROLE_SPECS}

        for mounted_low, lvl_obj in existing_level_objs.items():
            real_n = lvl_obj.get_outer().get_name()
            if ("scence" in mounted_low or "scene" in mounted_low) and self._is_valid_sublevel_name(real_n) and real_n not in final_mapping["scence"]:
                final_mapping["scence"].append(real_n)

        if not final_mapping["scence"] and self.asset_sub.does_directory_exist(target_scence_dir):
            for ap in self.asset_sub.list_assets(target_scence_dir, recursive=True):
                if self._is_true_world_map_asset(ap):
                    pkg_p = ap.split('.')[0]
                    short_n = os.path.basename(pkg_p)
                    if short_n not in final_mapping["scence"]:
                        final_mapping["scence"].append(short_n)

        light_roles = [spec for spec in SUBLEVEL_ROLE_SPECS if spec[0] != "scence"]
        light_sublevel_names = []

        for role_key, base_suffix, _, _, _ in light_roles:
            sub_name = f"{clean_prefix}{base_suffix}"
            sub_pkg_path = f"{target_light_dir}/{sub_name}"
            light_sublevel_names.append(sub_name)

            if sub_name.lower() in existing_level_objs or self.asset_sub.does_asset_exist(sub_pkg_path):
                created_or_loaded_map[role_key] = (sub_name, existing_level_objs.get(sub_name.lower()))
                final_mapping[role_key].append(sub_name)
                continue

            try:
                lvl_stream = unreal.EditorLevelUtils.create_new_streaming_level(streaming_cls, sub_pkg_path, False)
                if lvl_stream and hasattr(lvl_stream, "set_folder_path"):
                    try:
                        lvl_stream.set_folder_path(unreal.Name("Light"))
                    except Exception:
                        pass
                created_or_loaded_map[role_key] = (sub_name, lvl_stream)
            except Exception as e:
                print(f"[RenderLayer] 创建子关卡 {sub_name} 提示: {e}")

            final_mapping[role_key].append(sub_name)

        self.organize_sublevels_in_levels_panel(light_sublevel_names)

        moved_counts = {spec[0]: 0 for spec in light_roles}
        if auto_move_lights_and_fog:
            level_obj_by_role = {}
            try:
                for lvl in unreal.EditorLevelUtils.get_levels(world):
                    if lvl and lvl.get_outer():
                        short_n = lvl.get_outer().get_name().lower()
                        for role_key, base_suffix, _, _, _ in light_roles:
                            if short_n == f"{clean_prefix}{base_suffix}".lower():
                                level_obj_by_role[role_key] = lvl
            except Exception:
                pass

            persistent_name = world.get_name().lower()
            actors_by_role = {spec[0]: [] for spec in light_roles}

            for act in self.actor_sub.get_all_level_actors():
                outer_lvl = act.get_outer()
                if not outer_lvl or not outer_lvl.get_outer():
                    continue
                if outer_lvl.get_outer().get_name().lower() != persistent_name:
                    continue

                role = self._classify_single_actor_role(act)
                if role in actors_by_role:
                    actors_by_role[role].append(act)

            for role_key, act_list in actors_by_role.items():
                if not act_list:
                    continue
                target_info = created_or_loaded_map.get(role_key)
                target_stream_or_lvl = (target_info[1] if target_info else None) or level_obj_by_role.get(role_key)
                if target_stream_or_lvl:
                    try:
                        moved_num = unreal.EditorLevelUtils.move_actors_to_level(act_list, target_stream_or_lvl)
                        moved_counts[role_key] = int(moved_num) if moved_num is not None else len(act_list)
                    except Exception as e:
                        print(f"[RenderLayer] 自动移动 {role_key} Actor 提示: {e}")

        self.save_sublevel_mapping_for_current_world(final_mapping)

        if auto_move_lights_and_fog:
            lines = [f"• {clean_prefix}{sfx:<14} : 已归入 Levels 面板 [Light] 文件夹，移入 {moved_counts[rk]} 个 Actor" for rk, sfx, _, _, _ in light_roles]
            lines.append("• scence (场景模型) : 已按规范跳过移动，0 卡顿！")
            lines.append("• PostProcessVolume / 相机 : 已按规范保留在主渲染关卡！")
            msg = "灯光/雾子关卡创建与自动归类完成（已全部收纳至 Levels 面板 [Light] 文件夹）：\n\n" + "\n".join(lines)
        else:
            lines = [f"• {clean_prefix}{sfx:<14} (已归入 Levels 面板 [Light] 文件夹)  ➔  {desc}" for _, sfx, _, _, desc in light_roles]
            msg = "灯光/雾子关卡就绪（已全部收纳至 Levels 面板 [Light] 文件夹）：\n\n" + "\n".join(lines)

        return True, msg

    def save_sublevel_mapping_for_current_world(self, custom_mapping_dict):
        world = unreal.EditorLevelLibrary.get_editor_world()
        world_name = world.get_name() if world else "DefaultWorld"
        cfg = self.load_config()
        if "world_sublevel_map" not in cfg:
            cfg["world_sublevel_map"] = {}
        cfg["world_sublevel_map"][world_name] = custom_mapping_dict
        self.save_config(cfg)

    # =========================================================================
    # 3. 完整保留原版 CVarPresets 4 参数清洗逻辑 (修复空指针崩溃 + 严格只留 4 个参数)
    # =========================================================================
    def _get_existing_command_names_in_asset(self, asset_obj, cvar_lib=None):
        cmd_names = []
        if not asset_obj:
            return cmd_names

        if cvar_lib and hasattr(cvar_lib, "get_list_of_commands_from_preset"):
            try:
                raw_list = cvar_lib.get_list_of_commands_from_preset(asset_obj) or []
                for item in raw_list:
                    parts = str(item).strip().split()
                    if parts:
                        k = parts[0]
                        if k and k not in cmd_names:
                            cmd_names.append(k)
            except Exception:
                pass

        if hasattr(asset_obj, "get_saved_commands_as_string_array"):
            try:
                arr = asset_obj.get_saved_commands_as_string_array(False) or []
                for s in arr:
                    parts = str(s).strip().split()
                    if parts:
                        k = parts[0]
                        if k and k not in cmd_names:
                            cmd_names.append(k)
            except Exception:
                pass

        return cmd_names

    def _is_cvar_asset_exact_match(self, asset_obj, expected_dict, cvar_lib=None):
        """严格校验资产内是否【只有】指定的 4 个参数，且每个参数的数值也完全一致"""
        if not asset_obj:
            return False
        cmd_names = self._get_existing_command_names_in_asset(asset_obj, cvar_lib)
        if len(cmd_names) != len(expected_dict) or set(cmd_names) != set(expected_dict.keys()):
            return False

        if hasattr(asset_obj, "get_saved_commands_as_string_array"):
            try:
                arr = asset_obj.get_saved_commands_as_string_array(False) or []
                if len(arr) != len(expected_dict):
                    return False
                parsed_map = {}
                for s in arr:
                    parts = str(s).strip().split()
                    if len(parts) >= 2:
                        parsed_map[parts[0]] = parts[1]
                for k, v in expected_dict.items():
                    if parsed_map.get(k) != str(v):
                        return False
            except Exception:
                return False
        return True

    def get_or_create_cvar_presets(self):
        cvar_cls = getattr(unreal, "ConsoleVariablesAsset", None)
        cvar_factory_cls = getattr(unreal, "ConsoleVariablesEditorFactory", None)
        cvar_lib = getattr(unreal, "ConsoleVariablesEditorFunctionLibrary", None)
        if not cvar_cls:
            return {}

        std_dirs = self.detect_project_standard_folders()
        target_folder = std_dirs["cvar_dir"]  # /Game/{Project}/Shot/CVarPresets
        if not self.asset_sub.does_directory_exist(target_folder):
            self.asset_sub.make_directory(target_folder)

        specs = [
            ("heightfog", "CVar_HeightFog_Only",  CVAR_HEIGHTFOG_LAYER),
            ("fog",       "CVar_EasyFog_Only",    CVAR_EASYFOG_LAYER),
            ("restore",   "CVar_Default_Restore", CVAR_DEFAULT_RESTORE),
        ]

        expected_keys_set = {"ShowFlag.Diffuse", "ShowFlag.Specular", "ShowFlag.Translucency", "ShowFlag.Fog"}
        created_assets = {}
        any_written = False

        for key, asset_name, cvar_dict in specs:
            pkg_path = f"{target_folder}/{asset_name}"
            if self.asset_sub.does_asset_exist(pkg_path):
                asset_obj = self.asset_sub.load_asset(pkg_path)
            elif cvar_factory_cls:
                try:
                    asset_obj = self.asset_tools.create_asset(asset_name, target_folder, cvar_cls, cvar_factory_cls())
                except Exception:
                    asset_obj = None
            else:
                asset_obj = None

            if not asset_obj:
                continue

            is_clean_and_exact = self._is_cvar_asset_exact_match(asset_obj, cvar_dict, cvar_lib)

            if not is_clean_and_exact and cvar_lib:
                try:
                    existing_cmd_names = self._get_existing_command_names_in_asset(asset_obj, cvar_lib)

                    # 1. 先把当前 CVar 编辑器内存列表同步到 asset_obj 以提取所有潜在污染变量名
                    if hasattr(cvar_lib, "copy_current_list_to_asset"):
                        cvar_lib.copy_current_list_to_asset(asset_obj)

                    all_polluted = self._get_existing_command_names_in_asset(asset_obj, cvar_lib)
                    cmds_to_purge = set(all_polluted) | set(existing_cmd_names) | set(POLLUTED_MRQ_CVARS) | expected_keys_set

                    # 2. 清空 CVar 编辑器当前预设列表中的所有旧变量与污染变量
                    if hasattr(cvar_lib, "remove_command_from_current_preset"):
                        for bad_cmd in cmds_to_purge:
                            if bad_cmd:
                                try:
                                    cvar_lib.remove_command_from_current_preset(str(bad_cmd).strip())
                                except Exception:
                                    pass

                    # 同时将 asset_obj 自身的数据清空
                    if hasattr(asset_obj, "replace_saved_commands"):
                        try:
                            asset_obj.replace_saved_commands([])
                        except Exception:
                            pass

                    # 3. 严格按官方两步法写入 4 个雾气分层参数：
                    #    第一步：先通过 set_console_variable_by_name_int 设置变量当前值
                    #    第二步：调用 add_validated_command_to_current_preset(只传变量名 cv_k！绝不带空格和数值，防止空指针崩溃)
                    for cv_k, cv_v in cvar_dict.items():
                        cmd_key = str(cv_k).strip()
                        val_int = int(cv_v)
                        if hasattr(cvar_lib, "set_console_variable_by_name_int"):
                            cvar_lib.set_console_variable_by_name_int(cmd_key, val_int)
                        elif hasattr(cvar_lib, "set_console_variable_by_name_string"):
                            cvar_lib.set_console_variable_by_name_string(cmd_key, str(val_int))

                        if hasattr(cvar_lib, "add_validated_command_to_current_preset"):
                            cvar_lib.add_validated_command_to_current_preset(cmd_key)

                    # 4. 将只含 4 个参数的列表拷贝写入 asset_obj
                    if hasattr(cvar_lib, "copy_current_list_to_asset"):
                        cvar_lib.copy_current_list_to_asset(asset_obj)

                    # 5. 二次白名单强校验：直接从 asset_obj 本体剔除任何非 4 个 ShowFlag 的残留项
                    final_cmds = self._get_existing_command_names_in_asset(asset_obj, cvar_lib)
                    for cmd_n in final_cmds:
                        if cmd_n not in expected_keys_set:
                            if hasattr(asset_obj, "remove_console_variable"):
                                try:
                                    asset_obj.remove_console_variable(str(cmd_n).strip())
                                except Exception:
                                    pass
                            if hasattr(cvar_lib, "remove_command_from_current_preset"):
                                try:
                                    cvar_lib.remove_command_from_current_preset(str(cmd_n).strip())
                                except Exception:
                                    pass

                    if hasattr(asset_obj, "set_variable_collection_description"):
                        desc_str = ", ".join([f"{k}={v}" for k, v in cvar_dict.items()])
                        asset_obj.set_variable_collection_description(f"[{asset_name}] {desc_str}")

                    self.asset_sub.save_asset(pkg_path, only_if_is_dirty=False)
                    any_written = True
                except Exception as e:
                    print(f"[RenderLayer] 清洗并写入 CVar 预设参数提示 ({asset_name}): {e}")

            created_assets[key] = asset_obj

        # 6. 结束后将当前编辑器视口的 4 个 ShowFlag 还原为默认状态 (2)
        if any_written:
            try:
                world = unreal.EditorLevelLibrary.get_editor_world()
                for def_k, def_v in CVAR_DEFAULT_RESTORE.items():
                    if cvar_lib and hasattr(cvar_lib, "set_console_variable_by_name_int"):
                        cvar_lib.set_console_variable_by_name_int(str(def_k), int(def_v))
                    unreal.SystemLibrary.execute_console_command(world, f"{def_k} {def_v}")
            except Exception:
                pass

        return created_assets

    def get_or_create_global_emiss_mpc(self):
        std_dirs = self.detect_project_standard_folders()
        mpc_folder = std_dirs["collection_dir"]
        if not self.asset_sub.does_directory_exist(mpc_folder):
            self.asset_sub.make_directory(mpc_folder)

        mpc_name = "MPC_Global_Emiss"
        mpc_path = f"{mpc_folder}/{mpc_name}"

        is_new = False
        if self.asset_sub.does_asset_exist(mpc_path):
            mpc_asset = self.asset_sub.load_asset(mpc_path)
        else:
            mpc_factory = unreal.MaterialParameterCollectionFactoryNew()
            mpc_asset = self.asset_tools.create_asset(
                mpc_name, mpc_folder, unreal.MaterialParameterCollection, mpc_factory
            )
            is_new = True

        if not mpc_asset:
            return None

        try:
            scalar_params = list(mpc_asset.get_editor_property("scalar_parameters") or [])
            existing_names = {str(p.get_editor_property("parameter_name")).lower() for p in scalar_params}
            if "emiss" not in existing_names:
                p_emiss = unreal.CollectionScalarParameter()
                p_emiss.set_editor_property("parameter_name", unreal.Name("Emiss"))
                p_emiss.set_editor_property("default_value", 1.0)
                scalar_params.append(p_emiss)
                mpc_asset.set_editor_property("scalar_parameters", scalar_params)
                self.asset_sub.save_asset(mpc_path, only_if_is_dirty=True)
            elif is_new:
                self.asset_sub.save_asset(mpc_path, only_if_is_dirty=True)
        except Exception:
            pass

        return mpc_asset

    def hide_alignment_actors_in_game(self):
        try:
            for act in self.actor_sub.get_all_level_actors():
                label = act.get_actor_label()
                if "ImagePlate" in label or "SM_Ref" in label:
                    act.set_actor_hidden_in_game(True)
        except Exception:
            pass

    def strip_media_and_cvar_tracks(self, level_seq):
        cvar_track_cls = getattr(unreal, "MovieSceneCVarTrack", None)
        try:
            for track in list(level_seq.get_tracks()):
                if isinstance(track, unreal.MovieSceneMediaTrack):
                    level_seq.remove_track(track)
                elif cvar_track_cls and isinstance(track, cvar_track_cls):
                    level_seq.remove_track(track)
        except Exception:
            pass

    def inject_level_visibility_track(self, level_seq, visible_levels, all_levels, start_frame, end_frame_exclusive):
        try:
            for track in list(level_seq.get_tracks()):
                if isinstance(track, unreal.MovieSceneLevelVisibilityTrack):
                    level_seq.remove_track(track)

            vis_clean = [v for v in visible_levels if v and self._is_valid_sublevel_name(v)]
            vis_clean = list(dict.fromkeys(vis_clean))

            hidden_levels = [lvl for lvl in all_levels if lvl and self._is_valid_sublevel_name(lvl) and lvl not in vis_clean]
            if not vis_clean and not hidden_levels:
                return False

            vis_track = level_seq.add_track(unreal.MovieSceneLevelVisibilityTrack)
            if not vis_track:
                return False

            warmup_start_f = int(start_frame) - 100

            if vis_clean:
                sec_vis = vis_track.add_section()
                sec_vis.set_row_index(0)
                sec_vis.set_range(warmup_start_f, int(end_frame_exclusive))
                sec_vis.set_visibility(unreal.LevelVisibility.VISIBLE)
                sec_vis.set_level_names([unreal.Name(n) for n in vis_clean])

            if hidden_levels:
                sec_hid = vis_track.add_section()
                sec_hid.set_row_index(1)
                sec_hid.set_range(warmup_start_f, int(end_frame_exclusive))
                sec_hid.set_visibility(unreal.LevelVisibility.HIDDEN)
                sec_hid.set_level_names([unreal.Name(n) for n in hidden_levels])

            return True
        except Exception as e:
            print(f"[RenderLayer] 注入关卡显隐轨道提示 ({level_seq.get_name()}): {e}")
            return False

    def inject_mpc_control_track(self, level_seq, mpc_asset, emiss_val, start_frame, end_frame_exclusive):
        if not mpc_asset:
            return False
        try:
            for track in list(level_seq.get_tracks()):
                if isinstance(track, unreal.MovieSceneMaterialParameterCollectionTrack):
                    level_seq.remove_track(track)

            mpc_track = level_seq.add_track(unreal.MovieSceneMaterialParameterCollectionTrack)
            mpc_track.set_editor_property("mpc", mpc_asset)
            sec = mpc_track.add_section()
            warmup_start_f = int(start_frame) - 100
            sec.set_range(warmup_start_f, int(end_frame_exclusive))

            sec.add_scalar_parameter_key(unreal.Name("Emiss"), unreal.FrameNumber(int(start_frame)), float(emiss_val))
            return True
        except Exception as e:
            print(f"[RenderLayer] 注入 MPC 轨道提示 ({level_seq.get_name()}): {e}")
            return False

    def inject_sequencer_cvar_track(self, level_seq, cvar_asset_obj, start_frame, end_frame_exclusive):
        if not cvar_asset_obj:
            return False

        cvar_track_cls = getattr(unreal, "MovieSceneCVarTrack", None)
        if not cvar_track_cls:
            return False

        try:
            for track in list(level_seq.get_tracks()):
                if isinstance(track, cvar_track_cls):
                    level_seq.remove_track(track)

            cvar_track = level_seq.add_track(cvar_track_cls)
            sec = cvar_track.add_section()
            warmup_start_f = int(start_frame) - 100
            sec.set_range(warmup_start_f, int(end_frame_exclusive))

            col_item = unreal.MovieSceneConsoleVariableCollection()
            col_item.set_editor_property("interface", cvar_asset_obj)
            try:
                col_item.set_editor_property("only_include_checked", False)
            except Exception:
                pass
            sec.set_editor_property("console_variable_collections", [col_item])
            return True
        except Exception as e:
            print(f"[RenderLayer] 挂载 ConsoleVariableCollections 提示 ({level_seq.get_name()}): {e}")
            return False

    def list_all_mrq_config_assets(self):
        found_paths = []

        try:
            all_assets = self.asset_reg.get_all_assets()
            for ad in all_assets:
                cls_str = str(getattr(ad, "asset_class_path", getattr(ad, "asset_class", ""))).lower()
                a_name = str(ad.asset_name).lower()
                if ("moviepipeline" in cls_str and "config" in cls_str) or "renderset" in a_name:
                    pkg_p = str(ad.package_name)
                    if pkg_p not in found_paths and not pkg_p.startswith("/Engine/"):
                        found_paths.append(pkg_p)
        except Exception:
            pass

        search_roots = [("/Game", os.path.normpath(unreal.Paths.project_content_dir()).replace('\\', '/'))]
        plugins_dir = os.path.normpath(unreal.Paths.project_plugins_dir()).replace('\\', '/')
        if os.path.exists(plugins_dir):
            for p_folder in os.listdir(plugins_dir):
                p_content = os.path.join(plugins_dir, p_folder, "Content").replace('\\', '/')
                if os.path.isdir(p_content):
                    search_roots.append((f"/{p_folder}", p_content))

        for mount_prefix, disk_root in search_roots:
            if not os.path.exists(disk_root):
                continue
            for root, dirs, files in os.walk(disk_root):
                for f in files:
                    if f.lower().endswith(".uasset") and "renderset" in f.lower():
                        short_name = os.path.splitext(f)[0]
                        rel_dir = os.path.relpath(root, disk_root).replace('\\', '/')
                        pkg_path = f"{mount_prefix}/{short_name}" if rel_dir == "." else f"{mount_prefix}/{rel_dir}/{short_name}"
                        if pkg_path not in found_paths:
                            found_paths.append(pkg_path)

        found_paths.sort()
        return found_paths

    def _classify_preset_key_by_name(self, asset_name_str):
        low = os.path.basename(str(asset_name_str).strip()).lower()
        if "actor" in low:
            return "id_actor"
        if "material" in low or "_mat" in low:
            return "id_material"
        if "renderset" in low:
            return "beauty"
        return None

    def find_mrq_presets(self, force_rescan=False, explicit_paths_override=None):
        cfg = self.load_config()
        all_cand_paths = self.list_all_mrq_config_assets()

        presets = {
            "beauty": None,
            "id_actor": None,
            "id_material": None
        }

        if explicit_paths_override is not None:
            saved_presets = {}
            for k in ["beauty", "id_actor", "id_material"]:
                sp = str(explicit_paths_override.get(k, "")).strip()
                if sp and sp.startswith("/") and self.asset_sub.does_asset_exist(sp):
                    loaded = self.asset_sub.load_asset(sp)
                    if loaded:
                        presets[k] = loaded
                        saved_presets[k] = sp
                else:
                    saved_presets[k] = ""
            cfg["mrq_preset_paths"] = saved_presets
            self.save_config(cfg)
            return presets, all_cand_paths

        has_saved_dict = "mrq_preset_paths" in cfg and isinstance(cfg.get("mrq_preset_paths"), dict)
        saved_presets = {} if force_rescan else dict(cfg.get("mrq_preset_paths", {}))

        for k in ["beauty", "id_actor", "id_material"]:
            if not force_rescan and has_saved_dict and k in saved_presets:
                sp = str(saved_presets.get(k, "")).strip()
                if sp and sp.startswith("/") and self.asset_sub.does_asset_exist(sp):
                    presets[k] = self.asset_sub.load_asset(sp)
                else:
                    presets[k] = None
            else:
                for pkg_p in all_cand_paths:
                    role_k = self._classify_preset_key_by_name(pkg_p)
                    if role_k == k and presets[k] is None:
                        loaded = self.asset_sub.load_asset(pkg_p)
                        if loaded:
                            presets[k] = loaded
                            saved_presets[k] = pkg_p
                            break

        cfg["mrq_preset_paths"] = saved_presets
        self.save_config(cfg)
        return presets, all_cand_paths

    def resolve_preset_key_for_sequence(self, seq_name_str, default_key="beauty"):
        low = str(seq_name_str).strip().lower()
        if "id_actor" in low or "actor_id" in low or low.endswith("_actor"):
            return "id_actor"
        if "id_material" in low or "material_id" in low or low.endswith("_material"):
            return "id_material"
        return default_key

    def prepare_and_save_preset_assets(self, presets_dict, output_dir):
        norm_out = os.path.normpath(output_dir).replace('\\', '/')
        for key, preset_asset in presets_dict.items():
            if not preset_asset:
                continue
            try:
                p_out = preset_asset.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
                if p_out:
                    p_out.output_directory = unreal.DirectoryPath(norm_out)
                    p_out.file_name_format = "{sequence_name}.{frame_number}"
                    p_out.zero_pad_frame_numbers = 4
                    if hasattr(p_out, "use_custom_playback_range"):
                        p_out.use_custom_playback_range = False
            except Exception:
                pass

            try:
                game_ovr = preset_asset.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
                if game_ovr:
                    if hasattr(game_ovr, "set_is_enabled"):
                        game_ovr.set_is_enabled(True)
                    if hasattr(game_ovr, "flush_level_streaming"):
                        game_ovr.flush_level_streaming = True
                    if hasattr(game_ovr, "flush_grass_streaming"):
                        game_ovr.flush_grass_streaming = True
            except Exception:
                pass

            try:
                aa_setting = preset_asset.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
                if aa_setting:
                    if hasattr(aa_setting, "set_is_enabled"):
                        aa_setting.set_is_enabled(True)
                    cur_warmup = int(getattr(aa_setting, "engine_warm_up_count", 0))
                    if cur_warmup < 32:
                        aa_setting.engine_warm_up_count = 32
                    if hasattr(aa_setting, "render_warm_up_frames"):
                        aa_setting.render_warm_up_frames = True
            except Exception:
                pass

            try:
                if hasattr(preset_asset, "get_user_settings"):
                    for s_item in preset_asset.get_user_settings():
                        if isinstance(s_item, unreal.MoviePipelineConsoleVariableSetting):
                            if hasattr(s_item, "console_variable_presets"):
                                s_item.console_variable_presets = []
            except Exception:
                pass

            try:
                pkg_p = preset_asset.get_path_name().split('.')[0]
                self.asset_sub.save_asset(pkg_p, only_if_is_dirty=True)
            except Exception:
                pass

    def apply_preset_to_job_strictly(self, job, preset_asset, output_dir):
        """
        多镜头输出路径隔离核心：
        通过 job.get_configuration().copy_from(preset_asset) 将预设内的全部渲染设置
        深拷贝到当前 Job 自身的独立 Configuration 中，再单独写入当前镜头的 output_directory。
        """
        norm_out = os.path.normpath(output_dir).replace('\\', '/')
        try:
            config = job.get_configuration()
            if preset_asset and config and hasattr(config, "copy_from"):
                config.copy_from(preset_asset)
            if config:
                out_setting = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
                if out_setting:
                    out_setting.output_directory = unreal.DirectoryPath(norm_out)
                    out_setting.file_name_format = "{sequence_name}.{frame_number}"
                    out_setting.zero_pad_frame_numbers = 4
                    if hasattr(out_setting, "use_custom_playback_range"):
                        out_setting.use_custom_playback_range = False
        except Exception as e:
            print(f"[RenderLayer] 绑定独立预设配置提示: {e}")

    def _remove_only_shot_jobs_from_queue(self, queue, ep, shot, master_seq_name="", shot_folder=""):
        """
        精准清理：只从 MRQ 队列中移除属于当前镜头 (如 cam2180) 的旧 Job，
        100% 保留队列中已经添加的其他镜头 (如 cam2220)！
        """
        if not queue:
            return 0
        removed_count = 0
        shot_tag = f"cam{shot}".lower()
        master_low = str(master_seq_name).strip().lower()
        folder_low = str(shot_folder).strip().lower()

        try:
            for j in list(queue.get_jobs()):
                j_name = str(j.job_name).strip().lower()
                seq_str = str(j.sequence.asset_path_name if hasattr(j.sequence, "asset_path_name") else j.sequence).lower()
                is_same_shot = False
                if shot_tag in j_name or (master_low and j_name == master_low):
                    is_same_shot = True
                elif folder_low and folder_low in seq_str:
                    is_same_shot = True
                elif f"/shot_{shot}/" in seq_str or f"/{shot_tag}" in seq_str:
                    is_same_shot = True

                if is_same_shot:
                    queue.delete_job(j)
                    removed_count += 1
        except Exception as e:
            print(f"[RenderLayer] 清理当前镜头旧队列项提示: {e}")
        return removed_count

    def start_mrq_local_render_directly(self):
        queue = self.mrq_sub.get_queue()
        if not queue or len(queue.get_jobs()) == 0:
            return False, "当前 MRQ 渲染队列为空！请先点击底部绿色按钮生成并加入队列。"
        if self.mrq_sub.is_rendering():
            return False, "当前 Movie Render Queue 正在渲染中，请等待完成！"

        all_dirs = _extract_all_output_dirs_from_active_queue(only_enabled=True)
        sys._LL_LAST_RENDER_OUT_DIRS = all_dirs
        sys._LL_POPPED_DIRS_IN_SESSION = set()
        out_dir = all_dirs[-1] if all_dirs else ""
        ensure_mrq_render_finish_monitor_active(out_dir)

        try:
            executor = self.mrq_sub.render_queue_with_executor(unreal.MoviePipelinePIEExecutor)
            if executor:
                # 1. 绑定单任务完成回调：每个镜头 Sequence 渲染完成时，立即弹出该镜头的输出文件夹
                if hasattr(executor, "on_individual_job_finished_delegate"):
                    def _on_single_job_done(job_obj, success):
                        try:
                            j_dir = _extract_job_output_dir(job_obj)
                            if j_dir and os.path.exists(j_dir):
                                popped = getattr(sys, "_LL_POPPED_DIRS_IN_SESSION", set())
                                if j_dir not in popped:
                                    popped.add(j_dir)
                                    sys._LL_POPPED_DIRS_IN_SESSION = popped
                                    open_folder_in_explorer(j_dir)
                        except Exception:
                            pass

                    try:
                        executor.on_individual_job_finished_delegate.add_callable(_on_single_job_done)
                    except Exception:
                        pass

                # 2. 绑定全部完成回调：兜底确保队列里所有已渲染镜头的输出目录均已弹出
                if hasattr(executor, "on_executor_finished_delegate"):
                    def _on_exec_done(exec_obj, success):
                        sys._LL_WAS_MRQ_RENDERING = False
                        popped = getattr(sys, "_LL_POPPED_DIRS_IN_SESSION", set())
                        target_dirs = _extract_all_output_dirs_from_active_queue() or getattr(sys, "_LL_LAST_RENDER_OUT_DIRS", [])
                        for td in target_dirs:
                            if td and td not in popped and os.path.exists(td):
                                popped.add(td)
                                open_folder_in_explorer(td)
                        sys._LL_POPPED_DIRS_IN_SESSION = popped

                    try:
                        executor.on_executor_finished_delegate.add_callable(_on_exec_done)
                    except Exception:
                        pass
            return True, "已成功启动 Movie Render Queue 本地渲染！每个镜头渲染完成后将自动弹出对应的输出文件夹。"
        except Exception as e:
            return False, f"启动渲染异常: {e}"

    # =========================================================================
    # 5. 与 LiangLiangUECamWorkflow 深度联通的服务器路径检测与版本精准控制
    # =========================================================================
    def _strip_publish_or_version_suffix(self, path_str):
        """将 .../ue/publish/v001/render 或 .../ue/publish 还原为干净的 .../ue 根目录"""
        if not path_str:
            return ""
        norm_p = os.path.normpath(str(path_str).strip()).replace('\\', '/').rstrip('/')
        low_p = norm_p.lower()
        if "/publish/" in low_p:
            idx = low_p.rfind("/publish/")
            return norm_p[:idx]
        if low_p.endswith("/publish"):
            return os.path.dirname(norm_p).replace('\\', '/')
        return norm_p

    def _derive_ue_dir_from_any_disk_path(self, raw_disk_path, ep, shot):
        """从 FBX 路径、背景序列路径或任意镜头目录智能推导 .../epXX/shot/ue 目录"""
        if not raw_disk_path:
            return ""
        clean_p = os.path.normpath(str(raw_disk_path).strip()).replace('\\', '/')
        if os.path.isfile(clean_p) or clean_p.lower().endswith(".fbx"):
            chk = os.path.dirname(clean_p)
        else:
            chk = clean_p.rstrip('/')

        chk = self._strip_publish_or_version_suffix(chk)
        if not os.path.exists(chk):
            return ""

        if os.path.basename(chk).lower() == "ue":
            return chk

        cur = chk
        shot_dir_cand = ""
        for _ in range(6):
            base_low = os.path.basename(cur).lower()
            if base_low == "ue":
                return cur
            if os.path.exists(os.path.join(cur, "ue")):
                return os.path.join(cur, "ue").replace('\\', '/')
            if base_low in (str(shot).lower(), f"shot_{shot}".lower(), f"{ep.lower()}_{shot}".lower()):
                shot_dir_cand = cur
            if base_low in ("cam", "camera", "maya", "fbx", "export", "workarea", "plate", "plates", "bg"):
                parent_d = os.path.dirname(cur).replace('\\', '/')
                if parent_d and parent_d != cur:
                    if os.path.basename(parent_d).lower() == "ue":
                        return parent_d
                    shot_dir_cand = parent_d
            parent = os.path.dirname(cur).replace('\\', '/')
            if not parent or parent == cur:
                break
            cur = parent

        if shot_dir_cand and os.path.exists(shot_dir_cand):
            return os.path.join(shot_dir_cand, "ue").replace('\\', '/')

        if re.search(r'/ep\d+/\d{3,5}', chk, re.IGNORECASE):
            m = re.search(r'^(.*?/ep\d+/\d{3,5})', chk, re.IGNORECASE)
            if m:
                return f"{m.group(1)}/ue"

        return ""

    def detect_linked_ue_output_root(self, ep, shot, master_seq=None):
        """四级联动检测当前镜头的 UE 渲染输出根目录 (不弹窗)"""
        cfg = self.load_config()
        shot_key = f"{ep.upper()}_{shot}"

        # 1. 优先读取已直接绑定的 shot_ue_root_map
        ue_root_map = cfg.get("shot_ue_root_map", {})
        saved_ue_dir = str(ue_root_map.get(shot_key, "")).strip()
        if saved_ue_dir:
            norm_s = self._strip_publish_or_version_suffix(saved_ue_dir)
            parent_check = os.path.dirname(norm_s) if not os.path.exists(norm_s) else norm_s
            if os.path.exists(parent_check):
                return norm_s

        # 2. 读取 LiangLiangUECamWorkflow 保存的 shot_disk_map
        shot_map = cfg.get("shot_disk_map", {})
        fbx_path = str(shot_map.get(shot_key, "")).strip()
        if not fbx_path:
            for k, v in shot_map.items():
                if str(k).upper().endswith(f"_{shot}") and v:
                    fbx_path = str(v).strip()
                    break

        if fbx_path:
            derived = self._derive_ue_dir_from_any_disk_path(fbx_path, ep, shot)
            if derived:
                self.save_linked_ue_output_root(ep, shot, derived)
                return derived

        # 3. 从母版序列同目录的 bg/epXX_camXXXX_bg (ImgMediaSource) 提取路径
        if master_seq:
            try:
                seq_pkg = master_seq.get_path_name().split('.')[0]
                shot_folder = os.path.dirname(seq_pkg)
                bg_asset_path = f"{shot_folder}/bg/{ep.lower()}_cam{shot}_bg"
                if self.asset_sub.does_asset_exist(bg_asset_path):
                    img_src = self.asset_sub.load_asset(bg_asset_path)
                    if img_src:
                        seq_p_struct = img_src.get_editor_property("sequence_path")
                        raw_bg_p = str(seq_p_struct.path).strip() if seq_p_struct else ""
                        if raw_bg_p:
                            derived = self._derive_ue_dir_from_any_disk_path(raw_bg_p, ep, shot)
                            if derived:
                                self.save_linked_ue_output_root(ep, shot, derived)
                                return derived
            except Exception:
                pass

        # 4. 从 last_ue_root_dir 或 last_fbx_path 跨镜头自动替换 ep 与 shot
        for fallback_raw in (cfg.get("last_ue_root_dir", ""), cfg.get("last_fbx_path", "")):
            if not fallback_raw:
                continue
            cand_dir = self._derive_ue_dir_from_any_disk_path(fallback_raw, ep, shot) or self._strip_publish_or_version_suffix(fallback_raw)
            if cand_dir:
                replaced = re.sub(r'/ep\d+/\d{3,5}/ue$', f"/{ep.lower()}/{shot}/ue", cand_dir, flags=re.IGNORECASE)
                proj_parent = os.path.dirname(os.path.dirname(os.path.dirname(replaced)))
                if os.path.exists(proj_parent):
                    self.save_linked_ue_output_root(ep, shot, replaced)
                    return replaced

        return ""

    def save_linked_ue_output_root(self, ep, shot, ue_root_dir):
        """将当前镜头的 ue 输出根目录永久保存到 UECamWorkflowConfig.json，避免重复弹窗"""
        if not ue_root_dir:
            return
        norm_u = self._strip_publish_or_version_suffix(ue_root_dir)
        cfg = self.load_config()
        if "shot_ue_root_map" not in cfg or not isinstance(cfg.get("shot_ue_root_map"), dict):
            cfg["shot_ue_root_map"] = {}
        shot_key = f"{ep.upper()}_{shot}"
        cfg["shot_ue_root_map"][shot_key] = norm_u
        cfg["last_ue_root_dir"] = norm_u
        self.save_config(cfg)

    def _dir_contains_rendered_images(self, check_dir):
        """递归检查指定版本目录下是否已存在渲染出的图片文件 (.exr/.png/.jpg 等)"""
        if not check_dir or not os.path.exists(check_dir):
            return False
        try:
            for root, _, files in os.walk(check_dir):
                for f in files:
                    if f.lower().endswith(RENDER_IMG_EXTENSIONS):
                        return True
        except Exception:
            pass
        return False

    def resolve_and_create_publish_render_dir(self, ep, shot, custom_ue_dir="", force_new_version=True, seq_names_to_clean=None, master_seq=None):
        """
        精准版本控制核心算法：
        - 扫描 publish/ 下所有 vXXX 目录，区分【已有渲染图的版本 (populated_versions)】与【未渲染的空版本目录 (empty_versions)】；
        - 当选择【直接替换当前版本 (force_new_version=False)】时：
          自动清理掉排在后面的未渲染空版本文件夹 (如之前点递增产生但没渲染的空 v002)，
          100% 锁定回已经有图的当前版本 (如 v001)，且【不删除已有的渲染图素材】，待真正点击渲染时由 UE 直接覆盖！
        - 当选择【自动递增新版本 (force_new_version=True)】时：
          基于已有渲染图的最高版本 (如 v001) 递增为 v002；若 v001 尚无图片则保持 v001。
        """
        ue_root_dir = ""

        if custom_ue_dir and str(custom_ue_dir).strip():
            raw_c = self._strip_publish_or_version_suffix(custom_ue_dir)
            if re.search(r'/ep\d+/\d{3,5}/ue$', raw_c, re.IGNORECASE):
                raw_c = re.sub(r'/ep\d+/\d{3,5}/ue$', f"/{ep.lower()}/{shot}/ue", raw_c, flags=re.IGNORECASE)
            ue_root_dir = raw_c

        if not ue_root_dir:
            ue_root_dir = self.detect_linked_ue_output_root(ep, shot, master_seq=master_seq)

        if not ue_root_dir:
            import tkinter as tk
            from tkinter import filedialog
            chosen = filedialog.askdirectory(title=f"未检测到相机联动路径，请指定一次 Shot {shot} 的 ue 输出目录 (指定后将自动永久记住)")
            if not chosen:
                return ""
            ue_root_dir = self._strip_publish_or_version_suffix(chosen)

        self.save_linked_ue_output_root(ep, shot, ue_root_dir)

        if ue_root_dir.lower().endswith("/publish"):
            publish_dir = ue_root_dir
        elif os.path.basename(ue_root_dir).lower() in ("workarea", "export"):
            publish_dir = os.path.join(os.path.dirname(ue_root_dir), "publish").replace('\\', '/')
        else:
            publish_dir = os.path.join(ue_root_dir, "publish").replace('\\', '/')

        os.makedirs(publish_dir, exist_ok=True)

        existing_versions = []
        for d in os.listdir(publish_dir):
            full_d = os.path.join(publish_dir, d)
            if os.path.isdir(full_d):
                m = re.match(r'^v(\d+)$', d, re.IGNORECASE)
                if m:
                    ver_num = int(m.group(1))
                    has_imgs = self._dir_contains_rendered_images(full_d)
                    existing_versions.append((ver_num, d, has_imgs, full_d))

        if not existing_versions:
            target_v_str = "v001"
        else:
            existing_versions.sort(key=lambda x: x[0])
            populated_versions = [item for item in existing_versions if item[2]]

            if force_new_version:
                if populated_versions:
                    highest_pop_num = populated_versions[-1][0]
                    target_v_str = f"v{highest_pop_num + 1:03d}"
                else:
                    target_v_str = existing_versions[0][1]
            else:
                if populated_versions:
                    target_num, target_v_str, _, _ = populated_versions[-1]
                    for v_num, v_name, has_imgs, full_p in existing_versions:
                        if v_num > target_num and not has_imgs:
                            try:
                                shutil.rmtree(full_p, ignore_errors=True)
                            except Exception:
                                pass
                else:
                    target_num, target_v_str, _, _ = existing_versions[0]
                    for v_num, v_name, has_imgs, full_p in existing_versions[1:]:
                        if not has_imgs:
                            try:
                                shutil.rmtree(full_p, ignore_errors=True)
                            except Exception:
                                pass

        final_render_dir = os.path.join(publish_dir, target_v_str, "render").replace('\\', '/')
        os.makedirs(final_render_dir, exist_ok=True)
        return final_render_dir

    def requeue_existing_sequences(self, master_seq_path="", custom_publish_dir="",
                                   auto_increment_version=False, explicit_preset_paths=None):
        master_seq = self.get_active_master_sequence(master_seq_path, allow_content_browser_selection=True)
        if not master_seq:
            return False, "请先在顶部下拉框选择或在 Sequencer 中打开当前镜头的母版序列！"

        ep, shot = self.parse_ep_and_shot_from_seq(master_seq)
        master_pkg_path = master_seq.get_path_name().split('.')[0]
        shot_folder = os.path.dirname(master_pkg_path)
        start_f, end_f_inc, end_f_exc = self.get_exact_timeline_range(master_seq)

        multi_order = [
            ("env", "beauty"), ("key", "beauty"), ("sky", "beauty"),
            ("fill", "beauty"), ("heightfog", "beauty"), ("fog", "beauty"),
        ]
        found_multi = []
        for sfx, p_key in multi_order:
            p = f"{shot_folder}/cam{shot}_{sfx}"
            if self.asset_sub.does_asset_exist(p):
                seq_obj = self.asset_sub.load_asset(p)
                if seq_obj:
                    found_multi.append((seq_obj, p_key, sfx))

        queued_items = []
        if found_multi:
            queued_items.extend(found_multi)
        else:
            queued_items.append((master_seq, "beauty", "master"))

        emiss_p = f"{shot_folder}/cam{shot}_emiss"
        if self.asset_sub.does_asset_exist(emiss_p):
            emiss_obj = self.asset_sub.load_asset(emiss_p)
            if emiss_obj:
                queued_items.append((emiss_obj, "beauty", "emiss"))

        for id_sfx, p_key in [("ID_actor", "id_actor"), ("ID_material", "id_material")]:
            p = f"{shot_folder}/cam{shot}_{id_sfx}"
            if self.asset_sub.does_asset_exist(p):
                seq_obj = self.asset_sub.load_asset(p)
                if seq_obj:
                    queued_items.append((seq_obj, p_key, id_sfx))

        seq_names = [s.get_name() for s, _, _ in queued_items]
        render_out_dir = self.resolve_and_create_publish_render_dir(
            ep, shot, custom_ue_dir=custom_publish_dir,
            force_new_version=auto_increment_version, seq_names_to_clean=seq_names,
            master_seq=master_seq
        )
        if not render_out_dir:
            return False, "未选择有效的 publish 输出目录。"

        ensure_mrq_render_finish_monitor_active(render_out_dir)

        presets, _ = self.find_mrq_presets(force_rescan=False, explicit_paths_override=explicit_preset_paths)
        self.prepare_and_save_preset_assets(presets, render_out_dir)

        queue = self.mrq_sub.get_queue()
        self._remove_only_shot_jobs_from_queue(queue, ep, shot, master_seq.get_name(), shot_folder)

        world = unreal.EditorLevelLibrary.get_editor_world()
        world_soft_path = unreal.SoftObjectPath(world.get_path_name())

        bound_summary = []
        for seq_obj, default_pk, sfx in queued_items:
            self.ensure_sequence_camera_cut_bound_to_shot(seq_obj, shot, start_f, end_f_exc)

            job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
            final_pk = self.resolve_preset_key_for_sequence(seq_obj.get_name(), default_pk)
            target_preset = presets.get(final_pk)

            job.job_name = seq_obj.get_name()
            job.map = world_soft_path
            job.sequence = unreal.SoftObjectPath(seq_obj.get_path_name())
            self.apply_preset_to_job_strictly(job, target_preset, render_out_dir)

            p_name = target_preset.get_name() if target_preset else f"未绑定({final_pk})"
            bound_summary.append(f"• {seq_obj.get_name():<22}  ➔  预设: [{p_name}]")

        if hasattr(queue, "set_is_dirty"):
            queue.set_is_dirty(False)

        self.sync_content_browser_to_sequences([s for s, _, _ in queued_items], shot_folder=shot_folder)

        total_jobs_in_q = len(queue.get_jobs())
        ver_mode_str = "自动递增新版本 (若已有图则新建下一版)" if auto_increment_version else "直接替换当前版本 (保留现有图片，渲染时直接覆盖)"
        msg = (
            f"【Shot {shot} 现有 {len(queued_items)} 个序列已加入 MRQ 队列 (队列当前总计 {total_jobs_in_q} 个任务)】\n\n"
            f"• 版本策略: {ver_mode_str}\n"
            f"• 输出路径: {render_out_dir}\n"
            f"• 自动弹窗: 每个镜头渲染完成后将自动弹出对应的输出文件夹\n\n" + "\n".join(bound_summary)
        )
        return True, msg

    def execute_layer_split_and_queue(self, render_mode="multi", master_seq_path="",
                                      create_emiss_layer=False, custom_publish_dir="",
                                      auto_increment_version=True, clear_existing_queue=False,
                                      custom_sublevel_map=None, explicit_preset_paths=None):
        master_seq = self.get_active_master_sequence(master_seq_path, allow_content_browser_selection=True)
        if not master_seq:
            return False, "当前未打开任何母版镜头序列！\n请先在窗口顶部的【选择母版镜头 ▾】中选择一个主镜头序列。"

        is_single_mode = str(render_mode).strip().lower().startswith("single") or str(render_mode).strip() == "1"

        ep, shot = self.parse_ep_and_shot_from_seq(master_seq)
        master_pkg_path = master_seq.get_path_name().split('.')[0]
        master_seq_name = master_seq.get_name()
        shot_folder = os.path.dirname(master_pkg_path)

        start_f, end_f_inc, end_f_exc = self.get_exact_timeline_range(master_seq)
        self.hide_alignment_actors_in_game()

        all_levels, cls_lvls, _, _ = self.scan_mounted_and_folder_sublevels()
        if custom_sublevel_map is not None:
            for k, v_list in custom_sublevel_map.items():
                clean_v = [x for x in v_list if self._is_valid_sublevel_name(x)]
                cls_lvls[k] = clean_v
                for ln in clean_v:
                    if ln not in all_levels:
                        all_levels.append(ln)
            self.save_sublevel_mapping_for_current_world(cls_lvls)

        light_lvls_flat = []
        for rk in ["env", "key", "sky", "heightfog", "fill", "fog"]:
            light_lvls_flat.extend(cls_lvls.get(rk, []))
        self.organize_sublevels_in_levels_panel(light_lvls_flat)

        has_any_mapped = any(len(cls_lvls.get(k, [])) > 0 for k in ["scence", "env", "key", "sky", "heightfog", "fill", "fog"])
        if not is_single_mode and not has_any_mapped:
            return False, (
                "检测到当前地图尚未配置任何子关卡映射！\n\n"
                "• 方式 1：在面板第 03 区点击【自动创建并归类灯光/雾】，0.1秒即可完成拆分；\n"
                "• 方式 2：若该场景无需拆分灯光层，请切换为【模式一：单层快速模式】。"
            )

        render_out_dir = self.resolve_and_create_publish_render_dir(
            ep, shot, custom_ue_dir=custom_publish_dir,
            force_new_version=auto_increment_version, seq_names_to_clean=None,
            master_seq=master_seq
        )
        if not render_out_dir:
            return False, "未指定有效的 publish 输出目录。"

        # 防崩保护：在删除和同名复制当前镜头序列前，先关闭当前打开的 Sequencer 并只移除当前镜头在队列中的旧引用
        try:
            unreal.LevelSequenceEditorBlueprintLibrary.close_level_sequence()
        except Exception:
            pass

        queue = self.mrq_sub.get_queue()
        if queue:
            if clear_existing_queue:
                queue.delete_all_jobs()
            else:
                self._remove_only_shot_jobs_from_queue(queue, ep, shot, master_seq_name, shot_folder)

        master_seq = self.asset_sub.load_asset(master_pkg_path)
        self.ensure_sequence_camera_cut_bound_to_shot(master_seq, shot, start_f, end_f_exc)
        self.asset_sub.save_asset(master_pkg_path, only_if_is_dirty=True)

        scence_lvls = cls_lvls["scence"]
        global_mpc = self.get_or_create_global_emiss_mpc()
        cvar_assets_map = self.get_or_create_cvar_presets()
        queued_jobs_info = []

        if is_single_mode:
            for old_sfx in ("env", "key", "sky", "heightfog", "fill", "fog"):
                old_p = f"{shot_folder}/cam{shot}_{old_sfx}"
                if self.asset_sub.does_asset_exist(old_p):
                    self.asset_sub.delete_asset(old_p)

            if create_emiss_layer and global_mpc:
                self.inject_mpc_control_track(master_seq, global_mpc, 0.0, start_f, end_f_exc)
                self.asset_sub.save_asset(master_pkg_path, only_if_is_dirty=True)

            queued_jobs_info.append((master_seq, "beauty", ["母版全关卡直出"], "master"))

            single_sub_specs = []
            if create_emiss_layer:
                single_sub_specs.append(("emiss", scence_lvls, "beauty", 1.0))
            else:
                old_emiss = f"{shot_folder}/cam{shot}_emiss"
                if self.asset_sub.does_asset_exist(old_emiss):
                    self.asset_sub.delete_asset(old_emiss)

            single_sub_specs.extend([
                ("ID_actor",    scence_lvls, "id_actor",    0.0),
                ("ID_material", scence_lvls, "id_material", 0.0),
            ])

            for suffix, vis_lvls, preset_key, emiss_val in single_sub_specs:
                layer_seq_name = f"cam{shot}_{suffix}"
                layer_seq_path = f"{shot_folder}/{layer_seq_name}"
                if self.asset_sub.does_asset_exist(layer_seq_path):
                    self.asset_sub.delete_asset(layer_seq_path)

                dup_seq = self.asset_sub.duplicate_asset(master_pkg_path, layer_seq_path)
                if not dup_seq:
                    continue
                self.strip_media_and_cvar_tracks(dup_seq)
                self.ensure_sequence_camera_cut_bound_to_shot(dup_seq, shot, start_f, end_f_exc)
                if vis_lvls and all_levels:
                    self.inject_level_visibility_track(dup_seq, vis_lvls, all_levels, start_f, end_f_exc)
                if emiss_val is not None and global_mpc:
                    self.inject_mpc_control_track(dup_seq, global_mpc, emiss_val, start_f, end_f_exc)
                self.asset_sub.save_asset(layer_seq_path, only_if_is_dirty=False)
                queued_jobs_info.append((dup_seq, preset_key, vis_lvls if vis_lvls else ["主关卡默认场景"], suffix))
        else:
            layer_specs = [
                ("env",  scence_lvls + cls_lvls["env"],  "beauty", 0.0, cvar_assets_map.get("restore")),
                ("key",  scence_lvls + cls_lvls["key"],  "beauty", 0.0, cvar_assets_map.get("restore")),
                ("sky",  cls_lvls["sky"],                "beauty", 0.0, cvar_assets_map.get("restore")),
                ("fill", scence_lvls + cls_lvls["fill"], "beauty", 0.0, cvar_assets_map.get("restore")),
            ]

            if create_emiss_layer:
                layer_specs.append(("emiss", scence_lvls, "beauty", 1.0, cvar_assets_map.get("restore")))
            else:
                old_emiss = f"{shot_folder}/cam{shot}_emiss"
                if self.asset_sub.does_asset_exist(old_emiss):
                    self.asset_sub.delete_asset(old_emiss)

            layer_specs.extend([
                ("heightfog",   scence_lvls + cls_lvls["heightfog"] + cls_lvls["key"] + cls_lvls["env"], "beauty",      0.0, cvar_assets_map.get("heightfog")),
                ("fog",         scence_lvls + cls_lvls["fog"] + cls_lvls["key"] + cls_lvls["env"],       "beauty",      0.0, cvar_assets_map.get("fog")),
                ("ID_actor",    scence_lvls,                                                             "id_actor",    0.0, cvar_assets_map.get("restore")),
                ("ID_material", scence_lvls,                                                             "id_material", 0.0, cvar_assets_map.get("restore")),
            ])

            for suffix, vis_lvls, preset_key, emiss_val, cvar_asset_obj in layer_specs:
                layer_seq_name = f"cam{shot}_{suffix}"
                layer_seq_path = f"{shot_folder}/{layer_seq_name}"

                if self.asset_sub.does_asset_exist(layer_seq_path):
                    self.asset_sub.delete_asset(layer_seq_path)

                dup_seq = self.asset_sub.duplicate_asset(master_pkg_path, layer_seq_path)
                if not dup_seq:
                    continue

                self.strip_media_and_cvar_tracks(dup_seq)
                self.ensure_sequence_camera_cut_bound_to_shot(dup_seq, shot, start_f, end_f_exc)
                self.inject_level_visibility_track(dup_seq, vis_lvls, all_levels, start_f, end_f_exc)

                if emiss_val is not None and global_mpc:
                    self.inject_mpc_control_track(dup_seq, global_mpc, emiss_val, start_f, end_f_exc)

                if cvar_asset_obj:
                    self.inject_sequencer_cvar_track(dup_seq, cvar_asset_obj, start_f, end_f_exc)

                self.asset_sub.save_asset(layer_seq_path, only_if_is_dirty=False)
                queued_jobs_info.append((dup_seq, preset_key, vis_lvls, suffix))

        ensure_mrq_render_finish_monitor_active(render_out_dir)

        presets, _ = self.find_mrq_presets(force_rescan=False, explicit_paths_override=explicit_preset_paths)
        self.prepare_and_save_preset_assets(presets, render_out_dir)

        queue = self.mrq_sub.get_queue()
        if clear_existing_queue:
            queue.delete_all_jobs()
        else:
            self._remove_only_shot_jobs_from_queue(queue, ep, shot, master_seq_name, shot_folder)

        world = unreal.EditorLevelLibrary.get_editor_world()
        world_soft_path = unreal.SoftObjectPath(world.get_path_name())

        summary_lines = []
        for seq_obj, default_pk, lvls, sfx in queued_jobs_info:
            job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
            final_pk = self.resolve_preset_key_for_sequence(seq_obj.get_name(), default_pk)
            target_preset = presets.get(final_pk)

            job.job_name = seq_obj.get_name()
            job.map = world_soft_path
            job.sequence = unreal.SoftObjectPath(seq_obj.get_path_name())
            self.apply_preset_to_job_strictly(job, target_preset, render_out_dir)

            p_name = target_preset.get_name() if target_preset else f"未绑定({final_pk})"
            summary_lines.append(f"• {seq_obj.get_name():<22}  ➔  预设: [{p_name:<26}]  |  显示关卡: {lvls}")

        if hasattr(queue, "set_is_dirty"):
            queue.set_is_dirty(False)

        self.sync_content_browser_to_sequences([s for s, _, _, _ in queued_jobs_info], shot_folder=shot_folder)

        total_jobs_in_q = len(queue.get_jobs())
        ver_mode_str = "自动递增新版本 (v001 -> v002)" if auto_increment_version else "直接替换当前版本 (保留现有图片，渲染时直接覆盖)"
        msg = (
            f"【Shot {shot} 场景分层与 MRQ 渲染队列已就绪（队列当前总计 {total_jobs_in_q} 个任务）】\n\n"
            f"• 时间线帧区间: {start_f:04d} ~ {end_f_inc:04d} (共 {end_f_inc - start_f + 1} 帧)\n"
            f"• 内容浏览器定位: 已自动跳转并高亮 {shot_folder}\n"
            f"• 雾气与保底预设: CVar_HeightFog_Only / CVar_EasyFog_Only / CVar_Default_Restore (均严格只含 4 个 ShowFlag 参数)\n"
            f"• 输出版本策略: {ver_mode_str}\n"
            f"• 渲染输出目录: {render_out_dir}\n"
            f"• 自动弹窗状态: 已开启 (每个镜头 Sequence 渲染完成后将自动弹出对应文件夹)\n\n"
            f"【本次入列序列与绑定预设核对 (共 {len(queued_jobs_info)} 层)】\n" + "\n".join(summary_lines)
        )
        return True, msg


# =========================================================================
# 原生暗黑标题栏 + 纯净无蓝框自定义图标 & 跨 reload 单例窗口管理
# =========================================================================
def _enable_windows_dark_titlebar_and_pure_icon(tk_win):
    import tkinter as tk

    try:
        tk_win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(tk_win.winfo_id())
        if not hwnd:
            hwnd = tk_win.winfo_id()
        dark_val = ctypes.c_int(1)
        for attr_id in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr_id, ctypes.byref(dark_val), ctypes.sizeof(dark_val)
            )
    except Exception:
        pass

    curr_dir = os.path.dirname(os.path.abspath(__file__)).replace('\\', '/')
    proj_dir = os.path.normpath(unreal.Paths.project_dir()).replace('\\', '/')
    user_home = os.path.expanduser("~").replace('\\', '/')

    cand_icons = [
        os.path.join(curr_dir, "icon.png"),
        os.path.join(curr_dir, "icon.ico"),
        os.path.join(curr_dir, "icons/icon.png"),
        os.path.abspath(os.path.join(curr_dir, "../../Resources/Icon128.png")),
        os.path.abspath(os.path.join(curr_dir, "../../../Maya/icon.png")),
        os.path.abspath(os.path.join(curr_dir, "../../../Nuke/NukeWorkflowTool/icons/icon.png")),
        f"{user_home}/Documents/GitHub/VFX_Pipeline_CamSync/Nuke/NukeWorkflowTool/icons/icon.png",
        f"{user_home}/Documents/GitHub/VFX_Pipeline_CamSync/Maya/icon.png",
        f"{user_home}/.nuke/icons/icon.png",
    ]

    plugins_root = os.path.join(proj_dir, "Plugins")
    if os.path.exists(plugins_root):
        for root, _, files in os.walk(plugins_root):
            for f in files:
                if f.lower() in ("icon.png", "icon128.png", "icon.ico"):
                    cand_icons.insert(0, os.path.join(root, f))

    for icon_p in cand_icons:
        if icon_p and os.path.exists(icon_p):
            try:
                if icon_p.lower().endswith(".ico"):
                    tk_win.iconbitmap(icon_p)
                    return True
                else:
                    pure_img = tk.PhotoImage(master=tk_win, file=icon_p)
                    sys._LL_RENDER_ICON_REF = pure_img
                    tk_win.iconphoto(True, pure_img)
                    return True
            except Exception:
                pass
    return False


def _cleanup_existing_singleton_window():
    old_tick = getattr(sys, "_LL_RENDER_TICK_HANDLE", None)
    if old_tick is not None:
        try:
            unreal.unregister_slate_post_tick_callback(old_tick)
        except Exception:
            pass
        sys._LL_RENDER_TICK_HANDLE = None

    old_guide = getattr(sys, "_LL_RENDER_GUIDE_WIN", None)
    if old_guide is not None:
        try:
            if old_guide.winfo_exists():
                old_guide.destroy()
        except Exception:
            pass
        sys._LL_RENDER_GUIDE_WIN = None

    old_win = getattr(sys, "_LL_RENDER_TK_WIN", None)
    if old_win is not None:
        try:
            if old_win.winfo_exists():
                old_win.destroy()
        except Exception:
            pass
        sys._LL_RENDER_TK_WIN = None


def _PopupToplevelMessage(parent_win, title_str, body_str):
    import tkinter as tk

    old_guide = getattr(sys, "_LL_RENDER_GUIDE_WIN", None)
    if old_guide is not None:
        try:
            if old_guide.winfo_exists():
                old_guide.destroy()
        except Exception:
            pass
        sys._LL_RENDER_GUIDE_WIN = None

    top = tk.Toplevel(parent_win)
    sys._LL_RENDER_GUIDE_WIN = top
    top.title(title_str)
    top.configure(bg="#14161A")
    top.attributes('-topmost', True)
    top.transient(parent_win)

    card = tk.Frame(top, bg="#1C1F26", highlightbackground="#2E3440", highlightcolor="#2E3440", highlightthickness=1, padx=20, pady=16)
    card.pack(fill="both", expand=True, padx=12, pady=(12, 8))

    txt_lbl = tk.Label(
        card, text=body_str, justify="left", anchor="w",
        fg="#D8DEE9", bg="#1C1F26", font=("Microsoft YaHei UI", 9)
    )
    txt_lbl.pack(fill="both", expand=True)

    btn_ok = tk.Button(
        top, text="确认并关闭", command=top.destroy,
        bg="#0078D4", fg="#FFFFFF", activebackground="#106EBE", activeforeground="#FFFFFF",
        font=("Microsoft YaHei UI", 9, "bold"), relief="flat", bd=0, padx=24, pady=6, cursor="hand2"
    )
    btn_ok.pack(pady=(0, 12))

    top.update_idletasks()
    _enable_windows_dark_titlebar_and_pure_icon(top)
    w = max(600, top.winfo_reqwidth() + 24)
    h = top.winfo_reqheight() + 12
    sw = top.winfo_screenwidth()
    sh = top.winfo_screenheight()
    top.geometry(f"{w}x{h}+{int((sw - w) / 2)}+{int((sh - h) / 2)}")
    top.lift()
    top.focus_force()


def _ask_requeue_version_strategy_popup(parent_win):
    """
    点击【2. 仅将已有分层重新加入 MRQ】时弹出的模态询问框：
    返回 True (自动递增新版本) / False (直接替换当前版本) / None (取消)
    """
    import tkinter as tk

    result_ref = [None]

    dlg = tk.Toplevel(parent_win)
    dlg.title("选择重新入列的输出版本策略")
    dlg.configure(bg="#14161A")
    dlg.attributes('-topmost', True)
    dlg.transient(parent_win)
    dlg.resizable(False, False)

    card = tk.Frame(dlg, bg="#1C1F26", highlightbackground="#2E3440", highlightcolor="#2E3440", highlightthickness=1, padx=22, pady=18)
    card.pack(fill="both", expand=True, padx=14, pady=(14, 10))

    tk.Label(
        card, text="请选择【仅将已有分层重新加入 MRQ】的输出版本策略：",
        justify="left", anchor="w", fg="#E5E9F0", bg="#1C1F26",
        font=("Microsoft YaHei UI", 10, "bold")
    ).pack(anchor="w", pady=(0, 8))

    tk.Label(
        card,
        text="• 自动递增版本：若当前版本目录（如 v001）已有渲染图，自动递增新建 v002 / v003（若无图则保持 v001）\n"
             "• 替换当前版本：不删除已有渲染图素材，直接锁定当前版本目录（如 v001），待启动渲染时由 UE 直接覆盖\n"
             "• 多镜头队列隔离：自动保留队列中已添加的其他镜头（如 cam2220），各镜头输出路径独立互不覆盖",
        justify="left", anchor="w", fg="#9AA5B4", bg="#1C1F26",
        font=("Microsoft YaHei UI", 9)
    ).pack(anchor="w", pady=(0, 14))

    btn_row = tk.Frame(card, bg="#1C1F26")
    btn_row.pack(fill="x")

    def _choose(val):
        result_ref[0] = val
        dlg.destroy()

    btn_inc = tk.Button(
        btn_row, text="自动递增新版本 (有图则新建 v002/v003)", command=lambda: _choose(True),
        bg="#107C41", fg="#FFFFFF", activebackground="#159650", activeforeground="#FFFFFF",
        font=("Microsoft YaHei UI", 9, "bold"), relief="flat", bd=0, padx=16, pady=7, cursor="hand2"
    )
    btn_inc.pack(side="left", padx=(0, 8))

    btn_rep = tk.Button(
        btn_row, text="直接替换当前版本 (保留旧图·渲染时覆盖)", command=lambda: _choose(False),
        bg="#1D4ED8", fg="#FFFFFF", activebackground="#2563EB", activeforeground="#FFFFFF",
        font=("Microsoft YaHei UI", 9, "bold"), relief="flat", bd=0, padx=16, pady=7, cursor="hand2"
    )
    btn_rep.pack(side="left", padx=(0, 8))

    btn_cancel = tk.Button(
        btn_row, text="取消", command=lambda: _choose(None),
        bg="#2A2F3A", fg="#9AA5B4", activebackground="#373E4D", activeforeground="#FFFFFF",
        font=("Microsoft YaHei UI", 9), relief="flat", bd=0, padx=14, pady=7, cursor="hand2"
    )
    btn_cancel.pack(side="right")

    dlg.update_idletasks()
    _enable_windows_dark_titlebar_and_pure_icon(dlg)
    w = max(580, dlg.winfo_reqwidth() + 24)
    h = dlg.winfo_reqheight() + 14
    sw = dlg.winfo_screenwidth()
    sh = dlg.winfo_screenheight()
    dlg.geometry(f"{w}x{h}+{int((sw - w) / 2)}+{int((sh - h) / 2)}")
    dlg.lift()
    dlg.focus_force()
    dlg.grab_set()
    parent_win.wait_window(dlg)
    return result_ref[0]


def _create_social_icon_pill(parent, platform_type, label_text, on_click_cmd, bg_norm="#1C1F26", bg_hover="#2A303C"):
    import tkinter as tk

    pill = tk.Frame(parent, bg=bg_norm, highlightbackground="#2E3440", highlightcolor="#2E3440", highlightthickness=1, padx=8, pady=3, cursor="hand2")
    cv = tk.Canvas(pill, width=18, height=16, bg=bg_norm, highlightthickness=0, bd=0, cursor="hand2")
    cv.pack(side="left", padx=(0, 5))

    if platform_type == "github":
        cv.create_oval(1, 1, 15, 15, fill="#E5E9F0", outline="")
        cv.create_polygon(3, 5, 5, 2, 7, 5, fill="#14161A", outline="")
        cv.create_polygon(9, 5, 11, 2, 13, 5, fill="#14161A", outline="")
        cv.create_oval(4, 4, 12, 11, fill="#14161A", outline="")
        cv.create_rectangle(6, 10, 10, 15, fill="#14161A", outline="")
        fg_col = "#FFFFFF"
    elif platform_type == "youtube":
        cv.create_rectangle(1, 2, 17, 14, fill="#FF0000", outline="#FF0000")
        cv.create_polygon(7, 5, 7, 11, 13, 8, fill="#FFFFFF", outline="")
        fg_col = "#FFFFFF"
    elif platform_type == "bilibili":
        cv.create_line(5, 1, 8, 4, fill="#19a3d6", width=2)
        cv.create_line(13, 1, 10, 4, fill="#19a3d6", width=2)
        cv.create_rectangle(2, 4, 16, 14, fill="#19a3d6", outline="#19a3d6")
        cv.create_rectangle(4, 6, 14, 12, fill="#14161A", outline="")
        cv.create_line(6, 8, 8, 10, fill="#19a3d6", width=2)
        cv.create_line(12, 8, 10, 10, fill="#19a3d6", width=2)
        fg_col = "#FFFFFF"
    else:
        cv.create_rectangle(1, 3, 16, 13, fill="#101216", outline="#38BDF8", width=1)
        cv.create_line(1, 3, 8, 9, 16, 3, fill="#38BDF8", width=1)
        fg_col = "#38BDF8"

    lbl = tk.Label(pill, text=label_text, fg=fg_col, bg=bg_norm, font=("Consolas", 8, "bold"), cursor="hand2")
    lbl.pack(side="left")

    def _on_enter(e):
        pill.config(bg=bg_hover, highlightbackground="#38BDF8", highlightcolor="#38BDF8")
        cv.config(bg=bg_hover)
        lbl.config(bg=bg_hover, fg="#FFFFFF")

    def _on_leave(e):
        pill.config(bg=bg_norm, highlightbackground="#2E3440", highlightcolor="#2E3440")
        cv.config(bg=bg_norm)
        lbl.config(bg=bg_norm, fg=fg_col)

    for w in (pill, cv, lbl):
        w.bind("<Enter>", _on_enter)
        w.bind("<Leave>", _on_leave)
        w.bind("<Button-1>", lambda e: on_click_cmd())

    return pill, lbl


# =========================================================================
# 大厂工业级深色卡片 UI 主面板 (v5.8 Studio Pro)
# =========================================================================
def show_render_layer_dialog():
    import tkinter as tk
    from tkinter import filedialog

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    existing_win = getattr(sys, "_LL_RENDER_TK_WIN", None)
    existing_ver = getattr(sys, "_LL_RENDER_WIN_VER", "")
    if existing_win is not None and existing_ver == TOOL_VERSION_TAG:
        try:
            if existing_win.winfo_exists():
                existing_win.deiconify()
                existing_win.lift()
                existing_win.focus_force()
                return
        except Exception:
            pass
    _cleanup_existing_singleton_window()

    pipe = UERenderLayerPipeline()
    std_folders = pipe.detect_project_standard_folders()

    master_seq = pipe.get_active_master_sequence(allow_content_browser_selection=True)
    start_f, end_f_inc, _ = pipe.get_exact_timeline_range(master_seq)

    real_sublevels, cls_lvls, def_light_dir, _ = pipe.scan_mounted_and_folder_sublevels()
    presets, all_preset_paths = pipe.find_mrq_presets(force_rescan=False)
    cfg = pipe.load_config()
    saved_preset_paths = cfg.get("mrq_preset_paths", {})

    C_BG_MAIN      = "#14161A"
    C_CARD_BG      = "#1C1F26"
    C_CARD_HEADER  = "#222630"
    C_CARD_BORDER  = "#2C313C"
    C_INPUT_BG     = "#101216"
    C_INPUT_BORDER = "#303642"
    C_TEXT_MAIN    = "#E5E9F0"
    C_TEXT_SUB     = "#9AA5B4"
    C_TEXT_MUTED   = "#636E7E"
    C_ACCENT_BLUE  = "#0078D4"
    C_ACCENT_CYAN  = "#38BDF8"
    C_ACCENT_GREEN = "#10B981"
    C_ACCENT_AMBER = "#F59E0B"
    C_ACCENT_RED   = "#EF4444"
    C_BTN_DARK     = "#2A2F3A"
    C_BTN_HOVER    = "#373E4D"

    FONT_UI        = "Microsoft YaHei UI"
    FONT_MONO      = "Consolas"

    win = tk.Tk()
    sys._LL_RENDER_TK_WIN = win
    sys._LL_RENDER_WIN_VER = TOOL_VERSION_TAG
    win.title(f"UE5 Render Layer & MRQ Pipeline Center  —  v{TOOL_VERSION_TAG} Studio Pro  |  By {AUTHOR_NAME}")
    win.configure(bg=C_BG_MAIN, highlightthickness=0, bd=0)
    win.attributes('-topmost', True)
    win.resizable(True, True)

    # 全局禁止 Frame / Label / Button 产生焦点高亮外框，杜绝点击输入框或空白处时整个卡片模块发亮出大框
    win.option_add("*Frame.takeFocus", 0)
    win.option_add("*Label.takeFocus", 0)
    win.option_add("*Button.takeFocus", 0)
    win.option_add("*Checkbutton.takeFocus", 0)
    win.option_add("*Radiobutton.takeFocus", 0)
    win.option_add("*Menubutton.takeFocus", 0)

    # 创建一个 0x0 像素、完全看不见的隐藏焦点接收器，专门用于在点击非输入框时静默移走 Entry 的闪烁竖线
    _dummy_focus_sink = tk.Frame(win, width=0, height=0, bg=C_BG_MAIN, highlightthickness=0, bd=0, takefocus=1)
    _dummy_focus_sink.place(x=-10, y=-10)

    def _clear_entry_focus_on_click(event):
        try:
            w = event.widget
            if w is not None and not isinstance(w, tk.Entry):
                _dummy_focus_sink.focus_set()
        except Exception:
            pass

    win.bind_all("<Button-1>", _clear_entry_focus_on_click, add="+")

    def _on_close_win():
        _cleanup_existing_singleton_window()

    win.protocol("WM_DELETE_WINDOW", _on_close_win)

    def _bind_hover(btn_widget, normal_bg, hover_bg, normal_fg=None, hover_fg=None):
        def _on_enter(e):
            btn_widget.config(bg=hover_bg)
            if hover_fg:
                btn_widget.config(fg=hover_fg)
        def _on_leave(e):
            btn_widget.config(bg=normal_bg)
            if normal_fg:
                btn_widget.config(fg=normal_fg)
        btn_widget.bind("<Enter>", _on_enter)
        btn_widget.bind("<Leave>", _on_leave)

    default_mode = "multi" if len(real_sublevels) > 0 else "single"
    mode_var = tk.StringVar(master=win, value=default_mode)
    emiss_var = tk.BooleanVar(master=win, value=False)
    inc_ver_var = tk.BooleanVar(master=win, value=True)
    prefix_var = tk.StringVar(master=win, value="night_")
    light_dir_var = tk.StringVar(master=win, value=def_light_dir)
    topmost_var = tk.BooleanVar(master=win, value=True)
    linked_ue_dir_var = tk.StringVar(master=win, value="")

    # ----------------- 顶部 Header 与镜头上下文仪表盘 -----------------
    header_bar = tk.Frame(win, bg="#0E1013", highlightbackground=C_CARD_BORDER, highlightcolor=C_CARD_BORDER, highlightthickness=1, padx=16, pady=10)
    header_bar.pack(fill="x", padx=14, pady=(10, 5))

    title_row = tk.Frame(header_bar, bg="#0E1013")
    title_row.pack(fill="x", pady=(0, 8))

    tk.Label(title_row, text="UNREAL ENGINE 5", fg=C_ACCENT_CYAN, bg="#0E1013", font=(FONT_UI, 9, "bold")).pack(side="left")
    tk.Label(title_row, text="  |  影视级分层裂变与 MRQ 自动化调度中心", fg=C_TEXT_MAIN, bg="#0E1013", font=(FONT_UI, 11, "bold")).pack(side="left")

    def _toggle_topmost():
        win.attributes('-topmost', bool(topmost_var.get()))

    tk.Checkbutton(
        title_row, text="窗口置顶", variable=topmost_var, command=_toggle_topmost,
        fg=C_TEXT_SUB, bg="#0E1013", selectcolor="#1C1F26", activebackground="#0E1013", activeforeground=C_TEXT_MAIN,
        font=(FONT_UI, 8), highlightthickness=0, bd=0
    ).pack(side="right", padx=(10, 0))

    tk.Label(title_row, text=f" STUDIO PRO v{TOOL_VERSION_TAG} ", fg="#0E1013", bg=C_ACCENT_CYAN, font=(FONT_MONO, 8, "bold"), padx=6, pady=1).pack(side="right")

    ctx_row = tk.Frame(header_bar, bg="#161920", highlightbackground="#252A34", highlightcolor="#252A34", highlightthickness=1, padx=12, pady=6)
    ctx_row.pack(fill="x")

    tk.Label(ctx_row, text="母版序列:", fg=C_TEXT_SUB, bg="#161920", font=(FONT_UI, 9)).pack(side="left")
    lbl_seq_badge = tk.Label(ctx_row, text="", fg=C_ACCENT_GREEN, bg="#101216", font=(FONT_MONO, 9, "bold"), padx=10, pady=2)
    lbl_seq_badge.pack(side="left", padx=(6, 16))

    tk.Label(ctx_row, text="时间线帧范围:", fg=C_TEXT_SUB, bg="#161920", font=(FONT_UI, 9)).pack(side="left")
    lbl_frame_badge = tk.Label(ctx_row, text="", fg=C_ACCENT_CYAN, bg="#101216", font=(FONT_MONO, 9, "bold"), padx=10, pady=2)
    lbl_frame_badge.pack(side="left", padx=(6, 12))

    lbl_link_badge_ref = [None]
    ent_link_dir_ref = [None]

    def _sync_shot_linked_output_path(seq_obj, prompt_if_missing=False):
        if not seq_obj:
            linked_ue_dir_var.set("")
            if lbl_link_badge_ref[0]:
                lbl_link_badge_ref[0].config(text="● 待选镜头", fg=C_TEXT_MUTED)
            return

        ep, shot = pipe.parse_ep_and_shot_from_seq(seq_obj)
        detected_u = pipe.detect_linked_ue_output_root(ep, shot, master_seq=seq_obj)
        if detected_u:
            linked_ue_dir_var.set(detected_u)
            if lbl_link_badge_ref[0]:
                lbl_link_badge_ref[0].config(text="● 已联动", fg=C_ACCENT_GREEN)
            if ent_link_dir_ref[0]:
                ent_link_dir_ref[0].config(fg=C_ACCENT_GREEN)
        else:
            linked_ue_dir_var.set("")
            if lbl_link_badge_ref[0]:
                lbl_link_badge_ref[0].config(text="● 未绑定", fg=C_ACCENT_RED)
            if ent_link_dir_ref[0]:
                ent_link_dir_ref[0].config(fg=C_ACCENT_RED)
            if prompt_if_missing:
                chosen = filedialog.askdirectory(
                    parent=win,
                    title=f"未检测到 Shot {shot} 的相机联动路径，请指定一次 ue 输出目录 (指定后将自动永久保存)"
                )
                if chosen:
                    norm_c = pipe._strip_publish_or_version_suffix(chosen)
                    pipe.save_linked_ue_output_root(ep, shot, norm_c)
                    linked_ue_dir_var.set(norm_c)
                    if lbl_link_badge_ref[0]:
                        lbl_link_badge_ref[0].config(text="● 已绑定", fg=C_ACCENT_GREEN)
                    if ent_link_dir_ref[0]:
                        ent_link_dir_ref[0].config(fg=C_ACCENT_GREEN)

    def _update_seq_badges(seq_obj, sf, ef_inc, prompt_missing_path=False):
        if seq_obj and sf is not None and ef_inc is not None:
            total_len = ef_inc - sf + 1
            lbl_seq_badge.config(text=f"● {seq_obj.get_name()}", fg=C_ACCENT_GREEN)
            lbl_frame_badge.config(text=f"{sf:04d} - {ef_inc:04d}  ({total_len} Frames)", fg=C_ACCENT_CYAN)
        else:
            lbl_seq_badge.config(text="● 未打开母版序列 (请从右侧选择)", fg=C_ACCENT_RED)
            lbl_frame_badge.config(text="---- ~ ----", fg=C_TEXT_MUTED)
        _sync_shot_linked_output_path(seq_obj, prompt_if_missing=prompt_missing_path)

    def _select_and_open_seq_by_path(seq_pkg_path):
        nonlocal master_seq, start_f, end_f_inc
        if seq_pkg_path and pipe.asset_sub.does_asset_exist(seq_pkg_path):
            master_seq = pipe.asset_sub.load_asset(seq_pkg_path)
            if master_seq:
                try:
                    unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(master_seq)
                except Exception:
                    pass
                start_f, end_f_inc, _ = pipe.get_exact_timeline_range(master_seq)
                _update_seq_badges(master_seq, start_f, end_f_inc, prompt_missing_path=True)

    def _refresh_master_seq(allow_cb=True):
        nonlocal master_seq, start_f, end_f_inc
        master_seq = pipe.get_active_master_sequence(allow_content_browser_selection=allow_cb)
        if master_seq:
            try:
                unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(master_seq)
            except Exception:
                pass
        start_f, end_f_inc, _ = pipe.get_exact_timeline_range(master_seq)
        _update_seq_badges(master_seq, start_f, end_f_inc, prompt_missing_path=True)

    def _open_current_output_dir():
        out_d = _extract_output_dir_from_active_queue() or linked_ue_dir_var.get().strip()
        if not open_folder_in_explorer(out_d):
            _PopupToplevelMessage(win, "提示", "当前尚未生成输出目录或队列为空！请先点击底部绿色按钮生成队列。")

    btn_open_dir = tk.Button(
        ctx_row, text="打开输出文件夹", command=_open_current_output_dir,
        bg=C_BTN_DARK, fg=C_ACCENT_AMBER, font=(FONT_UI, 8, "bold"), relief="flat", bd=0, padx=10, pady=3, cursor="hand2"
    )
    btn_open_dir.pack(side="right", padx=(4, 0))
    _bind_hover(btn_open_dir, C_BTN_DARK, C_BTN_HOVER)

    btn_pick_seq = tk.Button(
        ctx_row, text="拾取UE选中序列", command=lambda: _refresh_master_seq(True),
        bg=C_BTN_DARK, fg=C_TEXT_MAIN, font=(FONT_UI, 8), relief="flat", bd=0, padx=10, pady=3, cursor="hand2"
    )
    btn_pick_seq.pack(side="right", padx=4)
    _bind_hover(btn_pick_seq, C_BTN_DARK, C_BTN_HOVER)

    mb_seq = tk.Menubutton(
        ctx_row, text="选择母版镜头 ▾", bg=C_ACCENT_BLUE, fg="#FFFFFF",
        activebackground="#106EBE", activeforeground="#FFFFFF",
        relief="flat", bd=0, font=(FONT_UI, 8, "bold"), padx=12, pady=3, cursor="hand2"
    )
    seq_menu = tk.Menu(mb_seq, tearoff=0, bg="#1C1F26", fg=C_TEXT_MAIN, activebackground=C_ACCENT_BLUE, font=(FONT_UI, 9))
    mb_seq.config(menu=seq_menu)

    def _populate_seq_menu():
        seq_menu.delete(0, "end")
        master_items = pipe.list_all_master_sequences_in_project()
        if master_items:
            for short_name, pkg_p in master_items:
                seq_menu.add_command(label=f"  {short_name}", command=lambda p=pkg_p: _select_and_open_seq_by_path(p))
        else:
            seq_menu.add_command(label="(工程中暂未找到母版主镜头序列)", state="disabled")

    _populate_seq_menu()
    mb_seq.pack(side="right", padx=4)

    # ----------------- 第一区：01 分层渲染模式 + 02 版本策略与联动输出路径双卡片 -----------------
    row1_container = tk.Frame(win, bg=C_BG_MAIN)
    row1_container.pack(fill="x", padx=14, pady=4)
    row1_container.columnconfigure(0, weight=3)
    row1_container.columnconfigure(1, weight=2)

    card_mode = tk.Frame(row1_container, bg=C_CARD_BG, highlightbackground=C_CARD_BORDER, highlightcolor=C_CARD_BORDER, highlightthickness=1)
    card_mode.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

    hdr_mode = tk.Frame(card_mode, bg=C_CARD_HEADER, padx=12, pady=6)
    hdr_mode.pack(fill="x")
    tk.Label(hdr_mode, text="01  |  分层渲染模式 (RENDER LAYER MODE)", fg=C_ACCENT_AMBER, bg=C_CARD_HEADER, font=(FONT_UI, 9, "bold")).pack(side="left")
    tk.Label(hdr_mode, text="无缝对接 Nuke 自动预合成", fg=C_TEXT_MUTED, bg=C_CARD_HEADER, font=(FONT_UI, 8)).pack(side="right")

    body_mode = tk.Frame(card_mode, bg=C_CARD_BG, padx=14, pady=8)
    body_mode.pack(fill="both", expand=True)

    tk.Radiobutton(
        body_mode,
        text="模式一：单层快速模式   [ 主镜头 + ID_actor + ID_material ]",
        variable=mode_var, value="single",
        fg=C_TEXT_MAIN, bg=C_CARD_BG, selectcolor=C_INPUT_BG, activebackground=C_CARD_BG, activeforeground=C_ACCENT_CYAN,
        font=(FONT_UI, 9, "bold"), highlightthickness=0, bd=0
    ).pack(anchor="w", pady=2)

    tk.Radiobutton(
        body_mode,
        text="模式二：多层全拆分模式 [ env / key / sky / fill / heightfog / fog + 双ID ]",
        variable=mode_var, value="multi",
        fg=C_ACCENT_GREEN, bg=C_CARD_BG, selectcolor=C_INPUT_BG, activebackground=C_CARD_BG, activeforeground=C_ACCENT_GREEN,
        font=(FONT_UI, 9, "bold"), highlightthickness=0, bd=0
    ).pack(anchor="w", pady=2)

    tk.Checkbutton(
        body_mode,
        text="额外生成自发光层 (cam_emiss — 单层/多层均支持，自动挂载 MPC_Global_Emiss)",
        variable=emiss_var,
        fg=C_ACCENT_AMBER, bg=C_CARD_BG, selectcolor=C_INPUT_BG, activebackground=C_CARD_BG, activeforeground=C_ACCENT_AMBER,
        font=(FONT_UI, 9), highlightthickness=0, bd=0
    ).pack(anchor="w", pady=(4, 2))

    card_ver = tk.Frame(row1_container, bg=C_CARD_BG, highlightbackground=C_CARD_BORDER, highlightcolor=C_CARD_BORDER, highlightthickness=1)
    card_ver.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

    hdr_ver = tk.Frame(card_ver, bg=C_CARD_HEADER, padx=12, pady=6)
    hdr_ver.pack(fill="x")
    tk.Label(hdr_ver, text="02  |  输出版本策略与相机路径联动", fg=C_ACCENT_AMBER, bg=C_CARD_HEADER, font=(FONT_UI, 9, "bold")).pack(side="left")
    tk.Label(hdr_ver, text="每个镜头跑完即刻弹出", fg=C_ACCENT_GREEN, bg=C_CARD_HEADER, font=(FONT_UI, 8, "bold")).pack(side="right")

    body_ver = tk.Frame(card_ver, bg=C_CARD_BG, padx=14, pady=8)
    body_ver.pack(fill="both", expand=True)

    tk.Radiobutton(
        body_ver,
        text="自动递增版本 (若 v001 已有图，自动新建 v002 / v003)",
        variable=inc_ver_var, value=True,
        fg=C_ACCENT_GREEN, bg=C_CARD_BG, selectcolor=C_INPUT_BG, activebackground=C_CARD_BG, activeforeground=C_ACCENT_GREEN,
        font=(FONT_UI, 9, "bold"), highlightthickness=0, bd=0
    ).pack(anchor="w", pady=1)

    tk.Radiobutton(
        body_ver,
        text="直接替换当前版本 (保留现有图片，渲染时直接覆盖旧图)",
        variable=inc_ver_var, value=False,
        fg=C_TEXT_MAIN, bg=C_CARD_BG, selectcolor=C_INPUT_BG, activebackground=C_CARD_BG, activeforeground=C_ACCENT_AMBER,
        font=(FONT_UI, 9), highlightthickness=0, bd=0
    ).pack(anchor="w", pady=1)

    link_row = tk.Frame(body_ver, bg=C_CARD_BG)
    link_row.pack(fill="x", pady=(4, 0))

    lbl_link_badge = tk.Label(link_row, text="● 检测中", fg=C_ACCENT_GREEN, bg=C_INPUT_BG, font=(FONT_UI, 8, "bold"), padx=6, pady=2)
    lbl_link_badge.pack(side="left", padx=(0, 4))
    lbl_link_badge_ref[0] = lbl_link_badge

    ent_link_dir = tk.Entry(
        link_row, textvariable=linked_ue_dir_var, bg=C_INPUT_BG, fg=C_ACCENT_GREEN,
        insertbackground="#FFFFFF", relief="flat", highlightbackground=C_INPUT_BORDER, highlightcolor=C_ACCENT_CYAN, highlightthickness=1,
        font=(FONT_MONO, 8)
    )
    ent_link_dir.pack(side="left", fill="x", expand=True, padx=2, ipady=2)
    ent_link_dir_ref[0] = ent_link_dir

    def _on_browse_ue_output_dir():
        ep, shot = pipe.parse_ep_and_shot_from_seq(master_seq) if master_seq else ("EP01", "1001")
        chosen = filedialog.askdirectory(
            parent=win,
            title=f"请指定 Shot {shot} 的 ue 输出根目录 (如 X:/.../ep28/{shot}/ue)"
        )
        if chosen:
            norm_c = pipe._strip_publish_or_version_suffix(chosen)
            linked_ue_dir_var.set(norm_c)
            pipe.save_linked_ue_output_root(ep, shot, norm_c)
            lbl_link_badge.config(text="● 已绑定", fg=C_ACCENT_GREEN)
            ent_link_dir.config(fg=C_ACCENT_GREEN)

    btn_browse_out = tk.Button(
        link_row, text="指定目录", command=_on_browse_ue_output_dir,
        bg=C_BTN_DARK, fg=C_ACCENT_CYAN, relief="flat", bd=0, font=(FONT_UI, 8, "bold"), padx=8, pady=2, cursor="hand2"
    )
    btn_browse_out.pack(side="right", padx=(4, 0))
    _bind_hover(btn_browse_out, C_BTN_DARK, C_BTN_HOVER)

    _update_seq_badges(master_seq, start_f, end_f_inc, prompt_missing_path=False)

    # ----------------- 第二区：03 子关卡映射与一键拆层矩阵 -----------------
    card_lvl = tk.Frame(win, bg=C_CARD_BG, highlightbackground=C_CARD_BORDER, highlightcolor=C_CARD_BORDER, highlightthickness=1)
    card_lvl.pack(fill="x", padx=14, pady=4)

    hdr_lvl = tk.Frame(card_lvl, bg=C_CARD_HEADER, padx=12, pady=6)
    hdr_lvl.pack(fill="x")
    tk.Label(hdr_lvl, text="03  |  子关卡映射与场景自动拆分 (SUBLEVEL MAPPING MATRIX)", fg=C_ACCENT_AMBER, bg=C_CARD_HEADER, font=(FONT_UI, 9, "bold")).pack(side="left")

    lbl_sublevel_status = tk.Label(hdr_lvl, text="", fg=C_ACCENT_GREEN, bg=C_CARD_HEADER, font=(FONT_UI, 8, "bold"))
    lbl_sublevel_status.pack(side="right")

    lvl_bar = tk.Frame(card_lvl, bg="#161920", padx=12, pady=6)
    lvl_bar.pack(fill="x")

    tk.Label(lvl_bar, text="命名前缀:", fg=C_TEXT_SUB, bg="#161920", font=(FONT_UI, 8)).pack(side="left")
    tk.Entry(
        lvl_bar, textvariable=prefix_var, width=8, bg=C_INPUT_BG, fg=C_ACCENT_GREEN,
        insertbackground="#FFFFFF", relief="flat", highlightbackground=C_INPUT_BORDER, highlightcolor=C_ACCENT_CYAN, highlightthickness=1,
        font=(FONT_MONO, 9, "bold")
    ).pack(side="left", padx=(4, 2), ipady=2)

    mb_pfx = tk.Menubutton(lvl_bar, text="▾", bg=C_BTN_DARK, fg=C_TEXT_MAIN, relief="flat", bd=0, font=(FONT_UI, 8), padx=6, pady=2, cursor="hand2")
    pfx_menu = tk.Menu(mb_pfx, tearoff=0, bg="#1C1F26", fg=C_TEXT_MAIN, activebackground=C_ACCENT_BLUE)
    mb_pfx.config(menu=pfx_menu)
    for p_opt in ["night_", "day_", "dusk_", ""]:
        pfx_menu.add_command(label=f"设为: '{p_opt}'", command=lambda v=p_opt: prefix_var.set(v))
    mb_pfx.pack(side="left", padx=(0, 12))

    tk.Label(lvl_bar, text="Light 存放目录:", fg=C_TEXT_SUB, bg="#161920", font=(FONT_UI, 8)).pack(side="left")
    tk.Entry(
        lvl_bar, textvariable=light_dir_var, width=28, bg=C_INPUT_BG, fg=C_ACCENT_CYAN,
        insertbackground="#FFFFFF", relief="flat", highlightbackground=C_INPUT_BORDER, highlightcolor=C_ACCENT_CYAN, highlightthickness=1,
        font=(FONT_MONO, 9)
    ).pack(side="left", padx=4, ipady=2)

    def _pick_selected_folder_for_light():
        try:
            sel_paths = unreal.EditorUtilityLibrary.get_current_content_browser_path()
            if sel_paths:
                light_dir_var.set(str(sel_paths))
        except Exception:
            pass

    btn_cur_dir = tk.Button(
        lvl_bar, text="取当前目录", command=_pick_selected_folder_for_light,
        bg=C_BTN_DARK, fg=C_TEXT_SUB, relief="flat", bd=0, font=(FONT_UI, 8), padx=8, pady=2, cursor="hand2"
    )
    btn_cur_dir.pack(side="left", padx=(0, 10))
    _bind_hover(btn_cur_dir, C_BTN_DARK, C_BTN_HOVER)

    lvl_StringVars = {}
    lvl_Menus = {}

    def _update_sublevel_status_label(sub_list):
        if sub_list:
            lbl_sublevel_status.config(text=f"● 已识别 {len(sub_list)} 个子关卡: {', '.join(sub_list)}", fg=C_ACCENT_GREEN)
        else:
            lbl_sublevel_status.config(text="● 当前地图未检测到子关卡 (可使用单层模式或点击下方按钮一键创建)", fg=C_ACCENT_RED)

    def _refresh_sublevel_widgets():
        nonlocal real_sublevels, cls_lvls
        real_sublevels, cls_lvls, _, _ = pipe.scan_mounted_and_folder_sublevels(custom_light_dir=light_dir_var.get())
        _update_sublevel_status_label(real_sublevels)
        for k, sv in lvl_StringVars.items():
            sv.set(", ".join(cls_lvls.get(k, [])))
            m_pop = lvl_Menus.get(k)
            if m_pop:
                m_pop.delete(0, "end")
                if real_sublevels:
                    for avail_l in real_sublevels:
                        m_pop.add_command(label=f"设为: {avail_l}", command=lambda s=sv, l=avail_l: s.set(l))
                    m_pop.add_separator()
                    for avail_l in real_sublevels:
                        m_pop.add_command(label=f"追加: + {avail_l}", command=lambda s=sv, l=avail_l: s.set(", ".join(list(dict.fromkeys([x.strip() for x in s.get().split(",") if x.strip()] + [l])))))
                    m_pop.add_separator()
                    m_pop.add_command(label="清空此项", command=lambda s=sv: s.set(""))
        if real_sublevels:
            mode_var.set("multi")

    def _show_split_guide_popup():
        pfx = prefix_var.get().strip()
        if pfx and not pfx.endswith("_"):
            pfx += "_"
        lines = [
            "【标准项目文件夹与关卡拆分规范】\n",
            f"1. 主渲染关卡 (如 {std_folders['proj_root']}/Map/项目名_Render)：",
            "   └ 保留：PostProcessVolume (后期处理体积)、导入的镜头相机 (/!Cam)、Shot_Root、ImagePlate、SM_Ref 参考简模。\n",
            f"2. 场景模型子关卡 ({std_folders['scence_dir']}/scence)：",
            "   └ 存放：静态网格体(StaticMesh)、地形(Landscape)、建筑、植被 (脚本自动跳过移动场景模型，0卡顿)。\n",
            f"3. 灯光与雾气子关卡 ({light_dir_var.get()} 下创建，自动归入 Levels 面板 [Light] 文件夹)："
        ]
        for role_k, base_sfx, _, lbl, desc in SUBLEVEL_ROLE_SPECS:
            if role_k == "scence":
                continue
            lines.append(f"   • {pfx}{base_sfx:<14} ({lbl})  ➔  {desc}")
        lines.append(
            f"\n4. 专属资产存放目录：\n"
            f"   • 控制台变量预设 : {std_folders['cvar_dir']} (CVar_HeightFog_Only / CVar_EasyFog_Only / CVar_Default_Restore)\n"
            f"   • 材质参数集总控 : {std_folders['collection_dir']}/MPC_Global_Emiss"
        )
        _PopupToplevelMessage(win, "UE 影视项目关卡存放规范", "\n".join(lines))

    def _on_create_empty_sublevels():
        ok, msg = pipe.create_or_mount_light_sublevels(
            prefix_str=prefix_var.get(), light_dir=light_dir_var.get(), auto_move_lights_and_fog=False
        )
        _refresh_sublevel_widgets()
        _PopupToplevelMessage(win, "子关卡创建结果", msg)

    def _on_auto_split_lights_and_fog():
        ok, msg = pipe.create_or_mount_light_sublevels(
            prefix_str=prefix_var.get(), light_dir=light_dir_var.get(), auto_move_lights_and_fog=True
        )
        _refresh_sublevel_widgets()
        _PopupToplevelMessage(win, "灯光与雾自动归类完成", msg)

    btn_auto_split = tk.Button(
        lvl_bar, text="自动创建并归类灯光/雾 (不移scence)", command=_on_auto_split_lights_and_fog,
        bg="#107C41", fg="#FFFFFF", relief="flat", bd=0, font=(FONT_UI, 8, "bold"), padx=10, pady=3, cursor="hand2"
    )
    btn_auto_split.pack(side="right", padx=(3, 0))
    _bind_hover(btn_auto_split, "#107C41", "#159650")

    btn_empty_sub = tk.Button(
        lvl_bar, text="创建空白灯光/雾子关卡", command=_on_create_empty_sublevels,
        bg=C_BTN_DARK, fg=C_ACCENT_AMBER, relief="flat", bd=0, font=(FONT_UI, 8, "bold"), padx=9, pady=3, cursor="hand2"
    )
    btn_empty_sub.pack(side="right", padx=3)
    _bind_hover(btn_empty_sub, C_BTN_DARK, C_BTN_HOVER)

    btn_rescan_lvl = tk.Button(
        lvl_bar, text="刷新识别 (.umap)", command=_refresh_sublevel_widgets,
        bg=C_BTN_DARK, fg=C_ACCENT_CYAN, relief="flat", bd=0, font=(FONT_UI, 8, "bold"), padx=9, pady=3, cursor="hand2"
    )
    btn_rescan_lvl.pack(side="right", padx=3)
    _bind_hover(btn_rescan_lvl, C_BTN_DARK, C_BTN_HOVER)

    btn_guide = tk.Button(
        lvl_bar, text="存放规范说明", command=_show_split_guide_popup,
        bg=C_BTN_DARK, fg=C_TEXT_MAIN, relief="flat", bd=0, font=(FONT_UI, 8), padx=9, pady=3, cursor="hand2"
    )
    btn_guide.pack(side="right", padx=3)
    _bind_hover(btn_guide, C_BTN_DARK, C_BTN_HOVER)

    grid_lvl = tk.Frame(card_lvl, bg=C_CARD_BG, padx=14, pady=8)
    grid_lvl.pack(fill="x")
    grid_lvl.columnconfigure(1, weight=1)
    grid_lvl.columnconfigure(4, weight=1)

    for idx, (k, base_sfx, _, label_txt, _) in enumerate(SUBLEVEL_ROLE_SPECS):
        r_idx = idx // 2
        c_idx = (idx % 2) * 3

        tk.Label(
            grid_lvl, text=f"{label_txt}:", anchor="e", fg=C_TEXT_SUB, bg=C_CARD_BG, font=(FONT_UI, 9)
        ).grid(row=r_idx, column=c_idx, sticky="e", padx=(4, 6), pady=4)

        sv = tk.StringVar(master=win, value=", ".join(cls_lvls.get(k, [])))
        lvl_StringVars[k] = sv

        ent = tk.Entry(
            grid_lvl, textvariable=sv, bg=C_INPUT_BG, fg=C_TEXT_MAIN,
            insertbackground="#FFFFFF", relief="flat", highlightbackground=C_INPUT_BORDER, highlightcolor=C_ACCENT_CYAN, highlightthickness=1,
            font=(FONT_MONO, 9)
        )
        ent.grid(row=r_idx, column=c_idx + 1, sticky="ew", padx=2, pady=4, ipady=3)

        mb = tk.Menubutton(
            grid_lvl, text="选择关卡 ▾", bg=C_BTN_DARK, fg=C_TEXT_MAIN,
            activebackground=C_BTN_HOVER, activeforeground="#FFFFFF",
            relief="flat", bd=0, font=(FONT_UI, 8), padx=8, pady=3, cursor="hand2"
        )
        menu_popup = tk.Menu(mb, tearoff=0, bg="#1C1F26", fg=C_TEXT_MAIN, activebackground=C_ACCENT_BLUE)
        mb.config(menu=menu_popup)
        lvl_Menus[k] = menu_popup
        mb.grid(row=r_idx, column=c_idx + 2, sticky="w", padx=(3, 18), pady=4)

    _refresh_sublevel_widgets()

    # ----------------- 第三区：04 MRQ 渲染配置文件绑定矩阵 -----------------
    card_mrq = tk.Frame(win, bg=C_CARD_BG, highlightbackground=C_CARD_BORDER, highlightcolor=C_CARD_BORDER, highlightthickness=1)
    card_mrq.pack(fill="x", padx=14, pady=4)

    hdr_mrq = tk.Frame(card_mrq, bg=C_CARD_HEADER, padx=12, pady=6)
    hdr_mrq.pack(fill="x")
    tk.Label(hdr_mrq, text="04  |  MRQ 渲染配置文件绑定 (RENDER PRESET BINDINGS)", fg=C_ACCENT_AMBER, bg=C_CARD_HEADER, font=(FONT_UI, 9, "bold")).pack(side="left")

    preset_vars = {}
    preset_entries = {}
    preset_badges = {}
    preset_menus = {}

    def _evaluate_and_sync_preset_slot(slot_key, *args):
        pv = preset_vars.get(slot_key)
        lbl_b = preset_badges.get(slot_key)
        ent_w = preset_entries.get(slot_key)
        if not pv or not lbl_b:
            return

        val = pv.get().strip()
        is_valid = bool(val and val.startswith("/") and pipe.asset_sub.does_asset_exist(val))

        if is_valid:
            lbl_b.config(text="● 已绑定", fg=C_ACCENT_GREEN)
            if ent_w:
                ent_w.config(fg=C_ACCENT_GREEN)
        elif not val or "未绑定" in val or "未找到" in val:
            lbl_b.config(text="● 未绑定", fg=C_ACCENT_RED)
            if ent_w:
                ent_w.config(fg=C_TEXT_MUTED)
        else:
            lbl_b.config(text="● 路径无效", fg=C_ACCENT_RED)
            if ent_w:
                ent_w.config(fg=C_ACCENT_RED)

        c = pipe.load_config()
        if "mrq_preset_paths" not in c or not isinstance(c.get("mrq_preset_paths"), dict):
            c["mrq_preset_paths"] = {}
        c["mrq_preset_paths"][slot_key] = val if is_valid else ""
        pipe.save_config(c)

    def _bind_preset_path_to_slot(slot_key, pkg_path):
        preset_vars[slot_key].set(pkg_path)

    def _clear_preset_slot(slot_key):
        preset_vars[slot_key].set("")

    def _auto_rescan_presets():
        new_p, new_cands = pipe.find_mrq_presets(force_rescan=True)
        _populate_preset_dropdowns(new_cands)
        for pk, p_obj in new_p.items():
            if p_obj:
                preset_vars[pk].set(p_obj.get_path_name().split('.')[0])
            else:
                preset_vars[pk].set("")

    btn_rescan_mrq = tk.Button(
        hdr_mrq, text="重新自动匹配三大预设", command=_auto_rescan_presets,
        bg=C_BTN_DARK, fg=C_ACCENT_CYAN, relief="flat", bd=0, font=(FONT_UI, 8, "bold"), padx=10, pady=2, cursor="hand2"
    )
    btn_rescan_mrq.pack(side="right")
    _bind_hover(btn_rescan_mrq, C_BTN_DARK, C_BTN_HOVER)

    tk.Label(
        hdr_mrq, text=f"CVar 路径: {std_folders['cvar_dir']}  |  MPC 路径: {std_folders['collection_dir']}/MPC_Global_Emiss",
        fg=C_TEXT_MUTED, bg=C_CARD_HEADER, font=(FONT_MONO, 8)
    ).pack(side="right", padx=12)

    grid_mrq = tk.Frame(card_mrq, bg=C_CARD_BG, padx=14, pady=8)
    grid_mrq.pack(fill="x")
    grid_mrq.columnconfigure(2, weight=1)

    preset_rows = [
        ("beauty",      "主渲染预设 (AOV_RenderSet):",                presets.get("beauty")),
        ("id_actor",    "Actor ID 预设 (RenderSet_ID_Actor):",         presets.get("id_actor")),
        ("id_material", "材质 AOV 预设 (AOV_RenderSet_ID_Material):", presets.get("id_material")),
    ]

    for row_i, (p_key, p_label, p_obj) in enumerate(preset_rows):
        tk.Label(
            grid_mrq, text=p_label, anchor="w", fg=C_TEXT_MAIN, bg=C_CARD_BG, font=(FONT_UI, 9, "bold")
        ).grid(row=row_i, column=0, sticky="w", padx=(2, 8), pady=4)

        b_lbl = tk.Label(grid_mrq, text="", bg=C_INPUT_BG, font=(FONT_UI, 8, "bold"), padx=8, pady=2)
        b_lbl.grid(row=row_i, column=1, sticky="w", padx=(0, 6), pady=4)
        preset_badges[p_key] = b_lbl

        init_p = p_obj.get_path_name().split('.')[0] if p_obj else str(saved_preset_paths.get(p_key, "")).strip()
        pv = tk.StringVar(master=win, value=init_p)
        preset_vars[p_key] = pv

        p_ent = tk.Entry(
            grid_mrq, textvariable=pv, bg=C_INPUT_BG,
            fg=C_ACCENT_GREEN, insertbackground="#FFFFFF",
            relief="flat", highlightbackground=C_INPUT_BORDER, highlightcolor=C_ACCENT_CYAN, highlightthickness=1,
            font=(FONT_MONO, 9)
        )
        p_ent.grid(row=row_i, column=2, sticky="ew", padx=4, pady=4, ipady=3)
        preset_entries[p_key] = p_ent

        pv.trace_add("write", lambda *args, k=p_key: _evaluate_and_sync_preset_slot(k))
        _evaluate_and_sync_preset_slot(p_key)

        mb_p = tk.Menubutton(
            grid_mrq, text="选择预设 ▾", bg=C_ACCENT_BLUE, fg="#FFFFFF",
            activebackground="#106EBE", activeforeground="#FFFFFF",
            relief="flat", bd=0, font=(FONT_UI, 8, "bold"), padx=10, pady=3, cursor="hand2"
        )
        p_menu = tk.Menu(mb_p, tearoff=0, bg="#1C1F26", fg=C_TEXT_MAIN, activebackground=C_ACCENT_BLUE)
        mb_p.config(menu=p_menu)
        preset_menus[p_key] = p_menu
        mb_p.grid(row=row_i, column=3, sticky="w", padx=3, pady=4)

        def _make_pick_preset(target_key):
            def _pick():
                sel_assets = unreal.EditorUtilityLibrary.get_selected_assets()
                if not sel_assets:
                    _PopupToplevelMessage(win, "提示", "请先在 UE 内容浏览器中单击选中对应的 MRQ 预设资产（窗口无需关闭，可直接去 UE 点选）！")
                    return
                picked_obj = sel_assets[0]
                pkg_path = picked_obj.get_path_name().split('.')[0]
                _bind_preset_path_to_slot(target_key, pkg_path)
            return _pick

        btn_pick_p = tk.Button(
            grid_mrq, text="拾取UE选中", command=_make_pick_preset(p_key),
            bg=C_BTN_DARK, fg=C_TEXT_MAIN, relief="flat", bd=0, font=(FONT_UI, 8), padx=9, pady=3, cursor="hand2"
        )
        btn_pick_p.grid(row=row_i, column=4, sticky="w", padx=3, pady=4)
        _bind_hover(btn_pick_p, C_BTN_DARK, C_BTN_HOVER)

        btn_clr_p = tk.Button(
            grid_mrq, text="清空", command=lambda k=p_key: _clear_preset_slot(k),
            bg=C_BTN_DARK, fg=C_ACCENT_RED, relief="flat", bd=0, font=(FONT_UI, 8, "bold"), padx=8, pady=3, cursor="hand2"
        )
        btn_clr_p.grid(row=row_i, column=5, sticky="w", padx=(2, 2), pady=4)
        _bind_hover(btn_clr_p, C_BTN_DARK, C_BTN_HOVER)

    def _populate_preset_dropdowns(cand_list):
        for slot_k, p_m in preset_menus.items():
            p_m.delete(0, "end")
            if cand_list:
                for cp in cand_list:
                    short_n = os.path.basename(cp)
                    p_m.add_command(label=f"  {short_n}   ({cp})", command=lambda k=slot_k, p=cp: _bind_preset_path_to_slot(k, p))
                p_m.add_separator()
            p_m.add_command(label="  ✖ 清空此预设绑定", command=lambda k=slot_k: _clear_preset_slot(k))

    _populate_preset_dropdowns(all_preset_paths)

    # ----------------- 第四区：底部命令执行坞 (3 大核心按钮) -----------------
    btn_bar = tk.Frame(win, bg="#0E1013", highlightbackground=C_CARD_BORDER, highlightcolor=C_CARD_BORDER, highlightthickness=1, padx=12, pady=9)
    btn_bar.pack(fill="x", padx=14, pady=(5, 4))

    def _collect_sublevel_map():
        mp = {}
        for k, sv in lvl_StringVars.items():
            mp[k] = [x.strip() for x in sv.get().split(",") if x.strip()]
        return mp

    def _collect_ui_preset_paths():
        res = {}
        for k, pv in preset_vars.items():
            val = pv.get().strip()
            res[k] = val if (val.startswith("/") and pipe.asset_sub.does_asset_exist(val)) else ""
        return res

    def _on_split_and_queue():
        if getattr(sys, "_LL_IS_EXECUTING_ACTION", False):
            return
        sys._LL_IS_EXECUTING_ACTION = True
        try:
            ui_presets = _collect_ui_preset_paths()
            sel_mode = mode_var.get()
            use_emiss = bool(emiss_var.get())
            use_inc = bool(inc_ver_var.get())
            sub_map = _collect_sublevel_map()
            cur_seq_path = master_seq.get_path_name().split('.')[0] if master_seq else ""
            custom_out = linked_ue_dir_var.get().strip()
            ok, msg = pipe.execute_layer_split_and_queue(
                render_mode=sel_mode,
                master_seq_path=cur_seq_path,
                create_emiss_layer=use_emiss,
                custom_publish_dir=custom_out,
                auto_increment_version=use_inc,
                clear_existing_queue=False,
                custom_sublevel_map=sub_map,
                explicit_preset_paths=ui_presets
            )
            _sync_shot_linked_output_path(master_seq, prompt_if_missing=False)
            _PopupToplevelMessage(win, "分层入列完成" if ok else "执行提示", msg)
        finally:
            sys._LL_IS_EXECUTING_ACTION = False

    def _on_requeue_only():
        if getattr(sys, "_LL_IS_EXECUTING_ACTION", False):
            return
        chosen_ver_inc = _ask_requeue_version_strategy_popup(win)
        if chosen_ver_inc is None:
            return
        inc_ver_var.set(bool(chosen_ver_inc))

        sys._LL_IS_EXECUTING_ACTION = True
        try:
            ui_presets = _collect_ui_preset_paths()
            cur_seq_path = master_seq.get_path_name().split('.')[0] if master_seq else ""
            custom_out = linked_ue_dir_var.get().strip()
            ok, msg = pipe.requeue_existing_sequences(
                master_seq_path=cur_seq_path,
                custom_publish_dir=custom_out,
                auto_increment_version=bool(chosen_ver_inc),
                explicit_preset_paths=ui_presets
            )
            _sync_shot_linked_output_path(master_seq, prompt_if_missing=False)
            _PopupToplevelMessage(win, "重新入列完成" if ok else "重新入列提示", msg)
        finally:
            sys._LL_IS_EXECUTING_ACTION = False

    def _on_render_now():
        win.attributes('-topmost', False)
        topmost_var.set(False)
        ok, msg = pipe.start_mrq_local_render_directly()
        if not ok:
            _PopupToplevelMessage(win, "渲染提示", msg)

    btn_main_build = tk.Button(
        btn_bar,
        text="1. 生成分层序列并加入 MRQ 队列",
        command=_on_split_and_queue,
        bg="#107C41", fg="#FFFFFF", activebackground="#159650", activeforeground="#FFFFFF",
        font=(FONT_UI, 10, "bold"), relief="flat", bd=0, pady=8, cursor="hand2"
    )
    btn_main_build.pack(side="left", fill="x", expand=True, padx=(0, 5))
    _bind_hover(btn_main_build, "#107C41", "#159650")

    btn_requeue = tk.Button(
        btn_bar,
        text="2. 仅将已有分层重新加入 MRQ",
        command=_on_requeue_only,
        bg="#1D4ED8", fg="#FFFFFF", activebackground="#2563EB", activeforeground="#FFFFFF",
        font=(FONT_UI, 10, "bold"), relief="flat", bd=0, pady=8, cursor="hand2"
    )
    btn_requeue.pack(side="left", fill="x", expand=True, padx=5)
    _bind_hover(btn_requeue, "#1D4ED8", "#2563EB")

    btn_render_local = tk.Button(
        btn_bar,
        text="3. 直接启动本地渲染 (Render Local)",
        command=_on_render_now,
        bg="#D97706", fg="#FFFFFF", activebackground="#F59E0B", activeforeground="#FFFFFF",
        font=(FONT_UI, 10, "bold"), relief="flat", bd=0, pady=8, cursor="hand2"
    )
    btn_render_local.pack(side="left", fill="x", expand=True, padx=(5, 0))
    _bind_hover(btn_render_local, "#D97706", "#F59E0B")

    # ----------------- 第五区：底部创作者铭牌与社交主页跳转栏 (含 Bilibili #19a3d6) -----------------
    footer_bar = tk.Frame(win, bg="#0E1013", highlightbackground="#222630", highlightcolor="#222630", highlightthickness=1, padx=14, pady=6)
    footer_bar.pack(fill="x", padx=14, pady=(2, 10))

    tk.Label(
        footer_bar, text="AUTHOR", fg="#0E1013", bg=C_ACCENT_AMBER,
        font=(FONT_MONO, 8, "bold"), padx=6, pady=1
    ).pack(side="left")

    tk.Label(
        footer_bar, text=f"  {AUTHOR_NAME}", fg=C_TEXT_MAIN, bg="#0E1013",
        font=(FONT_UI, 9, "bold")
    ).pack(side="left")

    tk.Label(
        footer_bar, text="   |   VFX Pipeline & Unreal Engine Technical Artist", fg=C_TEXT_MUTED, bg="#0E1013",
        font=(FONT_UI, 8)
    ).pack(side="left")

    def _open_bilibili():
        webbrowser.open(AUTHOR_BILIBILI_URL)

    def _open_youtube():
        webbrowser.open(AUTHOR_YOUTUBE_URL)

    def _open_github():
        webbrowser.open(AUTHOR_GITHUB_URL)

    email_lbl_ref = [None]

    def _copy_and_open_email():
        try:
            win.clipboard_clear()
            win.clipboard_append(AUTHOR_EMAIL)
            if email_lbl_ref[0]:
                email_lbl_ref[0].config(text=f"✓ 已复制: {AUTHOR_EMAIL}")
                win.after(2000, lambda: email_lbl_ref[0].config(text=AUTHOR_EMAIL) if email_lbl_ref[0].winfo_exists() else None)
        except Exception:
            pass
        try:
            webbrowser.open(f"mailto:{AUTHOR_EMAIL}")
        except Exception:
            pass

    # 从右往左依次排列：Bilibili (位于 YouTube 右侧/后面) <- YouTube <- GitHub <- Email
    bili_pill, _ = _create_social_icon_pill(footer_bar, "bilibili", "Bilibili", _open_bilibili)
    bili_pill.pack(side="right", padx=(6, 0))

    yt_pill, _ = _create_social_icon_pill(footer_bar, "youtube", "YouTube", _open_youtube)
    yt_pill.pack(side="right", padx=6)

    gh_pill, _ = _create_social_icon_pill(footer_bar, "github", "GitHub", _open_github)
    gh_pill.pack(side="right", padx=6)

    em_pill, em_lbl = _create_social_icon_pill(footer_bar, "email", AUTHOR_EMAIL, _copy_and_open_email)
    em_pill.pack(side="right", padx=6)
    email_lbl_ref[0] = em_lbl

    win.update_idletasks()
    _enable_windows_dark_titlebar_and_pure_icon(win)

    req_w = max(1080, win.winfo_reqwidth() + 24)
    req_h = win.winfo_reqheight() + 14
    scr_w = win.winfo_screenwidth()
    scr_h = win.winfo_screenheight()
    pos_x = max(10, int((scr_w - req_w) / 2))
    pos_y = max(10, int((scr_h - req_h) / 2))
    win.geometry(f"{req_w}x{req_h}+{pos_x}+{pos_y}")
    win.minsize(req_w, req_h)

    if master_seq and not linked_ue_dir_var.get().strip():
        win.after(200, lambda: _sync_shot_linked_output_path(master_seq, prompt_if_missing=True))

    sys._LL_TK_PUMPING_LOCK = False
    sys._LL_IS_EXECUTING_ACTION = False

    def _slate_tick_pump(delta_time):
        if getattr(sys, "_LL_TK_PUMPING_LOCK", False) or getattr(sys, "_LL_IS_EXECUTING_ACTION", False):
            return
        cur_win = getattr(sys, "_LL_RENDER_TK_WIN", None)
        cur_tick = getattr(sys, "_LL_RENDER_TICK_HANDLE", None)
        if cur_win is None:
            if cur_tick is not None:
                try:
                    unreal.unregister_slate_post_tick_callback(cur_tick)
                except Exception:
                    pass
                sys._LL_RENDER_TICK_HANDLE = None
            return
        sys._LL_TK_PUMPING_LOCK = True
        try:
            if cur_win.winfo_exists():
                cur_win.update_idletasks()
                cur_win.update()
            else:
                sys._LL_RENDER_TK_WIN = None
        except Exception:
            sys._LL_RENDER_TK_WIN = None
        finally:
            sys._LL_TK_PUMPING_LOCK = False

    sys._LL_RENDER_TICK_HANDLE = unreal.register_slate_post_tick_callback(_slate_tick_pump)


def run_single_layer_workflow(master_seq_path="", include_emiss=False, publish_dir="", new_version=True):
    pipe = UERenderLayerPipeline()
    ok, _ = pipe.execute_layer_split_and_queue(
        render_mode="single", master_seq_path=str(master_seq_path).strip(),
        create_emiss_layer=bool(include_emiss), custom_publish_dir=str(publish_dir).strip(),
        auto_increment_version=bool(new_version)
    )
    return ok


def run_multi_layer_workflow(master_seq_path="", include_emiss=False, publish_dir="", new_version=True):
    pipe = UERenderLayerPipeline()
    ok, _ = pipe.execute_layer_split_and_queue(
        render_mode="multi", master_seq_path=str(master_seq_path).strip(),
        create_emiss_layer=bool(include_emiss), custom_publish_dir=str(publish_dir).strip(),
        auto_increment_version=bool(new_version)
    )
    return ok


if __name__ == "__main__":
    show_render_layer_dialog()