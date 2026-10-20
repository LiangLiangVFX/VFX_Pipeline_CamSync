# -*- coding: utf-8 -*-
"""
UE5.3/5.4 影视级镜头分层裂变与 Movie Render Queue (MRQ) 自动化调度中心 v5.1 Studio Pro
-------------------------------------------------------------------------
核心特性：
1. [100% 自动弹出 Movie Render Queue 面板]：
   - 解决 log_v11.txt 中 /Engine/Transient 临时对象被 AssetEditorSubsystem 忽略的问题；
   - 自动将队列同步至 /Shot/Collection/MRQ_ActiveQueue 真实资产并调用 open_editor_for_assets，100% 唤起并置顶 MRQ 面板。
2. [MRQ 预设绑定状态实时联动]：
   - 挂载 StringVar.trace_add("write") 实时监听：手动删空路径或点击「清空」按钮时，状态立即变为红色「● 未绑定」。
3. [UE5 Slate 工业级深色卡片 UI + 底部创作者与 GitHub / YouTube / Email 矢量图标跳转栏]。
-------------------------------------------------------------------------
Author: LiangLiangArtist
Contact: liangliangvfx@gmail.com
"""

import os
import re
import sys
import json
import ctypes
import subprocess
import webbrowser
import unreal

# =========================================================================
# 创作者与社交主页配置 (点击 UI 底部对应图标直接跳转)
# =========================================================================
AUTHOR_NAME        = "LiangLiangArtist"
AUTHOR_EMAIL       = "liangliangvfx@gmail.com"
AUTHOR_GITHUB_URL  = "https://github.com/LiangLiangVFX"
AUTHOR_YOUTUBE_URL = "https://www.youtube.com/@zhaol2259"

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

# MRQ GameOverrides 污染变量清理黑名单
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


# =========================================================================
# 渲染完成自动弹出输出目录监听器 & 窗口焦点辅助函数
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


def _bring_mrq_or_ue_window_to_front(tk_win=None):
    try:
        if tk_win and tk_win.winfo_exists():
            tk_win.attributes('-topmost', False)
            tk_win.lower()
    except Exception:
        pass

    try:
        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        for title_name in ("Movie Render Queue", "影片渲染队列"):
            hwnd = user32.FindWindowW(None, title_name)
            if hwnd:
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, SW_RESTORE)
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
                return

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        cur_pid = os.getpid()
        tk_hwnd = user32.GetParent(tk_win.winfo_id()) if (tk_win and tk_win.winfo_exists()) else 0

        def _enum_cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd) and hwnd != tk_hwnd:
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == cur_pid:
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        w_title = buf.value
                        if "Unreal Editor" in w_title or "Movie Render Queue" in w_title or "CamProject" in w_title:
                            user32.SetForegroundWindow(hwnd)
                            user32.BringWindowToTop(hwnd)
                            return False
            return True

        user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
    except Exception:
        pass


def _extract_output_dir_from_active_queue():
    try:
        mrq_sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        queue = mrq_sub.get_queue()
        if queue:
            for job in queue.get_jobs():
                preset = job.get_preset_origin() if hasattr(job, "get_preset_origin") else None
                if preset:
                    p_out = preset.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
                    if p_out and p_out.output_directory.path:
                        return str(p_out.output_directory.path)
                cfg = job.get_configuration()
                if cfg:
                    c_out = cfg.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
                    if c_out and c_out.output_directory.path:
                        return str(c_out.output_directory.path)
    except Exception:
        pass
    return getattr(sys, "_LL_LAST_RENDER_OUT_DIR", "")


def ensure_mrq_render_finish_monitor_active(target_out_dir=""):
    if target_out_dir:
        sys._LL_LAST_RENDER_OUT_DIR = os.path.normpath(target_out_dir).replace('\\', '/')

    try:
        mrq_sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        sys._LL_WAS_MRQ_RENDERING = bool(mrq_sub.is_rendering())
    except Exception:
        sys._LL_WAS_MRQ_RENDERING = False

    if getattr(sys, "_LL_MRQ_MONITOR_HANDLE", None) is not None:
        return

    def _mrq_watch_tick(delta_time):
        try:
            mrq_s = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
            cur_rendering = bool(mrq_s.is_rendering())
            was_rendering = getattr(sys, "_LL_WAS_MRQ_RENDERING", False)

            if cur_rendering and not was_rendering:
                sys._LL_WAS_MRQ_RENDERING = True
                detected_dir = _extract_output_dir_from_active_queue()
                if detected_dir:
                    sys._LL_LAST_RENDER_OUT_DIR = detected_dir
            elif not cur_rendering and was_rendering:
                sys._LL_WAS_MRQ_RENDERING = False
                out_dir = getattr(sys, "_LL_LAST_RENDER_OUT_DIR", "") or _extract_output_dir_from_active_queue()
                if out_dir and os.path.exists(out_dir):
                    open_folder_in_explorer(out_dir)
        except Exception:
            pass

    try:
        sys._LL_MRQ_MONITOR_HANDLE = unreal.register_slate_post_tick_callback(_mrq_watch_tick)
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

    def _get_existing_command_names_in_asset(self, asset_obj, cvar_lib):
        cmd_names = []
        if not asset_obj:
            return cmd_names

        if cvar_lib and hasattr(cvar_lib, "get_list_of_commands_from_preset"):
            try:
                raw_list = cvar_lib.get_list_of_commands_from_preset(asset_obj) or []
                for item in raw_list:
                    k = str(item).strip().split()[0]
                    if k and k not in cmd_names:
                        cmd_names.append(k)
            except Exception:
                pass

        if not cmd_names and hasattr(asset_obj, "get_saved_commands_as_string_array"):
            try:
                arr = asset_obj.get_saved_commands_as_string_array(False) or []
                for s in arr:
                    k = str(s).strip().split()[0]
                    if k and k not in cmd_names:
                        cmd_names.append(k)
            except Exception:
                pass

        return cmd_names

    def get_or_create_cvar_presets(self):
        cvar_cls = getattr(unreal, "ConsoleVariablesAsset", None)
        cvar_factory_cls = getattr(unreal, "ConsoleVariablesEditorFactory", None)
        cvar_lib = getattr(unreal, "ConsoleVariablesEditorFunctionLibrary", None)
        if not cvar_cls:
            return {}

        std_dirs = self.detect_project_standard_folders()
        target_folder = std_dirs["cvar_dir"]
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

            existing_cmd_names = self._get_existing_command_names_in_asset(asset_obj, cvar_lib)
            is_clean_and_exact = (len(existing_cmd_names) == 4 and set(existing_cmd_names) == expected_keys_set)

            if not is_clean_and_exact and cvar_lib:
                try:
                    if hasattr(cvar_lib, "copy_current_list_to_asset"):
                        cvar_lib.copy_current_list_to_asset(asset_obj)

                    all_polluted = self._get_existing_command_names_in_asset(asset_obj, cvar_lib)
                    cmds_to_purge = set(all_polluted) | set(existing_cmd_names) | set(POLLUTED_MRQ_CVARS) | expected_keys_set
                    if hasattr(cvar_lib, "remove_command_from_current_preset"):
                        for bad_cmd in cmds_to_purge:
                            if bad_cmd:
                                try:
                                    cvar_lib.remove_command_from_current_preset(str(bad_cmd).strip())
                                except Exception:
                                    pass

                    for cv_k, cv_v in cvar_dict.items():
                        if hasattr(cvar_lib, "add_validated_command_to_current_preset"):
                            cvar_lib.add_validated_command_to_current_preset(f"{cv_k} {cv_v}")

                    if hasattr(cvar_lib, "copy_current_list_to_asset"):
                        cvar_lib.copy_current_list_to_asset(asset_obj)

                    if hasattr(asset_obj, "set_variable_collection_description"):
                        desc_str = ", ".join([f"{k}={v}" for k, v in cvar_dict.items()])
                        asset_obj.set_variable_collection_description(f"[{asset_name}] {desc_str}")

                    self.asset_sub.save_asset(pkg_path, only_if_is_dirty=False)
                    any_written = True
                except Exception as e:
                    print(f"[RenderLayer] 清洗并写入 CVar 预设参数提示 ({asset_name}): {e}")

            created_assets[key] = asset_obj

        if any_written:
            try:
                world = unreal.EditorLevelLibrary.get_editor_world()
                for def_k, def_v in CVAR_DEFAULT_RESTORE.items():
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

    # =========================================================================
    # 4. 根治 log_v11.txt 第 125 行 Transient 拦截问题，100% 弹出 MRQ 面板
    # =========================================================================
    def open_mrq_panel_reliably(self):
        try:
            std_dirs = self.detect_project_standard_folders()
            col_dir = std_dirs["collection_dir"]
            if not self.asset_sub.does_directory_exist(col_dir):
                self.asset_sub.make_directory(col_dir)

            q_asset_name = "MRQ_ActiveQueue"
            q_pkg_path = f"{col_dir}/{q_asset_name}"

            cur_q = self.mrq_sub.get_queue()
            if cur_q and hasattr(cur_q, "set_is_dirty"):
                cur_q.set_is_dirty(False)

            q_asset = None
            if self.asset_sub.does_asset_exist(q_pkg_path):
                q_asset = self.asset_sub.load_asset(q_pkg_path)

            if not q_asset:
                pkg = unreal.create_package(q_pkg_path)
                q_asset = unreal.find_object(pkg, q_asset_name)
                if not q_asset:
                    q_asset = unreal.new_object(unreal.MoviePipelineQueue, outer=pkg, name=unreal.Name(q_asset_name))

            if q_asset and cur_q:
                if hasattr(q_asset, "copy_from"):
                    q_asset.copy_from(cur_q)
                if hasattr(q_asset, "set_is_dirty"):
                    q_asset.set_is_dirty(False)
                try:
                    self.asset_sub.save_loaded_asset(q_asset, only_if_is_dirty=False)
                except Exception:
                    pass

            asset_ed = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
            if asset_ed and q_asset:
                asset_ed.open_editor_for_assets([q_asset])

            active_q = self.mrq_sub.get_queue()
            if active_q and hasattr(active_q, "set_is_dirty"):
                active_q.set_is_dirty(False)

            _bring_mrq_or_ue_window_to_front(getattr(sys, "_LL_RENDER_TK_WIN", None))
            return True
        except Exception as e:
            print(f"[RenderLayer] 唤起 MRQ 面板提示: {e}")
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
        norm_out = os.path.normpath(output_dir).replace('\\', '/')
        if preset_asset:
            try:
                job.set_preset_origin(preset_asset)
            except Exception as e:
                print(f"[RenderLayer] 绑定预设提示: {e}")
        else:
            try:
                config = job.get_configuration()
                if config:
                    out_setting = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
                    if out_setting:
                        out_setting.output_directory = unreal.DirectoryPath(norm_out)
                        out_setting.file_name_format = "{sequence_name}.{frame_number}"
                        out_setting.zero_pad_frame_numbers = 4
            except Exception:
                pass

    def start_mrq_local_render_directly(self):
        queue = self.mrq_sub.get_queue()
        if not queue or len(queue.get_jobs()) == 0:
            return False, "当前 MRQ 渲染队列为空！请先点击底部绿色按钮生成并加入队列。"
        if self.mrq_sub.is_rendering():
            return False, "当前 Movie Render Queue 正在渲染中，请等待完成！"

        out_dir = _extract_output_dir_from_active_queue()
        ensure_mrq_render_finish_monitor_active(out_dir)

        try:
            executor = self.mrq_sub.render_queue_with_executor(unreal.MoviePipelinePIEExecutor)
            if executor and hasattr(executor, "on_executor_finished_delegate"):
                def _on_exec_done(exec_obj, success):
                    sys._LL_WAS_MRQ_RENDERING = False
                    target_d = getattr(sys, "_LL_LAST_RENDER_OUT_DIR", "") or _extract_output_dir_from_active_queue()
                    open_folder_in_explorer(target_d)

                try:
                    executor.on_executor_finished_delegate.add_callable(_on_exec_done)
                except Exception:
                    pass
            return True, "已成功启动 Movie Render Queue 本地渲染！渲染完成后将自动弹出输出文件夹。"
        except Exception as e:
            return False, f"启动渲染异常: {e}"

    def resolve_and_create_publish_render_dir(self, ep, shot, custom_ue_dir="", force_new_version=True, seq_names_to_clean=None):
        ue_root_dir = ""

        if custom_ue_dir and os.path.exists(custom_ue_dir):
            clean_custom = os.path.normpath(custom_ue_dir).replace('\\', '/')
            if clean_custom.lower().endswith("/render") and "/publish/v" in clean_custom.lower():
                os.makedirs(clean_custom, exist_ok=True)
                return clean_custom
            ue_root_dir = clean_custom

        if not ue_root_dir:
            cfg = self.load_config()
            shot_map = cfg.get("shot_disk_map", {})
            fbx_path = shot_map.get(f"{ep.upper()}_{shot}", "") or cfg.get("last_fbx_path", "")
            if fbx_path:
                chk = os.path.normpath(os.path.dirname(fbx_path)).replace('\\', '/')
                for _ in range(5):
                    if os.path.basename(chk).lower() == "ue":
                        ue_root_dir = chk
                        break
                    if os.path.exists(os.path.join(chk, "ue")):
                        ue_root_dir = os.path.join(chk, "ue").replace('\\', '/')
                        break
                    parent = os.path.dirname(chk)
                    if parent == chk:
                        break
                    chk = parent

                if ue_root_dir:
                    ue_root_dir = re.sub(r'/ep\d+/\d{3,5}/ue$', f"/{ep.lower()}/{shot}/ue", ue_root_dir, flags=re.IGNORECASE)

        if not ue_root_dir:
            import tkinter as tk
            from tkinter import filedialog
            chosen = filedialog.askdirectory(title=f"请选择 Shot {shot} 的 ue 目录 (如 X:/.../ep28/{shot}/ue)")
            if not chosen:
                return ""
            ue_root_dir = os.path.normpath(chosen).replace('\\', '/')

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
                    existing_versions.append((int(m.group(1)), d))

        if not existing_versions:
            target_v_str = "v001"
        else:
            existing_versions.sort(key=lambda x: x[0])
            latest_num, latest_name = existing_versions[-1]
            latest_render_dir = os.path.join(publish_dir, latest_name, "render").replace('\\', '/')

            has_rendered_files = False
            if os.path.exists(latest_render_dir):
                exr_or_png = [f for f in os.listdir(latest_render_dir) if f.lower().endswith(('.exr', '.png', '.jpg', '.jpeg'))]
                if len(exr_or_png) > 0:
                    has_rendered_files = True

            if has_rendered_files and force_new_version:
                target_v_str = f"v{latest_num + 1:03d}"
            else:
                target_v_str = latest_name

        final_render_dir = os.path.join(publish_dir, target_v_str, "render").replace('\\', '/')
        os.makedirs(final_render_dir, exist_ok=True)

        if not force_new_version and seq_names_to_clean and os.path.exists(final_render_dir):
            try:
                prefixes = tuple(f"{sn.lower()}." for sn in seq_names_to_clean)
                for f in os.listdir(final_render_dir):
                    if f.lower().startswith(prefixes) and f.lower().endswith(('.exr', '.png', '.jpg', '.jpeg')):
                        try:
                            os.remove(os.path.join(final_render_dir, f))
                        except Exception:
                            pass
            except Exception:
                pass

        return final_render_dir

    def requeue_existing_sequences(self, master_seq_path="", custom_publish_dir="",
                                   auto_increment_version=False, explicit_preset_paths=None):
        master_seq = self.get_active_master_sequence(master_seq_path, allow_content_browser_selection=True)
        if not master_seq:
            return False, "请先在顶部下拉框选择或在 Sequencer 中打开当前镜头的母版序列！"

        ep, shot = self.parse_ep_and_shot_from_seq(master_seq)
        master_pkg_path = master_seq.get_path_name().split('.')[0]
        shot_folder = os.path.dirname(master_pkg_path)

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
            force_new_version=auto_increment_version, seq_names_to_clean=seq_names
        )
        if not render_out_dir:
            return False, "未选择有效的 publish 输出目录。"

        ensure_mrq_render_finish_monitor_active(render_out_dir)

        presets, _ = self.find_mrq_presets(force_rescan=False, explicit_paths_override=explicit_preset_paths)
        self.prepare_and_save_preset_assets(presets, render_out_dir)

        queue = self.mrq_sub.get_queue()
        queue.delete_all_jobs()

        world = unreal.EditorLevelLibrary.get_editor_world()
        world_soft_path = unreal.SoftObjectPath(world.get_path_name())

        bound_summary = []
        for seq_obj, default_pk, sfx in queued_items:
            job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
            job.job_name = seq_obj.get_name()
            job.sequence = unreal.SoftObjectPath(seq_obj.get_path_name())
            job.map = world_soft_path

            final_pk = self.resolve_preset_key_for_sequence(seq_obj.get_name(), default_pk)
            target_preset = presets.get(final_pk)
            self.apply_preset_to_job_strictly(job, target_preset, render_out_dir)

            p_name = target_preset.get_name() if target_preset else f"未绑定({final_pk})"
            bound_summary.append(f"• {seq_obj.get_name():<22}  ➔  预设: [{p_name}]")

        self.open_mrq_panel_reliably()

        ver_mode_str = "自动递增新版本" if auto_increment_version else "直接替换当前版本"
        msg = (
            f"【已将现有 {len(queued_items)} 个序列重新加入 MRQ 队列并唤起面板】\n\n"
            f"• 版本策略: {ver_mode_str}\n"
            f"• 输出路径: {render_out_dir} (渲染完成后将自动弹出此文件夹)\n\n" + "\n".join(bound_summary)
        )
        return True, msg

    def execute_layer_split_and_queue(self, render_mode="multi", master_seq_path="",
                                      create_emiss_layer=False, custom_publish_dir="",
                                      auto_increment_version=True, clear_existing_queue=True,
                                      custom_sublevel_map=None, explicit_preset_paths=None):
        master_seq = self.get_active_master_sequence(master_seq_path, allow_content_browser_selection=True)
        if not master_seq:
            return False, "当前未打开任何母版镜头序列！\n请先在窗口顶部的【选择母版镜头 ▾】中选择一个主镜头序列。"

        is_single_mode = str(render_mode).strip().lower().startswith("single") or str(render_mode).strip() == "1"

        ep, shot = self.parse_ep_and_shot_from_seq(master_seq)
        master_pkg_path = master_seq.get_path_name().split('.')[0]
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
                self.inject_level_visibility_track(dup_seq, vis_lvls, all_levels, start_f, end_f_exc)

                if emiss_val is not None and global_mpc:
                    self.inject_mpc_control_track(dup_seq, global_mpc, emiss_val, start_f, end_f_exc)

                if cvar_asset_obj:
                    self.inject_sequencer_cvar_track(dup_seq, cvar_asset_obj, start_f, end_f_exc)

                self.asset_sub.save_asset(layer_seq_path, only_if_is_dirty=False)
                queued_jobs_info.append((dup_seq, preset_key, vis_lvls, suffix))

        seq_names = [s.get_name() for s, _, _, _ in queued_jobs_info]
        render_out_dir = self.resolve_and_create_publish_render_dir(
            ep, shot, custom_ue_dir=custom_publish_dir,
            force_new_version=auto_increment_version, seq_names_to_clean=seq_names
        )
        if not render_out_dir:
            return False, "未指定有效的 publish 输出目录。"

        ensure_mrq_render_finish_monitor_active(render_out_dir)

        presets, _ = self.find_mrq_presets(force_rescan=False, explicit_paths_override=explicit_preset_paths)
        self.prepare_and_save_preset_assets(presets, render_out_dir)

        queue = self.mrq_sub.get_queue()
        if clear_existing_queue:
            queue.delete_all_jobs()

        world = unreal.EditorLevelLibrary.get_editor_world()
        world_soft_path = unreal.SoftObjectPath(world.get_path_name())

        summary_lines = []
        for seq_obj, default_pk, lvls, sfx in queued_jobs_info:
            job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
            job.job_name = seq_obj.get_name()
            job.sequence = unreal.SoftObjectPath(seq_obj.get_path_name())
            job.map = world_soft_path

            final_pk = self.resolve_preset_key_for_sequence(seq_obj.get_name(), default_pk)
            target_preset = presets.get(final_pk)
            self.apply_preset_to_job_strictly(job, target_preset, render_out_dir)

            p_name = target_preset.get_name() if target_preset else f"未绑定({final_pk})"
            summary_lines.append(f"• {seq_obj.get_name():<22}  ➔  预设: [{p_name:<26}]  |  显示关卡: {lvls}")

        # 所有分层 Job 入列完毕后，同步保存至 MRQ_ActiveQueue.uasset 并直接唤起 MRQ 窗口
        self.open_mrq_panel_reliably()

        ver_mode_str = "自动递增新版本 (v001 -> v002)" if auto_increment_version else "直接替换当前版本 (覆盖旧图)"
        msg = (
            f"【Shot {shot} 场景分层与 MRQ 渲染队列已就绪（已自动唤起 MRQ 面板）】\n\n"
            f"• 时间线帧区间: {start_f:04d} ~ {end_f_inc:04d} (共 {end_f_inc - start_f + 1} 帧)\n"
            f"• 雾气与保底预设: CVar_HeightFog_Only / CVar_EasyFog_Only / CVar_Default_Restore (均严格只含 4 个 ShowFlag 参数)\n"
            f"• 输出版本策略: {ver_mode_str}\n"
            f"• 渲染输出目录: {render_out_dir}\n"
            f"• 自动弹窗状态: 已开启 (MRQ 全部渲染完成后将自动弹出此文件夹)\n\n"
            f"【队列序列与绑定预设核对 (共 {len(queued_jobs_info)} 层)】\n" + "\n".join(summary_lines)
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

    card = tk.Frame(top, bg="#1C1F26", highlightbackground="#2E3440", highlightthickness=1, padx=20, pady=16)
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


def _create_social_icon_pill(parent, platform_type, label_text, on_click_cmd, bg_norm="#1C1F26", bg_hover="#2A303C"):
    import tkinter as tk

    pill = tk.Frame(parent, bg=bg_norm, highlightbackground="#2E3440", highlightthickness=1, padx=8, pady=3, cursor="hand2")
    cv = tk.Canvas(pill, width=18, height=16, bg=bg_norm, highlightthickness=0, bd=0, cursor="hand2")
    cv.pack(side="left", padx=(0, 5))

    if platform_type == "github":
        cv.create_oval(1, 1, 15, 15, fill="#E5E9F0", outline="")
        cv.create_polygon(3, 5, 5, 2, 7, 5, fill="#14161A", outline="")
        cv.create_polygon(9, 5, 11, 2, 13, 5, fill="#14161A", outline="")
        cv.create_oval(4, 4, 12, 11, fill="#14161A", outline="")
        cv.create_rectangle(6, 10, 10, 15, fill="#14161A", outline="")
        fg_col = "#E5E9F0"
    elif platform_type == "youtube":
        cv.create_rectangle(1, 2, 17, 14, fill="#FF0000", outline="#FF0000")
        cv.create_polygon(7, 5, 7, 11, 13, 8, fill="#FFFFFF", outline="")
        fg_col = "#F3F4F6"
    else:
        cv.create_rectangle(1, 3, 16, 13, fill="#101216", outline="#38BDF8", width=1)
        cv.create_line(1, 3, 8, 9, 16, 3, fill="#38BDF8", width=1)
        fg_col = "#38BDF8"

    lbl = tk.Label(pill, text=label_text, fg=fg_col, bg=bg_norm, font=("Consolas", 8, "bold"), cursor="hand2")
    lbl.pack(side="left")

    def _on_enter(e):
        pill.config(bg=bg_hover, highlightbackground="#38BDF8")
        cv.config(bg=bg_hover)
        lbl.config(bg=bg_hover, fg="#FFFFFF")

    def _on_leave(e):
        pill.config(bg=bg_norm, highlightbackground="#2E3440")
        cv.config(bg=bg_norm)
        lbl.config(bg=bg_norm, fg=fg_col)

    for w in (pill, cv, lbl):
        w.bind("<Enter>", _on_enter)
        w.bind("<Leave>", _on_leave)
        w.bind("<Button-1>", lambda e: on_click_cmd())

    return pill, lbl


# =========================================================================
# 大厂工业级深色卡片 UI 主面板 (v5.1 Studio Pro)
# =========================================================================
def show_render_layer_dialog():
    import tkinter as tk

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    existing_win = getattr(sys, "_LL_RENDER_TK_WIN", None)
    if existing_win is not None:
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
    win.title(f"UE5 Render Layer & MRQ Pipeline Center  —  v5.1 Studio Pro  |  By {AUTHOR_NAME}")
    win.configure(bg=C_BG_MAIN)
    win.attributes('-topmost', True)
    win.resizable(True, True)

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

    # ----------------- 顶部 Header 与镜头上下文仪表盘 -----------------
    header_bar = tk.Frame(win, bg="#0E1013", highlightbackground=C_CARD_BORDER, highlightthickness=1, padx=16, pady=10)
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
        font=(FONT_UI, 8)
    ).pack(side="right", padx=(10, 0))

    tk.Label(title_row, text=" STUDIO PRO v5.1 ", fg="#0E1013", bg=C_ACCENT_CYAN, font=(FONT_MONO, 8, "bold"), padx=6, pady=1).pack(side="right")

    ctx_row = tk.Frame(header_bar, bg="#161920", highlightbackground="#252A34", highlightthickness=1, padx=12, pady=6)
    ctx_row.pack(fill="x")

    tk.Label(ctx_row, text="母版序列:", fg=C_TEXT_SUB, bg="#161920", font=(FONT_UI, 9)).pack(side="left")
    lbl_seq_badge = tk.Label(ctx_row, text="", fg=C_ACCENT_GREEN, bg="#101216", font=(FONT_MONO, 9, "bold"), padx=10, pady=2)
    lbl_seq_badge.pack(side="left", padx=(6, 16))

    tk.Label(ctx_row, text="时间线帧范围:", fg=C_TEXT_SUB, bg="#161920", font=(FONT_UI, 9)).pack(side="left")
    lbl_frame_badge = tk.Label(ctx_row, text="", fg=C_ACCENT_CYAN, bg="#101216", font=(FONT_MONO, 9, "bold"), padx=10, pady=2)
    lbl_frame_badge.pack(side="left", padx=(6, 12))

    def _update_seq_badges(seq_obj, sf, ef_inc):
        if seq_obj and sf is not None and ef_inc is not None:
            total_len = ef_inc - sf + 1
            lbl_seq_badge.config(text=f"● {seq_obj.get_name()}", fg=C_ACCENT_GREEN)
            lbl_frame_badge.config(text=f"{sf:04d} - {ef_inc:04d}  ({total_len} Frames)", fg=C_ACCENT_CYAN)
        else:
            lbl_seq_badge.config(text="● 未打开母版序列 (请从右侧选择)", fg=C_ACCENT_RED)
            lbl_frame_badge.config(text="---- ~ ----", fg=C_TEXT_MUTED)

    _update_seq_badges(master_seq, start_f, end_f_inc)

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
                _update_seq_badges(master_seq, start_f, end_f_inc)

    def _refresh_master_seq(allow_cb=True):
        nonlocal master_seq, start_f, end_f_inc
        master_seq = pipe.get_active_master_sequence(allow_content_browser_selection=allow_cb)
        if master_seq:
            try:
                unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(master_seq)
            except Exception:
                pass
        start_f, end_f_inc, _ = pipe.get_exact_timeline_range(master_seq)
        _update_seq_badges(master_seq, start_f, end_f_inc)

    def _open_current_output_dir():
        out_d = _extract_output_dir_from_active_queue()
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

    # ----------------- 第一区：01 分层渲染模式 + 02 版本策略双卡片 -----------------
    row1_container = tk.Frame(win, bg=C_BG_MAIN)
    row1_container.pack(fill="x", padx=14, pady=4)
    row1_container.columnconfigure(0, weight=3)
    row1_container.columnconfigure(1, weight=2)

    card_mode = tk.Frame(row1_container, bg=C_CARD_BG, highlightbackground=C_CARD_BORDER, highlightthickness=1)
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
        font=(FONT_UI, 9, "bold")
    ).pack(anchor="w", pady=2)

    tk.Radiobutton(
        body_mode,
        text="模式二：多层全拆分模式 [ env / key / sky / fill / heightfog / fog + 双ID ]",
        variable=mode_var, value="multi",
        fg=C_ACCENT_GREEN, bg=C_CARD_BG, selectcolor=C_INPUT_BG, activebackground=C_CARD_BG, activeforeground=C_ACCENT_GREEN,
        font=(FONT_UI, 9, "bold")
    ).pack(anchor="w", pady=2)

    tk.Checkbutton(
        body_mode,
        text="额外生成自发光层 (cam_emiss — 单层/多层均支持，自动挂载 MPC_Global_Emiss)",
        variable=emiss_var,
        fg=C_ACCENT_AMBER, bg=C_CARD_BG, selectcolor=C_INPUT_BG, activebackground=C_CARD_BG, activeforeground=C_ACCENT_AMBER,
        font=(FONT_UI, 9)
    ).pack(anchor="w", pady=(4, 2))

    card_ver = tk.Frame(row1_container, bg=C_CARD_BG, highlightbackground=C_CARD_BORDER, highlightthickness=1)
    card_ver.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

    hdr_ver = tk.Frame(card_ver, bg=C_CARD_HEADER, padx=12, pady=6)
    hdr_ver.pack(fill="x")
    tk.Label(hdr_ver, text="02  |  输出版本策略 (VERSIONING)", fg=C_ACCENT_AMBER, bg=C_CARD_HEADER, font=(FONT_UI, 9, "bold")).pack(side="left")
    tk.Label(hdr_ver, text="跑完自动弹出目录", fg=C_ACCENT_GREEN, bg=C_CARD_HEADER, font=(FONT_UI, 8, "bold")).pack(side="right")

    body_ver = tk.Frame(card_ver, bg=C_CARD_BG, padx=14, pady=8)
    body_ver.pack(fill="both", expand=True)

    tk.Radiobutton(
        body_ver,
        text="自动递增版本 (若 v001 已有图，自动新建 v002 / v003)",
        variable=inc_ver_var, value=True,
        fg=C_ACCENT_GREEN, bg=C_CARD_BG, selectcolor=C_INPUT_BG, activebackground=C_CARD_BG, activeforeground=C_ACCENT_GREEN,
        font=(FONT_UI, 9, "bold")
    ).pack(anchor="w", pady=3)

    tk.Radiobutton(
        body_ver,
        text="直接替换当前版本 (不建新目录，直接覆盖当前版本旧图)",
        variable=inc_ver_var, value=False,
        fg=C_TEXT_MAIN, bg=C_CARD_BG, selectcolor=C_INPUT_BG, activebackground=C_CARD_BG, activeforeground=C_ACCENT_AMBER,
        font=(FONT_UI, 9)
    ).pack(anchor="w", pady=3)

    tk.Label(body_ver, text="输出规范: .../epXX/shot/ue/publish/vXXX/render", fg=C_TEXT_MUTED, bg=C_CARD_BG, font=(FONT_MONO, 8)).pack(anchor="w", pady=(4, 0))

    # ----------------- 第二区：03 子关卡映射与一键拆层矩阵 -----------------
    card_lvl = tk.Frame(win, bg=C_CARD_BG, highlightbackground=C_CARD_BORDER, highlightthickness=1)
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
        insertbackground="#FFFFFF", relief="flat", highlightbackground=C_INPUT_BORDER, highlightthickness=1,
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
        insertbackground="#FFFFFF", relief="flat", highlightbackground=C_INPUT_BORDER, highlightthickness=1,
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
            insertbackground="#FFFFFF", relief="flat", highlightbackground=C_INPUT_BORDER, highlightthickness=1,
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
    card_mrq = tk.Frame(win, bg=C_CARD_BG, highlightbackground=C_CARD_BORDER, highlightthickness=1)
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
            relief="flat", highlightbackground=C_INPUT_BORDER, highlightthickness=1,
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

    # ----------------- 第四区：底部命令执行坞 -----------------
    btn_bar = tk.Frame(win, bg="#0E1013", highlightbackground=C_CARD_BORDER, highlightthickness=1, padx=12, pady=9)
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
        ui_presets = _collect_ui_preset_paths()
        sel_mode = mode_var.get()
        use_emiss = bool(emiss_var.get())
        use_inc = bool(inc_ver_var.get())
        sub_map = _collect_sublevel_map()
        cur_seq_path = master_seq.get_path_name().split('.')[0] if master_seq else ""
        win.attributes('-topmost', False)
        topmost_var.set(False)
        ok, msg = pipe.execute_layer_split_and_queue(
            render_mode=sel_mode,
            master_seq_path=cur_seq_path,
            create_emiss_layer=use_emiss,
            auto_increment_version=use_inc,
            clear_existing_queue=True,
            custom_sublevel_map=sub_map,
            explicit_preset_paths=ui_presets
        )
        if not ok:
            _PopupToplevelMessage(win, "执行提示", msg)

    def _on_requeue_only():
        ui_presets = _collect_ui_preset_paths()
        use_inc = bool(inc_ver_var.get())
        cur_seq_path = master_seq.get_path_name().split('.')[0] if master_seq else ""
        win.attributes('-topmost', False)
        topmost_var.set(False)
        ok, msg = pipe.requeue_existing_sequences(
            master_seq_path=cur_seq_path,
            auto_increment_version=use_inc,
            explicit_preset_paths=ui_presets
        )
        if not ok:
            _PopupToplevelMessage(win, "重新入列提示", msg)

    def _on_open_mrq_only():
        win.attributes('-topmost', False)
        topmost_var.set(False)
        pipe.open_mrq_panel_reliably()

    def _on_render_now():
        win.attributes('-topmost', False)
        topmost_var.set(False)
        ok, msg = pipe.start_mrq_local_render_directly()
        if not ok:
            _PopupToplevelMessage(win, "渲染提示", msg)

    btn_main_build = tk.Button(
        btn_bar,
        text="1. 生成分层序列并弹出 MRQ 队列",
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

    btn_open_mrq = tk.Button(
        btn_bar,
        text="3. 唤起 MRQ 队列面板",
        command=_on_open_mrq_only,
        bg=C_BTN_DARK, fg=C_ACCENT_CYAN, activebackground=C_BTN_HOVER, activeforeground="#FFFFFF",
        font=(FONT_UI, 10, "bold"), relief="flat", bd=0, pady=8, cursor="hand2"
    )
    btn_open_mrq.pack(side="left", fill="x", expand=True, padx=5)
    _bind_hover(btn_open_mrq, C_BTN_DARK, C_BTN_HOVER)

    btn_render_local = tk.Button(
        btn_bar,
        text="4. 直接启动本地渲染 (Render Local)",
        command=_on_render_now,
        bg="#D97706", fg="#FFFFFF", activebackground="#F59E0B", activeforeground="#FFFFFF",
        font=(FONT_UI, 10, "bold"), relief="flat", bd=0, pady=8, cursor="hand2"
    )
    btn_render_local.pack(side="left", fill="x", expand=True, padx=(5, 0))
    _bind_hover(btn_render_local, "#D97706", "#F59E0B")

    # ----------------- 第五区：底部创作者铭牌与社交主页跳转栏 -----------------
    footer_bar = tk.Frame(win, bg="#0E1013", highlightbackground="#222630", highlightthickness=1, padx=14, pady=6)
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

    yt_pill, _ = _create_social_icon_pill(footer_bar, "youtube", "YouTube", _open_youtube)
    yt_pill.pack(side="right", padx=(6, 0))

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

    def _slate_tick_pump(delta_time):
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
        try:
            if cur_win.winfo_exists():
                cur_win.update_idletasks()
                cur_win.update()
            else:
                sys._LL_RENDER_TK_WIN = None
        except Exception:
            sys._LL_RENDER_TK_WIN = None

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