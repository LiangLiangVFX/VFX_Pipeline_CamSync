# -*- coding: utf-8 -*-
"""
UE5.3/5.4 影视级镜头分层裂变与 Movie Render Queue (MRQ) 自动化调度中心 v3.1
-------------------------------------------------------------------------
针对 7 大细节问题的全面精准修复：
1. [母版镜头下拉严格过滤]：彻底过滤所有带分层后缀 (_env/_key/_sky/_fog/_id_actor等) 的子序列，仅显示干净的母版主镜头名。
2. [帧区间精准修正 (不再多1帧)]：区分 UE 内部排他上限 (ExclusiveUpper) 与真实包含结束帧 (InclusiveEnd = ExclusiveUpper - 1)。
3. [MRQ 预设精准识别 & UI 完整显示]：
   - 修正 AOV_RenderSet 因带 AOV 前缀被误判为材质预设的 Bug；
   - 严格对应：AOV_RenderSet (主预设)、RenderSet_ID_Actor (Actor预设)、AOV_RenderSet_ID_Material (材质预设)；
   - 修复 UI 标签左侧『🌈 材』字被裁切的问题。
4. [ConsoleVariablesAsset 真实参数写入]：使用 unreal.ConsoleVariablesEditorAssetSaveData 结构体真实写入并勾选 5 大控制台变量。
5. [扫描/创建 0 卡顿]：扫描改为 100% 纯只读模式，绝不重复调用 add_level_to_world，彻底告别 Adding level to world 卡死。
6. [100% 自动弹出 MRQ 面板]：在写入队列前通过内存级 MoviePipelineQueue 实例触发 OpenAssetEditor 直接唤起 MRQ 窗口。
-------------------------------------------------------------------------
Author: LiangLiangArtist
Contact: liangliangvfx@gmail.com
"""

import os
import re
import json
import ctypes
import unreal

CONFIG_FILE_PATH = os.path.normpath(os.path.join(unreal.Paths.project_saved_dir(), "UECamWorkflowConfig.json"))

_GLOBAL_TK_WIN = None
_GLOBAL_GUIDE_WIN = None
_SLATE_TICK_HANDLE = None

# 标准子关卡后缀与存放规范
SUBLEVEL_ROLE_SPECS = [
    ("scence",    "scence",      "Map/Scence", "🏛️ 场景模型层 (scence):",      "静态网格体(StaticMesh)、地形(Landscape)、建筑、植被 (★不移动模型，直接引用场景关卡)"),
    ("env",       "env_lgt",     "Map/Light",  "🌤️ 环境天光层 (env):",         "仅存放天光 (SkyLight)"),
    ("key",       "key_lgt",     "Map/Light",  "☀️ 主方向光层 (key):",         "仅存放主平行光 (DirectionalLight 太阳光/月光)"),
    ("sky",       "sky_lgt",     "Map/Light",  "🌌 纯天空层 (sky,不含场景):",  "天空球 (SM_SkySphere/BP_Sky)、大气 (SkyAtmosphere)、体积云"),
    ("heightfog", "heightfog",   "Map/Light",  "🌫️ 指数高度雾 (heightfog):",   "指数高度雾 (ExponentialHeightFog)"),
    ("fill",      "fill01_lgt",  "Map/Light",  "💡 场景补光层 (fill):",        "场景局部补光：点光源(PointLight)、聚光灯(SpotLight)、矩形光(RectLight)"),
    ("fog",       "fog",         "Map/Light",  "☁️ 半透明雾片 (fog):",         "EasyFog 雾片蓝图、局部半透明雾气面片"),
]

# UE 5.3 / 5.4 官方控制台变量默认值与雾层配置值
CVAR_DEFAULT_RESTORE = {
    "ShowFlag.Diffuse": 2.0,       # 官方默认 2 (正常开启漫反射)
    "ShowFlag.Specular": 2.0,      # 官方默认 2 (正常开启高光反射)
    "ShowFlag.Translucency": 2.0,  # 官方默认 2 (正常开启半透明)
    "ShowFlag.Fog": 2.0,           # 官方默认 2 (正常开启高度雾)
    "r.LocalHeightFog": 1.0        # 官方默认 1 (正常开启局部高度雾)
}

CVAR_HEIGHTFOG_LAYER = {
    "ShowFlag.Diffuse": 0.0,       # 关闭场景物体漫反射，使模型变纯黑遮挡 Holdout
    "ShowFlag.Specular": 0.0,      # 关闭场景高光反射，保证雾气干净度
    "ShowFlag.Translucency": 0.0,  # 关闭半透明开关，剔除半透明雾片
    "r.LocalHeightFog": 0.0,       # 关闭局部高度雾
    "ShowFlag.Fog": 2.0            # 开启高度雾开关，单独渲染纯净指数高度雾
}

CVAR_EASYFOG_LAYER = {
    "ShowFlag.Diffuse": 0.0,       # 关闭场景物体漫反射，使模型变纯黑遮挡 Holdout
    "ShowFlag.Specular": 0.0,      # 关闭场景高光反射
    "ShowFlag.Translucency": 2.0,  # 开启半透明开关，单独渲染半透明雾片 (EasyFog)
    "r.LocalHeightFog": 0.0,       # 关闭局部高度雾
    "ShowFlag.Fog": 0.0            # 关闭所有高度雾
}

# 用于严格判定某个 Sequence 是否为派生子序列的后缀集合
DERIVED_SEQ_SUFFIXES = (
    "_env", "_key", "_sky", "_heightfog", "_expfog", "_fill", "_fog", "_easyfog",
    "_emiss", "_emi", "_id_actor", "_id_material", "_actor", "_material", "_aov", "_lgt"
)


class UERenderLayerPipeline(object):
    def __init__(self):
        self.asset_sub = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
        self.actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        self.mrq_sub = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
        self.asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        self.asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()

    # =========================================================================
    # 0. 配置文件读写与项目标准目录自动推导
    # =========================================================================
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
        media_dir = f"{proj_root.rstrip('/')}/Shot/MediaPlayer"

        if not self.asset_sub.does_directory_exist(scence_dir) and self.asset_sub.does_directory_exist(f"{proj_root.rstrip('/')}/Map/Scene"):
            scence_dir = f"{proj_root.rstrip('/')}/Map/Scene"

        return {
            "proj_root": proj_root,
            "light_dir": light_dir,
            "scence_dir": scence_dir,
            "media_dir": media_dir
        }

    # =========================================================================
    # 1. 【解决第 1 & 第 2 个问题】：母版镜头严格过滤 + 真实帧区间修正（不再多1帧）
    # =========================================================================
    def is_derived_layer_sequence_name(self, seq_short_name):
        """
        严格判断一个 Sequence 名称是否为分层派生子序列：
        - 凡是以 _env, _key, _sky, _heightfog, _fill, _fog, _emiss, _id_actor, _id_material 等结尾的一律排除；
        - 凡是形如 cam2220_xxx (在 cam+数字 后面还有下划线后缀) 的一律视为派生子序列排除！
        """
        low = str(seq_short_name).strip().lower()
        if any(low.endswith(sfx) for sfx in DERIVED_SEQ_SUFFIXES):
            return True
        if re.search(r'cam\d+_[a-zA-Z]+', low):
            return True
        return False

    def list_all_master_sequences_in_project(self):
        """
        扫描工程中所有的【母版主镜头 LevelSequence】：
        返回列表 [(short_name, pkg_path), ...]，下拉框只展示干净的主镜头名 (如 ep28_cam2220)！
        """
        result_map = {}
        try:
            all_assets = self.asset_reg.get_all_assets()
            for ad in all_assets:
                cls_str = str(getattr(ad, "asset_class_path", getattr(ad, "asset_class", ""))).lower()
                if "levelsequence" in cls_str:
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
        """
        【解决第 2 个问题：为什么母版镜头的帧区间多一帧？】
        在 UE5 Python API 中，level_seq.get_playback_end() 返回的是左闭右开区间的排他上限 (ExclusiveUpper = 实际最后一帧 + 1)！
        例如镜头实际是 0001 ~ 0022，get_playback_end() 会返回 23。
        因此：
        - start_f          : 起始帧 (如 1)
        - end_f_inclusive  : 真实包含的最后一帧 = end_f_exclusive - 1 (如 22，用于 UI 显示与核对，不再多 1 帧！)
        - end_f_exclusive  : 内部轨道排他上限 (如 23，用于 sec.set_range(start_f, end_f_exclusive) 铺满第 22 帧整帧)
        """
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

    # =========================================================================
    # 2. 【解决第 7 个问题】：100% 纯只读扫描子关卡，彻底废除扫描时调用 add_level_to_world
    # =========================================================================
    def scan_mounted_and_folder_sublevels(self, custom_light_dir="", custom_scence_dir=""):
        """
        纯只读极速扫描（0.01秒完成，绝不调用 add_level_to_world，彻底杜绝卡在 Adding level to world！）：
        1. 扫描当前 World 已加载的子关卡；
        2. 扫描 Map/Light 与 Map/Scence 文件夹下的所有 .umap 关卡文件名；
        3. 自动按命名与内部 Actor 特征归类。
        """
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
                    if short_name.lower() != persistent_name and short_name not in mounted_sublevels:
                        mounted_sublevels.append(short_name)
        except Exception:
            pass

        # 纯只读扫描 Map/Light 与 Map/Scence 下的 .umap 文件名（绝不调用 add_level_to_world！）
        folder_map_names = []
        for check_folder in [scence_dir, light_dir]:
            if check_folder and self.asset_sub.does_directory_exist(check_folder):
                assets = self.asset_sub.list_assets(check_folder, recursive=True)
                for ap in assets:
                    pkg_p = ap.split('.')[0]
                    if pkg_p.lower() == world_pkg.lower():
                        continue
                    ad = self.asset_sub.find_asset_data(ap)
                    cls_n = str(getattr(ad, "asset_class_path", getattr(ad, "asset_class", ""))).lower()
                    if "world" in cls_n or "level" in cls_n:
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
            "scence": [],
            "env": [],
            "key": [],
            "sky": [],
            "heightfog": [],
            "fill": [],
            "fog": [],
            "others": []
        }

        all_candidate_names = list(mounted_sublevels)
        for fn in folder_map_names:
            if fn not in all_candidate_names:
                all_candidate_names.append(fn)

        for lname in all_candidate_names:
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
            for k in ["scence", "env", "key", "sky", "heightfog", "fill", "fog"]:
                if k in saved_map and saved_map[k]:
                    valid_saved = [dn for dn in saved_map[k] if dn in all_candidate_names]
                    if valid_saved:
                        classified[k] = valid_saved

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
        """
        【解决第 7 个问题】：
        1. 绝不对 Map/Scence 下的场景大关卡调用 add_level_to_world（防止卡在 Adding level to world）；
        2. 在 Map/Light 下创建 6 个灯光/雾子关卡时，若子关卡文件已存在 (does_asset_exist) 或已在世界中，
           直接复用，绝不重复调用 add_level_to_world！
        """
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

        # 1. 只读记录已有的 scence 关卡名（绝不调用 add_level_to_world 挂载大场景关卡！）
        for mounted_low, lvl_obj in existing_level_objs.items():
            real_n = lvl_obj.get_outer().get_name()
            if ("scence" in mounted_low or "scene" in mounted_low) and real_n not in final_mapping["scence"]:
                final_mapping["scence"].append(real_n)

        if not final_mapping["scence"] and self.asset_sub.does_directory_exist(target_scence_dir):
            for ap in self.asset_sub.list_assets(target_scence_dir, recursive=True):
                pkg_p = ap.split('.')[0]
                short_n = os.path.basename(pkg_p)
                if short_n not in final_mapping["scence"]:
                    final_mapping["scence"].append(short_n)

        # 2. 在 Map/Light 下仅针对【尚不存在】的灯光/雾子关卡调用 create_new_streaming_level
        light_roles = [spec for spec in SUBLEVEL_ROLE_SPECS if spec[0] != "scence"]
        newly_created_count = 0
        for role_key, base_suffix, _, _, _ in light_roles:
            sub_name = f"{clean_prefix}{base_suffix}"
            sub_pkg_path = f"{target_light_dir}/{sub_name}"

            # 如果已经在世界中或者磁盘上已存在该 .umap，直接记录名字，绝不重复调用 add_level_to_world 卡死！
            if sub_name.lower() in existing_level_objs or self.asset_sub.does_asset_exist(sub_pkg_path):
                created_or_loaded_map[role_key] = (sub_name, existing_level_objs.get(sub_name.lower()))
                final_mapping[role_key].append(sub_name)
                continue

            try:
                lvl_stream = unreal.EditorLevelUtils.create_new_streaming_level(streaming_cls, sub_pkg_path, False)
                created_or_loaded_map[role_key] = (sub_name, lvl_stream)
                newly_created_count += 1
            except Exception as e:
                print(f"[RenderLayer] 创建子关卡 {sub_name} 提示: {e}")

            final_mapping[role_key].append(sub_name)

        # 3. 若勾选了自动归类，仅将主关卡中的 6 类轻量灯光/天空/雾 Actor 移入对应子关卡（绝不移动 scence 模型！）
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
            lines = [f"• {clean_prefix}{sfx:<14} : 已自动移入 {moved_counts[rk]} 个灯光/雾 Actor" for rk, sfx, _, _, _ in light_roles]
            lines.append("• scence (场景模型) : 已按规范跳过移动，0 卡顿！")
            lines.append("• PostProcessVolume / 相机 : 已按规范保留在主渲染关卡！")
            msg = f"✅ 灯光/雾子关卡映射与自动归类完成（新创建 {newly_created_count} 个，已存在自动跳过挂载）：\n\n" + "\n".join(lines)
        else:
            lines = [f"• {clean_prefix}{sfx:<14}  ➔  {desc}" for _, sfx, _, _, desc in light_roles]
            msg = f"✅ 灯光/雾子关卡就绪（新创建 {newly_created_count} 个，已存在的子关卡已自动识别映射）：\n\n" + "\n".join(lines)

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
    # 3. 【解决第 5 个问题】：使用 ConsoleVariablesEditorAssetSaveData 结构体真实填充 ConsoleVariablesAsset
    # =========================================================================
    def get_or_create_cvar_presets(self):
        """
        自动创建并真实填充 3 个 ConsoleVariablesAsset 资产：
        使用 UE 5.3/5.4 标准结构体 unreal.ConsoleVariablesEditorAssetSaveData(command_name, command_value_as_string, checked_state)
        """
        cvar_cls = getattr(unreal, "ConsoleVariablesAsset", None)
        cvar_factory_cls = getattr(unreal, "ConsoleVariablesEditorFactory", None)
        save_data_cls = getattr(unreal, "ConsoleVariablesEditorAssetSaveData", None)
        if not cvar_cls or not cvar_factory_cls:
            return {}

        std_dirs = self.detect_project_standard_folders()
        target_folder = f"{std_dirs['light_dir']}/CVarPresets"
        if not self.asset_sub.does_directory_exist(target_folder):
            self.asset_sub.make_directory(target_folder)

        specs = {
            "heightfog": ("CVar_HeightFog_Only",  CVAR_HEIGHTFOG_LAYER),
            "fog":       ("CVar_EasyFog_Only",    CVAR_EASYFOG_LAYER),
            "restore":   ("CVar_Default_Restore", CVAR_DEFAULT_RESTORE),
        }

        created_assets = {}
        for key, (asset_name, cvar_dict) in specs.items():
            pkg_path = f"{target_folder}/{asset_name}"
            if self.asset_sub.does_asset_exist(pkg_path):
                asset_obj = self.asset_sub.load_asset(pkg_path)
            else:
                try:
                    asset_obj = self.asset_tools.create_asset(asset_name, target_folder, cvar_cls, cvar_factory_cls())
                except Exception:
                    asset_obj = None

            if asset_obj and save_data_cls:
                try:
                    saved_list = []
                    chk_state = getattr(unreal.CheckBoxState, "CHECKED", None) if hasattr(unreal, "CheckBoxState") else None

                    for cv_k, cv_v in cvar_dict.items():
                        item = save_data_cls()
                        item.set_editor_property("command_name", str(cv_k))
                        item.set_editor_property("command_value_as_string", str(cv_v))
                        if chk_state is not None:
                            try:
                                item.set_editor_property("checked_state", chk_state)
                            except Exception:
                                pass
                        saved_list.append(item)

                    # 方式 1：调用官方 replace_saved_commands 方法整表写入
                    if hasattr(asset_obj, "replace_saved_commands"):
                        asset_obj.replace_saved_commands(saved_list)
                    # 方式 2：逐条调用 add_or_set_console_variable_saved_data(item)
                    elif hasattr(asset_obj, "add_or_set_console_variable_saved_data"):
                        for item in saved_list:
                            asset_obj.add_or_set_console_variable_saved_data(item)
                    # 方式 3：直接设置 saved_commands 属性
                    else:
                        asset_obj.set_editor_property("saved_commands", saved_list)

                    self.asset_sub.save_asset(pkg_path, only_if_is_dirty=False)
                except Exception as e:
                    print(f"[RenderLayer] 写入 ConsoleVariablesAsset ({asset_name}) 提示: {e}")

            if asset_obj:
                created_assets[key] = asset_obj

        return created_assets

    def get_or_create_global_emiss_mpc(self):
        std_dirs = self.detect_project_standard_folders()
        mpc_folder = std_dirs["media_dir"]
        if not self.asset_sub.does_directory_exist(mpc_folder):
            self.asset_sub.make_directory(mpc_folder)

        mpc_name = "MPC_Global_Emiss"
        mpc_path = f"{mpc_folder}/{mpc_name}"

        if self.asset_sub.does_asset_exist(mpc_path):
            mpc_asset = self.asset_sub.load_asset(mpc_path)
        else:
            mpc_factory = unreal.MaterialParameterCollectionFactoryNew()
            mpc_asset = self.asset_tools.create_asset(
                mpc_name, mpc_folder, unreal.MaterialParameterCollection, mpc_factory
            )

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
                self.asset_sub.save_asset(mpc_path, only_if_is_dirty=False)
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

    def strip_media_tracks(self, level_seq):
        try:
            for track in list(level_seq.get_tracks()):
                if isinstance(track, unreal.MovieSceneMediaTrack):
                    level_seq.remove_track(track)
        except Exception:
            pass

    def inject_level_visibility_track(self, level_seq, visible_levels, all_levels, start_frame, end_frame_exclusive):
        try:
            for track in list(level_seq.get_tracks()):
                if isinstance(track, unreal.MovieSceneLevelVisibilityTrack):
                    level_seq.remove_track(track)

            vis_clean = []
            for v in visible_levels:
                if v and v not in vis_clean:
                    vis_clean.append(v)

            hidden_levels = [lvl for lvl in all_levels if lvl and lvl not in vis_clean]
            if not vis_clean and not hidden_levels:
                return False

            vis_track = level_seq.add_track(unreal.MovieSceneLevelVisibilityTrack)
            if not vis_track:
                return False

            if vis_clean:
                sec_vis = vis_track.add_section()
                sec_vis.set_row_index(0)
                sec_vis.set_range(int(start_frame), int(end_frame_exclusive))
                sec_vis.set_visibility(unreal.LevelVisibility.VISIBLE)
                sec_vis.set_level_names([unreal.Name(n) for n in vis_clean])

            if hidden_levels:
                sec_hid = vis_track.add_section()
                sec_hid.set_row_index(1)
                sec_hid.set_range(int(start_frame), int(end_frame_exclusive))
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
            sec.set_range(int(start_frame), int(end_frame_exclusive))

            sec.add_scalar_parameter_key(unreal.Name("Emiss"), unreal.FrameNumber(int(start_frame)), float(emiss_val))
            return True
        except Exception as e:
            print(f"[RenderLayer] 注入 MPC 轨道提示 ({level_seq.get_name()}): {e}")
            return False

    def inject_sequencer_cvar_track(self, level_seq, cvar_dict, cvar_asset_obj, start_frame, end_frame_exclusive):
        if not cvar_dict:
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
            sec.set_range(int(start_frame), int(end_frame_exclusive))

            if cvar_asset_obj:
                try:
                    if hasattr(sec, "console_variable_collections"):
                        col_item = unreal.MovieSceneConsoleVariableCollection()
                        col_item.set_editor_property("interface", cvar_asset_obj)
                        sec.set_editor_property("console_variable_collections", [col_item])
                except Exception:
                    pass

            cvar_pairs = [f"{k} {v}" for k, v in cvar_dict.items()]
            cvar_str = ", ".join(cvar_pairs)

            if hasattr(sec, "set_from_string"):
                sec.set_from_string(cvar_str)
            else:
                try:
                    cvar_overrides = sec.get_editor_property("console_variables")
                    if hasattr(cvar_overrides, "set_from_string"):
                        cvar_overrides.set_from_string(cvar_str)
                        sec.set_editor_property("console_variables", cvar_overrides)
                except Exception:
                    pass
            return True
        except Exception as e:
            print(f"[RenderLayer] 注入 Sequencer CVar 轨道提示 ({level_seq.get_name()}): {e}")
            return False

    # =========================================================================
    # 4. 【解决第 3 个问题】：精准识别 AOV_RenderSet / RenderSet_ID_Actor / AOV_RenderSet_ID_Material
    # =========================================================================
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
        """
        【解决第 3 个问题：为什么 AOV_RenderSet 被误判给了材质预设？】
        因为主预设名字叫 AOV_RenderSet（带有 AOV 前缀），绝不能用 `if "aov" in low` 来判断材质层！
        正确互斥规则：
        1. 名字含 "actor"                 -> 'id_actor'    (匹配 RenderSet_ID_Actor / AOV_RenderSet_ID_Actor)
        2. 名字含 "material" 或 "_mat"    -> 'id_material' (匹配 AOV_RenderSet_ID_Material / RenderSet_ID_Material_AOV)
        3. 名字含 "renderset" (且不含 actor/material) -> 'beauty' (精准匹配 AOV_RenderSet / RenderSet)
        """
        low = os.path.basename(str(asset_name_str).strip()).lower()
        if "actor" in low:
            return "id_actor"
        if "material" in low or "_mat" in low:
            return "id_material"
        if "renderset" in low:
            return "beauty"
        return None

    def find_mrq_presets(self, force_rescan=False):
        cfg = self.load_config()
        saved_presets = {} if force_rescan else cfg.get("mrq_preset_paths", {})

        presets = {
            "beauty": None,
            "id_actor": None,
            "id_material": None
        }

        # 1. 严格校验缓存路径，自动清除之前把 AOV_RenderSet 错绑给 id_material 的旧缓存！
        for k in ["beauty", "id_actor", "id_material"]:
            sp = str(saved_presets.get(k, "")).strip()
            if sp and sp.startswith("/") and self.asset_sub.does_asset_exist(sp):
                loaded = self.asset_sub.load_asset(sp)
                if loaded:
                    role = self._classify_preset_key_by_name(loaded.get_name())
                    if role == k:
                        presets[k] = loaded
                    else:
                        saved_presets.pop(k, None)

        # 2. 从全盘候选列表中精准匹配 (优先匹配 AOV_RenderSet, RenderSet_ID_Actor, AOV_RenderSet_ID_Material)
        all_cand_paths = self.list_all_mrq_config_assets()
        for pkg_p in all_cand_paths:
            role_k = self._classify_preset_key_by_name(pkg_p)
            if role_k and presets[role_k] is None:
                loaded = self.asset_sub.load_asset(pkg_p)
                if loaded:
                    presets[role_k] = loaded
                    saved_presets[role_k] = pkg_p

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

    def apply_preset_to_job_strictly(self, job, preset_asset, output_dir):
        norm_out = os.path.normpath(output_dir).replace('\\', '/')

        if preset_asset:
            try:
                p_out = preset_asset.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
                if p_out:
                    p_out.output_directory = unreal.DirectoryPath(norm_out)
                    p_out.file_name_format = "{sequence_name}.{frame_number}"
                    p_out.zero_pad_frame_numbers = 4
                    if hasattr(p_out, "use_custom_playback_range"):
                        p_out.use_custom_playback_range = False
            except Exception as e:
                print(f"[RenderLayer] 更新预设资产输出路径提示: {e}")

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

    # =========================================================================
    # 5. 【解决第 6 个问题】：100% 自动弹出 Movie Render Queue 面板
    # =========================================================================
    def open_mrq_panel_before_populating(self):
        """
        【解决第 6 个问题：为什么之前没有自动弹出 Movie Render Queue 面板？】
        在向队列写入 Job 之前，直接构造一个内存级 unreal.MoviePipelineQueue() 对象传给
        AssetEditorSubsystem.open_editor_for_assets([temp_q])！
        引擎底层的 FAssetTypeActions_MoviePipelineQueue::OpenAssetEditor 会立即调用
        FGlobalTabmanager::Get()->TryInvokeTab("MovieRenderPipeline") 弹出 MRQ 独立窗口！
        随后再往 mrq_sub.get_queue() 写入所有 Job，面板既能 100% 弹出，又绝不会清空已写入的队列！
        """
        try:
            temp_q = unreal.MoviePipelineQueue()
            asset_ed = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
            if asset_ed:
                asset_ed.open_editor_for_assets([temp_q])
                return True
        except Exception as e:
            print(f"[RenderLayer] 唤起 MRQ 窗口提示: {e}")
        return False

    # =========================================================================
    # 6. 自动解析服务器镜头目录与递增创建 publish/v001/render, v002/render
    # =========================================================================
    def resolve_and_create_publish_render_dir(self, ep, shot, custom_ue_dir="", force_new_version=True):
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
        return final_render_dir

    # =========================================================================
    # 7. 仅将已存在的分层序列重新一键加入 MRQ 队列
    # =========================================================================
    def requeue_existing_sequences(self, master_seq_path="", custom_publish_dir="", auto_increment_version=False):
        master_seq = self.get_active_master_sequence(master_seq_path, allow_content_browser_selection=True)
        if not master_seq:
            return False, "请先在顶部下拉框选择或在 Sequencer 中打开当前镜头的母版序列！"

        ep, shot = self.parse_ep_and_shot_from_seq(master_seq)
        master_pkg_path = master_seq.get_path_name().split('.')[0]
        shot_folder = os.path.dirname(master_pkg_path)

        multi_order = [
            ("env", "beauty"),
            ("key", "beauty"),
            ("sky", "beauty"),
            ("fill", "beauty"),
            ("emiss", "beauty"),
            ("heightfog", "beauty"),
            ("fog", "beauty"),
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

        for id_sfx, p_key in [("ID_actor", "id_actor"), ("ID_material", "id_material")]:
            p = f"{shot_folder}/cam{shot}_{id_sfx}"
            if self.asset_sub.does_asset_exist(p):
                seq_obj = self.asset_sub.load_asset(p)
                if seq_obj:
                    queued_items.append((seq_obj, p_key, id_sfx))

        render_out_dir = self.resolve_and_create_publish_render_dir(
            ep, shot, custom_ue_dir=custom_publish_dir, force_new_version=auto_increment_version
        )
        if not render_out_dir:
            return False, "未选择有效的 publish 输出目录。"

        presets, _ = self.find_mrq_presets(force_rescan=False)

        # ★ 先弹出 MRQ 面板，再填充队列 Job！
        self.open_mrq_panel_before_populating()

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

            p_name = target_preset.get_name() if target_preset else f"⚠️未绑定({final_pk})"
            bound_summary.append(f"• {seq_obj.get_name():<22}  ➔  预设: [{p_name}]")

        msg = f"【✅ 已将现有 {len(queued_items)} 个序列重新加入 MRQ 队列并弹出面板！】\n\n• 输出路径: {render_out_dir}\n\n" + "\n".join(bound_summary)
        return True, msg

    # =========================================================================
    # 8. 主执行入口：一键裂变分层 Sequence + 填充 CVarAsset + 精准绑定预设 + 弹出 MRQ
    # =========================================================================
    def execute_layer_split_and_queue(self, render_mode="multi", master_seq_path="",
                                      create_emiss_layer=False, custom_publish_dir="",
                                      auto_increment_version=True, clear_existing_queue=True,
                                      custom_sublevel_map=None):
        master_seq = self.get_active_master_sequence(master_seq_path, allow_content_browser_selection=True)
        if not master_seq:
            return False, "当前未打开任何母版镜头序列！\n请先在窗口顶部的【🎞️ 下拉选择母版镜头 ▾】中选择一个主镜头序列。"

        is_single_mode = str(render_mode).strip().lower().startswith("single") or str(render_mode).strip() == "1"

        ep, shot = self.parse_ep_and_shot_from_seq(master_seq)
        master_pkg_path = master_seq.get_path_name().split('.')[0]
        shot_folder = os.path.dirname(master_pkg_path)

        start_f, end_f_inc, end_f_exc = self.get_exact_timeline_range(master_seq)
        self.hide_alignment_actors_in_game()

        # 纯只读扫描，绝不调用 add_level_to_world 卡死
        all_levels, cls_lvls, _, _ = self.scan_mounted_and_folder_sublevels()
        if custom_sublevel_map is not None:
            for k, v_list in custom_sublevel_map.items():
                cls_lvls[k] = v_list
                for ln in v_list:
                    if ln and ln not in all_levels:
                        all_levels.append(ln)
            self.save_sublevel_mapping_for_current_world(custom_sublevel_map)

        has_any_mapped = any(len(cls_lvls.get(k, [])) > 0 for k in ["scence", "env", "key", "sky", "heightfog", "fill", "fog"])
        if not is_single_mode and not has_any_mapped:
            return False, (
                "检测到当前地图尚未配置任何子关卡映射！\n\n"
                "• 方式 1：在面板第 2 区点击【⚡ 一键创建并自动归类灯光/雾 (不移scence)】，0.1秒即可完成拆分；\n"
                "• 方式 2：若该场景无需拆分灯光层，请切换为【模式一：单层快速模式】。"
            )

        scence_lvls = cls_lvls["scence"]
        queued_jobs_info = []

        # ---------------------------------------------------------------------
        # 分支 A：模式一 (单层快速模式：仅 母版主相机序列 + ID_actor + ID_material 共 3 层)
        # ---------------------------------------------------------------------
        if is_single_mode:
            for old_sfx in ("env", "key", "sky", "heightfog", "fill", "fog", "emiss"):
                old_p = f"{shot_folder}/cam{shot}_{old_sfx}"
                if self.asset_sub.does_asset_exist(old_p):
                    self.asset_sub.delete_asset(old_p)

            queued_jobs_info.append((master_seq, "beauty", ["母版全关卡直出"], "master"))

            id_specs = [
                ("ID_actor",    scence_lvls, "id_actor"),
                ("ID_material", scence_lvls, "id_material"),
            ]
            for suffix, vis_lvls, preset_key in id_specs:
                layer_seq_name = f"cam{shot}_{suffix}"
                layer_seq_path = f"{shot_folder}/{layer_seq_name}"
                if self.asset_sub.does_asset_exist(layer_seq_path):
                    self.asset_sub.delete_asset(layer_seq_path)

                dup_seq = self.asset_sub.duplicate_asset(master_pkg_path, layer_seq_path)
                if not dup_seq:
                    continue
                self.strip_media_tracks(dup_seq)
                if vis_lvls and all_levels:
                    self.inject_level_visibility_track(dup_seq, vis_lvls, all_levels, start_f, end_f_exc)
                self.asset_sub.save_asset(layer_seq_path, only_if_is_dirty=False)
                queued_jobs_info.append((dup_seq, preset_key, vis_lvls if vis_lvls else ["主关卡默认场景"], suffix))

        # ---------------------------------------------------------------------
        # 分支 B：模式二 (多层拆分模式)
        # ---------------------------------------------------------------------
        else:
            global_mpc = self.get_or_create_global_emiss_mpc()
            cvar_assets_map = self.get_or_create_cvar_presets()

            layer_specs = [
                ("env",         scence_lvls + cls_lvls["env"],                                           "beauty", 0.0, CVAR_DEFAULT_RESTORE, cvar_assets_map.get("restore")),
                ("key",         scence_lvls + cls_lvls["key"],                                           "beauty", 0.0, CVAR_DEFAULT_RESTORE, cvar_assets_map.get("restore")),
                ("sky",         cls_lvls["sky"],                                                         "beauty", 0.0, CVAR_DEFAULT_RESTORE, cvar_assets_map.get("restore")),
                ("fill",        scence_lvls + cls_lvls["fill"],                                          "beauty", 0.0, CVAR_DEFAULT_RESTORE, cvar_assets_map.get("restore")),
            ]

            if create_emiss_layer:
                layer_specs.append(("emiss", scence_lvls, "beauty", 1.0, CVAR_DEFAULT_RESTORE, cvar_assets_map.get("restore")))
            else:
                old_emiss = f"{shot_folder}/cam{shot}_emiss"
                if self.asset_sub.does_asset_exist(old_emiss):
                    self.asset_sub.delete_asset(old_emiss)

            layer_specs.extend([
                ("heightfog",   scence_lvls + cls_lvls["heightfog"] + cls_lvls["key"] + cls_lvls["env"], "beauty", 0.0, CVAR_HEIGHTFOG_LAYER, cvar_assets_map.get("heightfog")),
                ("fog",         scence_lvls + cls_lvls["fog"] + cls_lvls["key"] + cls_lvls["env"],       "beauty", 0.0, CVAR_EASYFOG_LAYER,   cvar_assets_map.get("fog")),
                ("ID_actor",    scence_lvls,                                                             "id_actor",    None, None, None),
                ("ID_material", scence_lvls,                                                             "id_material", None, None, None),
            ])

            for suffix, vis_lvls, preset_key, emiss_val, cvar_dict, cvar_asset_obj in layer_specs:
                layer_seq_name = f"cam{shot}_{suffix}"
                layer_seq_path = f"{shot_folder}/{layer_seq_name}"

                if self.asset_sub.does_asset_exist(layer_seq_path):
                    self.asset_sub.delete_asset(layer_seq_path)

                dup_seq = self.asset_sub.duplicate_asset(master_pkg_path, layer_seq_path)
                if not dup_seq:
                    continue

                self.strip_media_tracks(dup_seq)
                self.inject_level_visibility_track(dup_seq, vis_lvls, all_levels, start_f, end_f_exc)

                if emiss_val is not None and global_mpc:
                    self.inject_mpc_control_track(dup_seq, global_mpc, emiss_val, start_f, end_f_exc)

                if cvar_dict:
                    self.inject_sequencer_cvar_track(dup_seq, cvar_dict, cvar_asset_obj, start_f, end_f_exc)

                self.asset_sub.save_asset(layer_seq_path, only_if_is_dirty=False)
                queued_jobs_info.append((dup_seq, preset_key, vis_lvls, suffix))

        render_out_dir = self.resolve_and_create_publish_render_dir(
            ep, shot, custom_ue_dir=custom_publish_dir, force_new_version=auto_increment_version
        )
        if not render_out_dir:
            return False, "未指定有效的 publish 输出目录。"

        presets, _ = self.find_mrq_presets(force_rescan=False)

        # ★ 先唤起 Movie Render Queue 面板，再往队列里写入所有 Job！
        self.open_mrq_panel_before_populating()

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

            p_name = target_preset.get_name() if target_preset else f"⚠️未绑定({final_pk})"
            summary_lines.append(f"• {seq_obj.get_name():<22}  ➔  预设: [{p_name:<26}]  |  显示关卡: {lvls}")

        try:
            unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(master_seq)
        except Exception:
            pass

        msg = (
            f"【✅ Shot {shot} 场景分层与 MRQ 渲染队列配置完成（已自动打开 MRQ 窗口）！】\n\n"
            f"• 时间线帧区间: {start_f:04d} ~ {end_f_inc:04d} (共 {end_f_inc - start_f + 1} 帧)\n"
            f"• 渲染输出目录: {render_out_dir}\n\n"
            f"【队列序列与绑定预设核对】\n" + "\n".join(summary_lines)
        )
        return True, msg


# =========================================================================
# 非阻塞工业级控制面板 v3.1
# =========================================================================
def _PopupToplevelMessage(parent_win, title_str, body_str):
    import tkinter as tk
    global _GLOBAL_GUIDE_WIN

    if _GLOBAL_GUIDE_WIN is not None:
        try:
            if _GLOBAL_GUIDE_WIN.winfo_exists():
                _GLOBAL_GUIDE_WIN.destroy()
        except Exception:
            pass
        _GLOBAL_GUIDE_WIN = None

    top = tk.Toplevel(parent_win)
    _GLOBAL_GUIDE_WIN = top
    top.title(title_str)
    top.configure(bg="#21252b")
    top.attributes('-topmost', True)
    top.transient(parent_win)

    txt_lbl = tk.Label(
        top, text=body_str, justify="left", anchor="w",
        fg="#dcdfe4", bg="#21252b", font=("Microsoft YaHei", 9), padx=18, pady=14
    )
    txt_lbl.pack(fill="both", expand=True)

    tk.Button(
        top, text="✓ 我知道了 (关闭此提示)", command=top.destroy,
        bg="#2ea043", fg="#ffffff", font=("Microsoft YaHei", 9, "bold"),
        relief="flat", padx=16, pady=6, cursor="hand2"
    ).pack(pady=(0, 14))

    top.update_idletasks()
    w = max(580, top.winfo_reqwidth() + 20)
    h = top.winfo_reqheight() + 10
    sw = top.winfo_screenwidth()
    sh = top.winfo_screenheight()
    top.geometry(f"{w}x{h}+{int((sw - w) / 2)}+{int((sh - h) / 2)}")
    top.lift()
    top.focus_force()


def show_render_layer_dialog():
    import tkinter as tk

    global _GLOBAL_TK_WIN, _SLATE_TICK_HANDLE

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    if _GLOBAL_TK_WIN is not None:
        try:
            if _GLOBAL_TK_WIN.winfo_exists():
                _GLOBAL_TK_WIN.lift()
                _GLOBAL_TK_WIN.focus_force()
                return
        except Exception:
            _GLOBAL_TK_WIN = None

    pipe = UERenderLayerPipeline()
    std_folders = pipe.detect_project_standard_folders()

    master_seq = pipe.get_active_master_sequence(allow_content_browser_selection=True)
    start_f, end_f_inc, _ = pipe.get_exact_timeline_range(master_seq)

    real_sublevels, cls_lvls, def_light_dir, _ = pipe.scan_mounted_and_folder_sublevels()
    presets, all_preset_paths = pipe.find_mrq_presets(force_rescan=False)
    cfg = pipe.load_config()
    saved_preset_paths = cfg.get("mrq_preset_paths", {})

    win = tk.Tk()
    _GLOBAL_TK_WIN = win
    win.title("UE5 影视级分层渲染与 MRQ 自动化调度中心 v3.1 (非阻塞悬浮窗·可随时操作UE) [LiangLiangVFX]")
    win.configure(bg="#1e2127")
    win.attributes('-topmost', True)
    win.resizable(True, True)

    def _on_close_win():
        global _GLOBAL_TK_WIN, _SLATE_TICK_HANDLE
        if _SLATE_TICK_HANDLE is not None:
            try:
                unreal.unregister_slate_post_tick_callback(_SLATE_TICK_HANDLE)
            except Exception:
                pass
            _SLATE_TICK_HANDLE = None
        try:
            win.destroy()
        except Exception:
            pass
        _GLOBAL_TK_WIN = None

    win.protocol("WM_DELETE_WINDOW", _on_close_win)

    default_mode = "multi" if len(real_sublevels) > 0 else "single"
    mode_var = tk.StringVar(master=win, value=default_mode)
    emiss_var = tk.BooleanVar(master=win, value=False)
    inc_ver_var = tk.BooleanVar(master=win, value=True)
    prefix_var = tk.StringVar(master=win, value="night_")
    light_dir_var = tk.StringVar(master=win, value=def_light_dir)

    # ----------------- 顶部状态栏 (仅列出干净的主镜头名，帧区间严格显示真实包含帧) -----------------
    top_frame = tk.Frame(win, bg="#282c34", padx=12, pady=8)
    top_frame.pack(fill="x", padx=14, pady=(10, 4))

    def _get_seq_status_text_and_color(seq_obj, sf, ef_inc):
        if seq_obj and sf is not None and ef_inc is not None:
            total_len = ef_inc - sf + 1
            return f"🎬 当前母版主镜头: {seq_obj.get_name()}   |   ⏱️ 帧区间: {sf:04d} ~ {ef_inc:04d} (共 {total_len} 帧)", "#61afef"
        return "⚠️ 未打开母版序列 (请在右侧【🎞️ 下拉选择母版镜头 ▾】中直接点选，或在 UE 中选中后点拾取)", "#e06c75"

    init_txt, init_col = _get_seq_status_text_and_color(master_seq, start_f, end_f_inc)
    lbl_seq = tk.Label(top_frame, text=init_txt, fg=init_col, bg="#282c34", font=("Microsoft YaHei", 9, "bold"))
    lbl_seq.pack(side="left")

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
                t_str, c_str = _get_seq_status_text_and_color(master_seq, start_f, end_f_inc)
                lbl_seq.config(text=t_str, fg=c_str)

    def _refresh_master_seq(allow_cb=True):
        nonlocal master_seq, start_f, end_f_inc
        master_seq = pipe.get_active_master_sequence(allow_content_browser_selection=allow_cb)
        if master_seq:
            try:
                unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(master_seq)
            except Exception:
                pass
        start_f, end_f_inc, _ = pipe.get_exact_timeline_range(master_seq)
        t_str, c_str = _get_seq_status_text_and_color(master_seq, start_f, end_f_inc)
        lbl_seq.config(text=t_str, fg=c_str)

    tk.Button(
        top_frame, text="📌 拾取UE当前选中/打开序列", command=lambda: _refresh_master_seq(True),
        bg="#3e4451", fg="#98c379", font=("Microsoft YaHei", 8, "bold"), relief="flat", padx=8, pady=2, cursor="hand2"
    ).pack(side="right", padx=(4, 0))

    mb_seq = tk.Menubutton(
        top_frame, text="🎞️ 下拉选择母版镜头 ▾", bg="#1f6feb", fg="#ffffff",
        relief="flat", font=("Microsoft YaHei", 8, "bold"), padx=10, pady=3, cursor="hand2"
    )
    seq_menu = tk.Menu(mb_seq, tearoff=0, bg="#282c34", fg="#ffffff")
    mb_seq.config(menu=seq_menu)

    def _populate_seq_menu():
        seq_menu.delete(0, "end")
        master_items = pipe.list_all_master_sequences_in_project()
        if master_items:
            for short_name, pkg_p in master_items:
                # 仅显示干净的主镜头名称 (如 ep28_cam2220)，彻底过滤掉所有分层子序列！
                seq_menu.add_command(label=f"🎬 {short_name}", command=lambda p=pkg_p: _select_and_open_seq_by_path(p))
        else:
            seq_menu.add_command(label="(工程中暂未找到母版主镜头序列)", state="disabled")

    _populate_seq_menu()
    mb_seq.pack(side="right", padx=4)

    # ----------------- 区域 1：分层渲染模式选择 -----------------
    frm_mode = tk.LabelFrame(
        win, text=" 1. 选择分层渲染模式 (自动对齐 Nuke 单层/多层预合成) ",
        fg="#e5c07b", bg="#1e2127", font=("Microsoft YaHei", 9, "bold"), padx=12, pady=6
    )
    frm_mode.pack(fill="x", padx=14, pady=4)

    tk.Radiobutton(
        frm_mode,
        text="模式一：单层快速模式  ➔  仅渲染 3 个序列：[母版主相机] + [cam_ID_actor] + [cam_ID_material]",
        variable=mode_var, value="single",
        fg="#ffffff", bg="#1e2127", selectcolor="#2c313c", activebackground="#1e2127", activeforeground="#61afef",
        font=("Microsoft YaHei", 9, "bold")
    ).pack(anchor="w", pady=1)

    tk.Radiobutton(
        frm_mode,
        text="模式二：多层灯光与雾效全拆分模式  ➔  自动裂变 [env / key / sky / fill / heightfog / fog + 双ID] (LevelVisibility 轨道自动隔离隐藏其余层)",
        variable=mode_var, value="multi",
        fg="#98c379", bg="#1e2127", selectcolor="#2c313c", activebackground="#1e2127", activeforeground="#98c379",
        font=("Microsoft YaHei", 9, "bold")
    ).pack(anchor="w", pady=1)

    chk_row = tk.Frame(frm_mode, bg="#1e2127")
    chk_row.pack(fill="x", pady=(3, 1))
    tk.Checkbutton(
        chk_row,
        text="在模式二中额外生成自发光层 (cam_emiss + 自动在 Shot/MediaPlayer 创建 MPC_Global_Emiss)",
        variable=emiss_var,
        fg="#dcdfe4", bg="#1e2127", selectcolor="#2c313c", activebackground="#1e2127",
        font=("Microsoft YaHei", 9)
    ).pack(side="left", padx=(20, 16))

    tk.Checkbutton(
        chk_row,
        text="当 publish/v001/render 已有渲染图时，自动递增新建 v002 / v003",
        variable=inc_ver_var,
        fg="#dcdfe4", bg="#1e2127", selectcolor="#2c313c", activebackground="#1e2127",
        font=("Microsoft YaHei", 9)
    ).pack(side="left")

    # ----------------- 区域 2：子关卡映射与拆分 (纯只读极速扫描，0卡顿) -----------------
    def _get_sublevel_frame_title(sub_list):
        if sub_list:
            return f" 2. 子关卡映射与拆分 (当前检测到 {len(sub_list)} 个子关卡：{', '.join(sub_list)}) "
        return " 2. 子关卡映射与拆分 (⚠️ 当前地图尚未检测到子关卡，可点下方按钮一键创建) "

    frm_lvl = tk.LabelFrame(
        win, text=_get_sublevel_frame_title(real_sublevels),
        fg="#e5c07b" if real_sublevels else "#e06c75", bg="#1e2127",
        font=("Microsoft YaHei", 9, "bold"), padx=12, pady=6
    )
    frm_lvl.pack(fill="x", padx=14, pady=4)

    dir_bar = tk.Frame(frm_lvl, bg="#282c34", padx=8, pady=5)
    dir_bar.pack(fill="x", pady=(0, 4))

    tk.Label(dir_bar, text="关卡前缀:", fg="#abb2bf", bg="#282c34", font=("Microsoft YaHei", 8, "bold")).pack(side="left")
    ent_prefix = tk.Entry(dir_bar, textvariable=prefix_var, width=8, bg="#1e2127", fg="#98c379", insertbackground="#ffffff", relief="flat", font=("Consolas", 9, "bold"))
    ent_prefix.pack(side="left", padx=4, ipady=1)

    mb_pfx = tk.Menubutton(dir_bar, text="预设前缀 ▾", bg="#3e4451", fg="#ffffff", relief="flat", font=("Microsoft YaHei", 8), padx=5)
    pfx_menu = tk.Menu(mb_pfx, tearoff=0, bg="#282c34", fg="#ffffff")
    mb_pfx.config(menu=pfx_menu)
    for p_opt in ["night_", "day_", "dusk_", ""]:
        pfx_menu.add_command(label=f"设为: '{p_opt}'", command=lambda v=p_opt: prefix_var.set(v))
    mb_pfx.pack(side="left", padx=(0, 12))

    tk.Label(dir_bar, text="Light 关卡存放目录:", fg="#abb2bf", bg="#282c34", font=("Microsoft YaHei", 8, "bold")).pack(side="left")
    tk.Entry(dir_bar, textvariable=light_dir_var, width=32, bg="#1e2127", fg="#61afef", insertbackground="#ffffff", relief="flat", font=("Consolas", 9)).pack(side="left", padx=4, ipady=1)

    def _pick_selected_folder_for_light():
        try:
            sel_paths = unreal.EditorUtilityLibrary.get_current_content_browser_path()
            if sel_paths:
                light_dir_var.set(str(sel_paths))
        except Exception:
            pass

    tk.Button(
        dir_bar, text="📂 设为内容浏览器当前目录", command=_pick_selected_folder_for_light,
        bg="#3e4451", fg="#ffffff", relief="flat", font=("Microsoft YaHei", 8), padx=6, cursor="hand2"
    ).pack(side="left", padx=4)

    sub_toolbar = tk.Frame(frm_lvl, bg="#282c34", padx=8, pady=5)
    sub_toolbar.pack(fill="x", pady=(0, 6))

    def _show_split_guide_popup():
        pfx = prefix_var.get().strip()
        if pfx and not pfx.endswith("_"):
            pfx += "_"
        lines = [
            "【大厂标准项目文件夹与关卡拆分规范 (依据《UE项目文件夹规范.txt》)】\n",
            f"1. 主渲染关卡 (如 {std_folders['proj_root']}/Map/WG_Cliff_Render)：",
            "   └ 保留：PostProcessVolume (后期处理体积)、导入的镜头相机 (/!Cam)、Shot_Root、ImagePlate、SM_Ref 参考简模。\n",
            f"2. 场景模型子关卡 ({std_folders['scence_dir']}/scence)：",
            "   └ 存放：静态网格体(StaticMesh)、地形(Landscape)、建筑、植被 (★脚本自动跳过移动场景模型，0卡顿)。\n",
            f"3. 灯光与雾气子关卡 ({light_dir_var.get()} 下创建，当前前缀 '{pfx}')："
        ]
        for role_k, base_sfx, _, lbl, desc in SUBLEVEL_ROLE_SPECS:
            if role_k == "scence":
                continue
            lines.append(f"   • {pfx}{base_sfx:<14} ({lbl.replace(':', '')})  ➔  {desc}")
        lines.append("\n💡 关于 Always Loaded 模式的说明：\n   虽然子关卡流送方式为 Always Loaded，但每个分层 Sequence 内部均自动注入了 Level Visibility 轨道（Visible + Hidden），\n   渲染每层时会自动强制关闭其他无关子关卡，绝不会混在一起渲染！")
        _PopupToplevelMessage(win, "UE 影视项目关卡存放规范", "\n".join(lines))

    lvl_StringVars = {}
    lvl_Menus = {}

    def _refresh_sublevel_widgets():
        nonlocal real_sublevels, cls_lvls
        real_sublevels, cls_lvls, _, _ = pipe.scan_mounted_and_folder_sublevels(custom_light_dir=light_dir_var.get())
        frm_lvl.config(text=_get_sublevel_frame_title(real_sublevels), fg="#98c379" if real_sublevels else "#e06c75")
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
                    m_pop.add_command(label="❌ 清空此项", command=lambda s=sv: s.set(""))
        if real_sublevels:
            mode_var.set("multi")

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

    tk.Button(
        sub_toolbar, text="📖 查看各关卡存放规范", command=_show_split_guide_popup,
        bg="#3e4451", fg="#ffffff", relief="flat", font=("Microsoft YaHei", 8), padx=8, pady=2, cursor="hand2"
    ).pack(side="left", padx=(0, 4))

    tk.Button(
        sub_toolbar, text="🔍 刷新识别现有子关卡 (纯只读·0卡顿)", command=_refresh_sublevel_widgets,
        bg="#61afef", fg="#1e2127", relief="flat", font=("Microsoft YaHei", 8, "bold"), padx=8, pady=2, cursor="hand2"
    ).pack(side="left", padx=4)

    tk.Button(
        sub_toolbar, text="📁 一键创建空白灯光/雾子关卡 (手动分)", command=_on_create_empty_sublevels,
        bg="#d19a66", fg="#1e2127", relief="flat", font=("Microsoft YaHei", 8, "bold"), padx=8, pady=2, cursor="hand2"
    ).pack(side="left", padx=4)

    tk.Button(
        sub_toolbar, text="⚡ 一键创建并自动归类灯光/雾 (不移scence模型)", command=_on_auto_split_lights_and_fog,
        bg="#98c379", fg="#1e2127", relief="flat", font=("Microsoft YaHei", 8, "bold"), padx=8, pady=2, cursor="hand2"
    ).pack(side="left", padx=4)

    grid_lvl = tk.Frame(frm_lvl, bg="#1e2127")
    grid_lvl.pack(fill="x")

    for idx, (k, base_sfx, _, label_txt, _) in enumerate(SUBLEVEL_ROLE_SPECS):
        r_idx = idx // 2
        c_idx = (idx % 2) * 3

        tk.Label(
            grid_lvl, text=label_txt, anchor="e", fg="#abb2bf", bg="#1e2127", font=("Microsoft YaHei", 9)
        ).grid(row=r_idx, column=c_idx, sticky="e", padx=(6, 4), pady=3)

        sv = tk.StringVar(master=win, value=", ".join(cls_lvls.get(k, [])))
        lvl_StringVars[k] = sv

        ent = tk.Entry(
            grid_lvl, textvariable=sv, width=22, bg="#282c34", fg="#ffffff",
            insertbackground="#ffffff", relief="flat", font=("Consolas", 9)
        )
        ent.grid(row=r_idx, column=c_idx + 1, sticky="w", padx=2, pady=3, ipady=2)

        mb = tk.Menubutton(
            grid_lvl, text="选择关卡 ▾", bg="#3e4451", fg="#ffffff",
            relief="flat", font=("Microsoft YaHei", 8), padx=6, pady=1, cursor="hand2"
        )
        menu_popup = tk.Menu(mb, tearoff=0, bg="#282c34", fg="#ffffff")
        mb.config(menu=menu_popup)
        lvl_Menus[k] = menu_popup
        mb.grid(row=r_idx, column=c_idx + 2, sticky="w", padx=(2, 16), pady=3)

    _refresh_sublevel_widgets()

    # ----------------- 区域 3：【解决第 3 个问题】完整显示『🌈 材质 AOV 预设』且精准匹配 AOV_RenderSet -----------------
    frm_mrq = tk.LabelFrame(
        win, text=" 3. MRQ 渲染配置文件绑定 (主层 -> AOV_RenderSet | Actor层 -> RenderSet_ID_Actor | 材质层 -> AOV_RenderSet_ID_Material) ",
        fg="#e5c07b", bg="#1e2127", font=("Microsoft YaHei", 9, "bold"), padx=12, pady=6
    )
    frm_mrq.pack(fill="x", padx=14, pady=4)

    grid_mrq = tk.Frame(frm_mrq, bg="#1e2127")
    grid_mrq.pack(fill="x")

    preset_vars = {}
    preset_entries = {}
    preset_menus = {}
    preset_rows = [
        ("beauty",      "🎨 主渲染预设 (AOV_RenderSet):",                presets.get("beauty")),
        ("id_actor",    "🆔 Actor ID 预设 (RenderSet_ID_Actor):",         presets.get("id_actor")),
        ("id_material", "🌈 材质 AOV 预设 (AOV_RenderSet_ID_Material):", presets.get("id_material")),
    ]

    def _bind_preset_path_to_slot(slot_key, pkg_path):
        preset_vars[slot_key].set(pkg_path)
        preset_entries[slot_key].config(fg="#98c379")
        c = pipe.load_config()
        if "mrq_preset_paths" not in c:
            c["mrq_preset_paths"] = {}
        c["mrq_preset_paths"][slot_key] = pkg_path
        pipe.save_config(c)

    for row_i, (p_key, p_label, p_obj) in enumerate(preset_rows):
        # 使用 grid + sticky="w" 自适应宽度，绝不裁切左侧『🌈 材』字！
        tk.Label(
            grid_mrq, text=p_label, anchor="w", fg="#abb2bf", bg="#1e2127", font=("Microsoft YaHei", 9, "bold")
        ).grid(row=row_i, column=0, sticky="w", padx=(4, 8), pady=3)

        init_p = p_obj.get_path_name().split('.')[0] if p_obj else saved_preset_paths.get(p_key, "未找到 (请点击右侧[下拉选择预设]或在内容浏览器选中后点[拾取])")
        pv = tk.StringVar(master=win, value=init_p)
        preset_vars[p_key] = pv

        p_ent = tk.Entry(
            grid_mrq, textvariable=pv, width=40, bg="#282c34",
            fg="#98c379" if p_obj else "#e06c75", insertbackground="#ffffff",
            relief="flat", font=("Consolas", 9)
        )
        p_ent.grid(row=row_i, column=1, sticky="w", padx=4, pady=3, ipady=2)
        preset_entries[p_key] = p_ent

        mb_p = tk.Menubutton(
            grid_mrq, text="▾ 下拉选择预设", bg="#1f6feb", fg="#ffffff",
            relief="flat", font=("Microsoft YaHei", 8), padx=8, pady=2, cursor="hand2"
        )
        p_menu = tk.Menu(mb_p, tearoff=0, bg="#282c34", fg="#ffffff")
        mb_p.config(menu=p_menu)
        preset_menus[p_key] = p_menu
        mb_p.grid(row=row_i, column=2, sticky="w", padx=3, pady=3)

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

        tk.Button(
            grid_mrq, text="📌 拾取UE选中资产", command=_make_pick_preset(p_key),
            bg="#3e4451", fg="#ffffff", relief="flat", font=("Microsoft YaHei", 8), padx=8, cursor="hand2"
        ).grid(row=row_i, column=3, sticky="w", padx=3, pady=3)

    def _populate_preset_dropdowns(cand_list):
        for slot_k, p_m in preset_menus.items():
            p_m.delete(0, "end")
            if cand_list:
                for cp in cand_list:
                    short_n = os.path.basename(cp)
                    p_m.add_command(label=f"{short_n}  ({cp})", command=lambda k=slot_k, p=cp: _bind_preset_path_to_slot(k, p))
            else:
                p_m.add_command(label="(未扫描到预设，可在UE中选中后点拾取)", state="disabled")

    _populate_preset_dropdowns(all_preset_paths)

    def _auto_rescan_presets():
        new_p, new_cands = pipe.find_mrq_presets(force_rescan=True)
        _populate_preset_dropdowns(new_cands)
        for pk, p_obj in new_p.items():
            if p_obj:
                preset_vars[pk].set(p_obj.get_path_name().split('.')[0])
                preset_entries[pk].config(fg="#98c379")
            else:
                preset_vars[pk].set("未找到 (请点击右侧[下拉选择预设]或[拾取UE选中资产])")
                preset_entries[pk].config(fg="#e06c75")

    cf = tk.Frame(frm_mrq, bg="#1e2127")
    cf.pack(fill="x", pady=(4, 2))
    tk.Label(
        cf, text="💡 雾层防污染说明: 自动生成并填充 CVar_HeightFog_Only / CVar_EasyFog_Only / CVar_Default_Restore (Diffuse=2, Specular=2, Fog=2)",
        fg="#98c379", bg="#1e2127", font=("Microsoft YaHei", 8)
    ).pack(side="left", padx=4)
    tk.Button(
        cf, text="🔄 重新自动匹配三大预设", command=_auto_rescan_presets,
        bg="#3e4451", fg="#61afef", relief="flat", font=("Microsoft YaHei", 8, "bold"), padx=8, cursor="hand2"
    ).pack(side="right", padx=4)

    # ----------------- 底部执行按钮区 -----------------
    btn_bar = tk.Frame(win, bg="#1e2127", pady=6)
    btn_bar.pack(fill="x", padx=14, pady=(4, 12))

    def _collect_sublevel_map():
        mp = {}
        for k, sv in lvl_StringVars.items():
            mp[k] = [x.strip() for x in sv.get().split(",") if x.strip()]
        return mp

    def _save_preset_paths_from_ui():
        c = pipe.load_config()
        if "mrq_preset_paths" not in c:
            c["mrq_preset_paths"] = {}
        for k, pv in preset_vars.items():
            val = pv.get().strip()
            if val.startswith("/"):
                c["mrq_preset_paths"][k] = val
        pipe.save_config(c)

    def _on_split_and_queue():
        _save_preset_paths_from_ui()
        sel_mode = mode_var.get()
        use_emiss = emiss_var.get()
        use_inc = inc_ver_var.get()
        sub_map = _collect_sublevel_map()
        cur_seq_path = master_seq.get_path_name().split('.')[0] if master_seq else ""
        ok, msg = pipe.execute_layer_split_and_queue(
            render_mode=sel_mode,
            master_seq_path=cur_seq_path,
            create_emiss_layer=use_emiss,
            auto_increment_version=use_inc,
            clear_existing_queue=True,
            custom_sublevel_map=sub_map
        )
        _PopupToplevelMessage(win, "执行结果", msg)

    def _on_requeue_only():
        _save_preset_paths_from_ui()
        use_inc = inc_ver_var.get()
        cur_seq_path = master_seq.get_path_name().split('.')[0] if master_seq else ""
        ok, msg = pipe.requeue_existing_sequences(
            master_seq_path=cur_seq_path,
            auto_increment_version=use_inc
        )
        _PopupToplevelMessage(win, "重新入列结果", msg)

    tk.Button(
        btn_bar,
        text="🚀 一键裂变生成分层 Sequence + 加入 MRQ 队列并弹出面板",
        command=_on_split_and_queue,
        bg="#2ea043", fg="#ffffff", activebackground="#238636", activeforeground="#ffffff",
        font=("Microsoft YaHei", 10, "bold"), relief="flat", pady=8, cursor="hand2"
    ).pack(side="left", fill="x", expand=True, padx=(0, 6))

    tk.Button(
        btn_bar,
        text="📥 仅将已有分层 Sequence 重新加入 MRQ 队列并弹出面板",
        command=_on_requeue_only,
        bg="#1f6feb", fg="#ffffff", activebackground="#1158c7", activeforeground="#ffffff",
        font=("Microsoft YaHei", 10, "bold"), relief="flat", pady=8, cursor="hand2"
    ).pack(side="left", fill="x", expand=True, padx=(6, 0))

    win.update_idletasks()
    req_w = max(1000, win.winfo_reqwidth() + 28)
    req_h = win.winfo_reqheight() + 20
    scr_w = win.winfo_screenwidth()
    scr_h = win.winfo_screenheight()
    pos_x = max(10, int((scr_w - req_w) / 2))
    pos_y = max(10, int((scr_h - req_h) / 2))
    win.geometry(f"{req_w}x{req_h}+{pos_x}+{pos_y}")
    win.minsize(req_w, req_h)

    def _slate_tick_pump(delta_time):
        global _GLOBAL_TK_WIN, _SLATE_TICK_HANDLE
        if _GLOBAL_TK_WIN is None:
            if _SLATE_TICK_HANDLE is not None:
                try:
                    unreal.unregister_slate_post_tick_callback(_SLATE_TICK_HANDLE)
                except Exception:
                    pass
                _SLATE_TICK_HANDLE = None
            return
        try:
            if _GLOBAL_TK_WIN.winfo_exists():
                _GLOBAL_TK_WIN.update_idletasks()
                _GLOBAL_TK_WIN.update()
            else:
                _GLOBAL_TK_WIN = None
        except Exception:
            _GLOBAL_TK_WIN = None

    _SLATE_TICK_HANDLE = unreal.register_slate_post_tick_callback(_slate_tick_pump)


def run_single_layer_workflow(master_seq_path="", publish_dir="", new_version=True):
    pipe = UERenderLayerPipeline()
    ok, _ = pipe.execute_layer_split_and_queue(
        render_mode="single", master_seq_path=str(master_seq_path).strip(),
        create_emiss_layer=False, custom_publish_dir=str(publish_dir).strip(),
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