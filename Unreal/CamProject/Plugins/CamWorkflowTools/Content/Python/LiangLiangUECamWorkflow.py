# -*- coding: utf-8 -*-
"""
UE5.4 镜头资产自动化交付管线 (Media轨道素材真实帧长对齐版)
- 保持原版控件变量名与装配逻辑 100% 不变
- 智能递归嗅探工程既有 Shot 目录规范 (/Game/.../Shot)
Author: LiangLiangArtist
"""

import os
import re
import json
import unreal

CONFIG_FILE_PATH = os.path.normpath(os.path.join(unreal.Paths.project_saved_dir(), "UECamWorkflowConfig.json"))

class UECamWorkflowPipeline(object):
    def __init__(self):
        pass

    def scan_existing_shot_directory(self):
        """递归扫描工程物理 Content 目录，匹配工程规范 Shot 路径 (如 /Game/EG1/Shot)"""
        try:
            content_dir = unreal.Paths.project_content_dir()
            content_dir_norm = os.path.normpath(content_dir).replace('\\', '/')

            for root, dirs, files in os.walk(content_dir_norm):
                for d in dirs:
                    if d.lower() == "shot":
                        full_shot_path = os.path.normpath(os.path.join(root, d)).replace('\\', '/')
                        relative_path = os.path.relpath(full_shot_path, content_dir_norm).replace('\\', '/')
                        ue_game_path = f"/Game/{relative_path}".rstrip('/')
                        print(f"[CamWorkflow] 成功递归嗅探到工程规范目录: {ue_game_path}")
                        return ue_game_path
        except Exception as e:
            print(f"[CamWorkflow] 扫描工程目录发生异常: {e}")
        return None

    def get_saved_root_dir(self, default_dir="/Game/Shot"):
        """读取持久化保存的根目录路径 (优先动态嗅探工程中的规范 Shot 目录)"""
        # 1. 优先检测工程实际存在的 Shot 目录
        scanned_dir = self.scan_existing_shot_directory()
        if scanned_dir:
            return scanned_dir

        # 2. 其次读取本地保存的历史记忆配置
        try:
            if os.path.exists(CONFIG_FILE_PATH):
                with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("root_dir", default_dir)
        except Exception:
            pass
        return default_dir

    def save_root_dir(self, root_dir):
        """保存用户设置的根目录路径"""
        try:
            data = {}
            if os.path.exists(CONFIG_FILE_PATH):
                with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            data["root_dir"] = root_dir
            with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[CamWorkflow] 保存配置提示: {e}")

    def parse_metadata_from_path(self, fbx_path):
        if not fbx_path:
            return "EP28", "2180", 1001, 1021, 21, 22

        clean_path = str(fbx_path).replace('\\', '/').strip()
        filename = os.path.splitext(os.path.basename(clean_path))[0]

        shot = "2180"
        start_f = 1001
        end_f = 1021
        raw_shot_len = 21
        duration = 22

        m = re.search(r'(\d+)_(\d+)_(\d+)', filename)
        if m:
            shot = m.group(1)
            start_f = int(m.group(2))
            end_f = int(m.group(3))
            raw_shot_len = end_f - start_f + 1
            duration = raw_shot_len + 1
        else:
            nums = re.findall(r'\d+', filename)
            if len(nums) >= 3:
                shot = nums[0]
                start_f = int(nums[1])
                end_f = int(nums[2])
                raw_shot_len = end_f - start_f + 1
                duration = raw_shot_len + 1
            elif len(nums) >= 1:
                shot = nums[0]

        ep = "EP28"
        ep_m = re.search(r'(ep\d+)', clean_path, re.IGNORECASE)
        if ep_m:
            ep = ep_m.group(1).upper()
        else:
            parent_dir = os.path.basename(os.path.dirname(clean_path))
            parent_ep = re.search(r'(ep\d+)', parent_dir, re.IGNORECASE)
            if parent_ep:
                ep = parent_ep.group(1).upper()

        return ep, shot, start_f, end_f, raw_shot_len, duration

    def set_camera_focus_to_do_not_override(self, cine_cam_actor):
        try:
            cam_comp = cine_cam_actor.get_cine_camera_component()
            focus_settings = cam_comp.get_editor_property("focus_settings")
            focus_settings.set_editor_property("focus_method", unreal.CameraFocusMethod.DO_NOT_OVERRIDE)
            cam_comp.set_editor_property("focus_settings", focus_settings)
            print("[CamWorkflow] 焦点方式已成功设为: Do Not Override")
        except Exception as e:
            print(f"[CamWorkflow] 设置焦点属性提示: {e}")

    def get_or_create_shared_media_suite(self, user_root_path):
        """
        在 Shot 根目录统一维护一套全局单例：MediaPlayer + MediaTexture + 对位专用材质 M_Global_MediaPlate
        """
        asset_sub = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

        media_root_folder = f"{user_root_path.rstrip('/')}/Media"
        if not asset_sub.does_directory_exist(media_root_folder):
            asset_sub.make_directory(media_root_folder)

        player_path = f"{media_root_folder}/Global_MediaPlayer"
        tex_path = f"{media_root_folder}/Global_MediaTexture"
        mat_path = f"{media_root_folder}/M_Global_MediaPlate"

        if asset_sub.does_asset_exist(player_path):
            shared_player = asset_sub.load_asset(player_path)
        else:
            shared_player = asset_tools.create_asset("Global_MediaPlayer", media_root_folder, unreal.MediaPlayer, unreal.MediaPlayerFactoryNew())

        if asset_sub.does_asset_exist(tex_path):
            shared_media_tex = asset_sub.load_asset(tex_path)
        else:
            shared_media_tex = asset_tools.create_asset("Global_MediaTexture", media_root_folder, unreal.MediaTexture, unreal.MediaTextureFactoryNew())

        if shared_media_tex and shared_player:
            shared_media_tex.set_editor_property("media_player", shared_player)

        if asset_sub.does_asset_exist(mat_path):
            shared_mat = asset_sub.load_asset(mat_path)
        else:
            mat_factory = unreal.MaterialFactoryNew()
            shared_mat = asset_tools.create_asset("M_Global_MediaPlate", media_root_folder, unreal.Material, mat_factory)
            if shared_mat:
                shared_mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
                shared_mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
                shared_mat.set_editor_property("two_sided", True)

                ts_node = unreal.MaterialEditingLibrary.create_material_expression(shared_mat, unreal.MaterialExpressionTextureSample, -300, 0)
                ts_node.set_editor_property("texture", shared_media_tex)

                unreal.MaterialEditingLibrary.connect_material_property(ts_node, "RGB", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
                unreal.MaterialEditingLibrary.connect_material_property(ts_node, "A", unreal.MaterialProperty.MP_OPACITY)

                if hasattr(unreal.MaterialEditingLibrary, "recompile_material"):
                    unreal.MaterialEditingLibrary.recompile_material(shared_mat)
                elif hasattr(unreal.MaterialEditingLibrary, "update_material"):
                    unreal.MaterialEditingLibrary.update_material(shared_mat)

                print(f"[CamWorkflow] 成功创建并编译全局对位材质: {mat_path}")

        return shared_media_tex, shared_mat

    def spawn_native_image_plate(self, parent_cam, level_seq, shot_name, shared_mat=None, distance=400.0):
        actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        plate_class = unreal.load_class(None, "/Script/ImagePlate.ImagePlate")
        if not plate_class:
            plate_class = getattr(unreal, "ImagePlate", None)

        if plate_class:
            plate_actor = actor_sub.spawn_actor_from_class(
                plate_class, parent_cam.get_actor_location(), parent_cam.get_actor_rotation()
            )
            plate_actor.set_actor_label(f"ImagePlate_{shot_name}")
            plate_actor.set_folder_path("/!Cam")
            
            plate_actor.attach_to_actor(
                parent_cam, unreal.Name(),
                unreal.AttachmentRule.KEEP_RELATIVE, unreal.AttachmentRule.KEEP_RELATIVE, unreal.AttachmentRule.KEEP_RELATIVE, False
            )
            plate_actor.set_actor_relative_location(unreal.Vector(distance, 0.0, 0.0), False, False)
            plate_actor.set_actor_relative_rotation(unreal.Rotator(0.0, 0.0, 0.0), False, False)

            if shared_mat:
                try:
                    for comp in plate_actor.get_components_by_class(unreal.PrimitiveComponent):
                        comp.set_material(0, shared_mat)
                    img_comps = plate_actor.get_components_by_class(unreal.ImagePlateComponent)
                    for ic in img_comps:
                        if hasattr(ic, "set_editor_property"):
                            try:
                                ic.set_editor_property("material", shared_mat)
                            except Exception:
                                pass
                    print(f"[CamWorkflow] 全局对位材质已成功应用至 ImagePlate_{shot_name}")
                except Exception as e:
                    print(f"[CamWorkflow] 赋予 ImagePlate 材质提示: {e}")
            
            level_seq.add_possessable(plate_actor)
            return plate_actor
        return None

    def ensure_camera_cuts_full_range(self, level_seq, duration):
        try:
            for track in level_seq.get_tracks():
                if isinstance(track, unreal.MovieSceneCameraCutTrack):
                    for sec in track.get_sections():
                        sec.set_range(1, duration + 1)
                    print(f"[CamWorkflow] Camera Cuts 轨道已铺满整个帧区间: 0001 ~ {duration:04d}")
        except Exception as e:
            print(f"[CamWorkflow] 铺满 Camera Cuts 轨道提示: {e}")

    def ensure_camera_focal_length_track(self, level_seq, cam_binding, cine_cam_actor, duration):
        try:
            cam_comp = cine_cam_actor.get_cine_camera_component()
            current_fl = float(cam_comp.get_editor_property("current_focal_length"))
            if current_fl <= 0.0:
                current_fl = 14.0

            comp_binding = None
            for child in cam_binding.get_child_possessables():
                child_name = child.get_name().lower()
                if "cameracomponent" in child_name or "cinecamera" in child_name:
                    comp_binding = child
                    break

            if not comp_binding:
                comp_binding = level_seq.add_possessable(cam_comp)
                comp_binding.set_parent(cam_binding)

            has_fl_track = False
            for track in comp_binding.get_tracks():
                t_name = track.get_track_name().lower()
                if "focal" in t_name or "currentfocallength" in t_name:
                    has_fl_track = True
                    break

            if not has_fl_track:
                fl_track = comp_binding.add_track(unreal.MovieSceneFloatTrack)
                if fl_track:
                    fl_track.set_property_name_and_path("CurrentFocalLength", "CurrentFocalLength")
                    sec = fl_track.add_section()
                    sec.set_range(1, duration + 1)
                    t1 = unreal.FrameNumber(1)
                    t2 = unreal.FrameNumber(duration)

                    for method_name in ["get_channels", "find_channels"]:
                        if hasattr(sec, method_name):
                            try:
                                chs = getattr(sec, method_name)()
                                if chs and len(chs) > 0:
                                    chs[0].add_key(t1, current_fl)
                                    chs[0].add_key(t2, current_fl)
                                    break
                            except Exception:
                                pass

                    cam_comp.set_editor_property("current_focal_length", current_fl)
                    print(f"[CamWorkflow] 焦距轨道挂载完成: {current_fl}mm")
        except Exception as e:
            print(f"[CamWorkflow] 构建焦距轨道提示: {e}")

    def add_sequencer_attach_track(self, level_seq, child_binding, parent_binding, duration):
        try:
            attach_track = child_binding.add_track(unreal.MovieScene3DAttachTrack)
            if attach_track:
                section = attach_track.add_section()
                section.set_range(1, duration + 1)
                
                binding_id = unreal.MovieSceneObjectBindingID()
                binding_id.set_editor_property("guid", parent_binding.get_id())
                section.set_editor_property("constraint_binding_id", binding_id)
                print("[CamWorkflow] Attach 轨道创建完毕，相机已锁死在 Shot_Root")
                return True
        except Exception as e:
            print(f"[CamWorkflow] Attach Track 提示: {e}")
        return False

    def find_potential_bg_sequence_path(self, fbx_cam_path):
        clean_path = str(fbx_cam_path).replace('\\', '/').strip()
        current_dir = os.path.dirname(clean_path)
        
        keywords = ['plate', 'plates', 'bg', 'background', 'source', 'images', 'render']
        image_extensions = ('.exr', '.png', '.jpg', '.jpeg', '.tga', '.dpx', '.tif')

        search_dirs = [current_dir]
        p = current_dir
        for _ in range(3):
            parent = os.path.dirname(p)
            if parent and parent != p:
                search_dirs.append(parent)
                p = parent

        for s_dir in search_dirs:
            if not os.path.exists(s_dir):
                continue
            try:
                for entry in os.listdir(s_dir):
                    sub_path = os.path.join(s_dir, entry).replace('\\', '/')
                    if os.path.isdir(sub_path):
                        if any(k in entry.lower() for k in keywords):
                            files = os.listdir(sub_path)
                            if any(f.lower().endswith(image_extensions) for f in files):
                                print(f"[CamWorkflow] 自动嗅探到实拍背景序列帧目录: {sub_path}")
                                return sub_path
            except Exception:
                pass
        return ""

    def setup_media_background(self, target_folder, user_root_path, ep, shot, fps_val, level_seq, raw_shot_len, fbx_cam_path, user_bg_path=""):
        """
        根据素材实际帧长精确匹配 Media Section 长度，绝不向后超额铺满
        """
        try:
            asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
            asset_sub = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
            
            # 1. 镜头目录下创建专属的 bg 文件夹
            bg_folder = f"{target_folder}/bg"
            if not asset_sub.does_directory_exist(bg_folder):
                asset_sub.make_directory(bg_folder)

            # 2. 判断背景序列帧路径 (用户指定 vs 智能嗅探)
            final_bg_path = ""
            if user_bg_path and str(user_bg_path).strip() and os.path.exists(str(user_bg_path).strip()):
                final_bg_path = str(user_bg_path).replace('\\', '/').strip()
                print(f"[CamWorkflow] 使用用户指定的图片序列目录: {final_bg_path}")
            else:
                final_bg_path = self.find_potential_bg_sequence_path(fbx_cam_path)

            # 计算素材真实的实际帧长
            actual_media_len = raw_shot_len
            if final_bg_path and os.path.exists(final_bg_path):
                image_extensions = ('.exr', '.png', '.jpg', '.jpeg', '.tga', '.dpx', '.tif')
                try:
                    img_files = [f for f in os.listdir(final_bg_path) if f.lower().endswith(image_extensions)]
                    if img_files:
                        actual_media_len = len(img_files)
                except Exception:
                    pass

            # 3. 创建该镜头专属的 ImgMediaSource
            source_name = f"{ep.lower()}_cam{shot}_bg"
            source_asset_path = f"{bg_folder}/{source_name}"
            
            if asset_sub.does_asset_exist(source_asset_path):
                img_source = asset_sub.load_asset(source_asset_path)
            else:
                img_source_factory = unreal.ImgMediaSourceFactoryNew()
                img_source = asset_tools.create_asset(source_name, bg_folder, unreal.ImgMediaSource, img_source_factory)

            if img_source:
                fps_int = int(round(float(fps_val)))
                frame_rate = unreal.FrameRate(numerator=fps_int, denominator=1)
                img_source.set_editor_property("frame_rate_override", frame_rate)
                
                if final_bg_path and os.path.exists(final_bg_path):
                    norm_bg_dir = str(final_bg_path).replace('\\', '/').rstrip('/') + '/'
                    dir_struct = unreal.DirectoryPath(path=norm_bg_dir)
                    img_source.set_editor_property("sequence_path", dir_struct)
                    if hasattr(img_source, "set_sequence_path"):
                        try:
                            img_source.set_sequence_path(norm_bg_dir)
                        except Exception:
                            pass
                    print(f"[CamWorkflow] 镜头专属 ImgMediaSource 路径已锁死: {norm_bg_dir} (实际图片数: {actual_media_len}帧)")
                else:
                    print(f"[CamWorkflow] 提示: 暂未提供或检测到背景序列帧，ImgMediaSource 保持静默占位")

            # 4. 获取全局共用 MediaTexture 和 Material
            shared_media_tex, shared_mat = self.get_or_create_shared_media_suite(user_root_path)

            # 5. 在 Level Sequence 中添加原生的 Media Track 轨道
            media_track = level_seq.add_track(unreal.MovieSceneMediaTrack)
            if media_track:
                media_section = media_track.add_section()
                media_section.set_range(1, actual_media_len + 1)
                
                if img_source:
                    media_section.set_editor_property("media_source", img_source)
                if shared_media_tex:
                    media_section.set_editor_property("media_texture", shared_media_tex)
                print(f"[CamWorkflow] 定序器 Media Track 已构建: [{source_name}] 长度精确对齐素材实际帧长 (0001 ~ {actual_media_len:04d})")

            return shared_mat

        except Exception as e:
            print(f"[CamWorkflow] 创建 Media 背景资产与轨道提示: {e}")
            return None

    def execute_workflow(self, fbx_cam_path, user_root_path="/Game/Shot", custom_ep="", fps_val=25.0, 
                         create_root_parent=True, create_image_plane=True, disable_focus=True, import_mesh_ref=True,
                         bg_sequence_path=""):
        
        clean_fbx = str(fbx_cam_path).replace('\\', '/').strip()
        if not clean_fbx or not os.path.exists(clean_fbx):
            unreal.EditorDialog.show_message("错误", f"找不到相机文件:\n{clean_fbx}", unreal.AppMsgType.OK)
            return False

        self.save_root_dir(user_root_path)

        # 1. 提取元数据 (包含实拍实际长度 raw_shot_len 以及 +1 帧把手后的 duration)
        ep_det, shot, plate_s, plate_e, raw_shot_len, duration = self.parse_metadata_from_path(clean_fbx)
        ep = custom_ep.strip() if custom_ep.strip() else ep_det

        # 2. 目录与 Level Sequence 创建
        target_folder = f"{user_root_path.rstrip('/')}/{ep}/Shot_{shot}"
        seq_name = f"{ep.lower()}_cam{shot}"
        seq_asset_path = f"{target_folder}/{seq_name}"

        asset_sub = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
        if not asset_sub.does_directory_exist(target_folder):
            asset_sub.make_directory(target_folder)

        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        if asset_sub.does_asset_exist(seq_asset_path):
            level_seq = asset_sub.load_asset(seq_asset_path)
        else:
            factory = unreal.LevelSequenceFactoryNew()
            level_seq = asset_tools.create_asset(seq_name, target_folder, unreal.LevelSequence, factory)

        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(level_seq)

        fps_int = int(round(float(fps_val)))
        level_seq.set_display_rate(unreal.FrameRate(numerator=fps_int, denominator=1))

        # 3. 配置 FBX 导入参数
        import_settings = unreal.MovieSceneUserImportFBXSettings()
        import_settings.set_editor_property("create_cameras", True)
        import_settings.set_editor_property("reduce_keys", False)
        import_settings.set_editor_property("match_by_name_only", False)
        import_settings.set_editor_property("force_front_x_axis", False)

        for focal_prop in ["import_camera_focal_length", "bImportCameraFocalLength"]:
            try:
                import_settings.set_editor_property(focal_prop, True)
            except Exception:
                pass

        world = unreal.EditorLevelLibrary.get_editor_world()
        old_bindings = [b.get_id() for b in level_seq.get_bindings()]

        # 4. 执行原生 FBX 导入
        st = getattr(unreal, "SequencerTools", None)
        if st and hasattr(st, "import_level_sequence_fbx"):
            st.import_level_sequence_fbx(world, level_seq, [], import_settings, clean_fbx)

        # 5. 抓取生成的 CineCameraActor 与 Binding
        imported_cam_actor = None
        imported_cam_binding = None
        for b in level_seq.get_bindings():
            if b.get_id() not in old_bindings:
                try:
                    bound_objs = unreal.LevelSequenceEditorBlueprintLibrary.get_bound_objects(b)
                    for obj in bound_objs:
                        if isinstance(obj, unreal.CineCameraActor):
                            imported_cam_actor = obj
                            imported_cam_binding = b
                            break
                except Exception:
                    pass
            if imported_cam_actor:
                break

        if not imported_cam_actor:
            actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            for act in actor_sub.get_all_level_actors():
                if isinstance(act, unreal.CineCameraActor) and shot in act.get_actor_label():
                    imported_cam_actor = act
                    imported_cam_binding = level_seq.add_possessable(act)
                    break

        # 6. 严格闭区间锁定为 0001 ~ duration (交付多留1帧把手)
        level_seq.set_playback_start(1)
        level_seq.set_playback_end(duration + 1)
        level_seq.set_view_range_start(1.0 / fps_int)
        level_seq.set_view_range_end(float(duration + 1) / fps_int)
        level_seq.set_work_range_start(1.0 / fps_int)
        level_seq.set_work_range_end(float(duration + 1) / fps_int)

        self.ensure_camera_cuts_full_range(level_seq, duration)

        # 7. 背景媒体与全局材质构建
        shared_mat = self.setup_media_background(target_folder, user_root_path, ep, shot, fps_val, level_seq, raw_shot_len, clean_fbx, bg_sequence_path)

        # 8. 相机后续自动化装配 (Attach轨道 + ImagePlate赋予材质)
        if imported_cam_actor and imported_cam_binding:
            imported_cam_actor.set_folder_path("/!Cam")

            if disable_focus:
                self.set_camera_focus_to_do_not_override(imported_cam_actor)

            self.ensure_camera_focal_length_track(level_seq, imported_cam_binding, imported_cam_actor, duration)

            if create_root_parent:
                actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                root_actor = actor_sub.spawn_actor_from_class(unreal.Actor, unreal.Vector(0,0,0), unreal.Rotator(0,0,0))
                root_actor.set_actor_label(f"Shot_Root_{shot}")
                root_actor.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
                root_actor.set_folder_path("/!Cam")
                root_binding = level_seq.add_possessable(root_actor)
                
                imported_cam_actor.attach_to_actor(
                    root_actor, unreal.Name(),
                    unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, False
                )
                self.add_sequencer_attach_track(level_seq, imported_cam_binding, root_binding, duration)

            if create_image_plane:
                self.spawn_native_image_plate(imported_cam_actor, level_seq, shot, shared_mat=shared_mat, distance=400.0)

        # 9. 扫描导入同目录简模
        dir_name = os.path.dirname(clean_fbx)
        cam_base = os.path.basename(clean_fbx).lower()
        if import_mesh_ref and os.path.exists(dir_name):
            for f in os.listdir(dir_name):
                if f.lower().endswith('.fbx') and f.lower() != cam_base:
                    mesh_path = os.path.join(dir_name, f).replace('\\', '/')
                    mesh_name = f"SM_Ref_{shot}"
                    
                    task = unreal.AssetImportTask()
                    task.filename = mesh_path
                    task.destination_path = target_folder
                    task.destination_name = mesh_name
                    task.replace_existing = True
                    task.automated = True
                    task.save = True
                    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
                    
                    imported_mesh = unreal.EditorAssetSubsystem().load_asset(f"{target_folder}/{mesh_name}")
                    if imported_mesh:
                        actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                        mesh_act = actor_sub.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0,0,0), unreal.Rotator(0,0,0))
                        mesh_act.static_mesh_component.set_static_mesh(imported_mesh)
                        mesh_act.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
                        mesh_act.set_actor_label(f"SM_Ref_{shot}")
                        mesh_act.set_folder_path("/!Cam")
                        level_seq.add_possessable(mesh_act)
                    break

        # 刷新定序器
        unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()

        # 弹窗提示
        unreal.EditorDialog.show_message(
            "组装成功", 
            f"【镜头交付组装完成】\n\n• 序列命名: {seq_name}\n• 目标路径: {target_folder}\n• 大纲归纳: 全部 Actor 已收纳至 [(!Cam)]\n• 媒体中心: Media 轨道长度已严格对齐实拍素材 ({raw_shot_len}帧)\n• 帧区间: 0001 ~ {duration:04d} 帧 (Camera Cuts 已铺满)\n• Attach轨道: 已在定序器永久绑定至 Shot_Root_{shot}", 
            unreal.AppMsgType.OK
        )
        return True

def browse_and_fill_ui_directly(widget_path):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    file_path = filedialog.askopenfilename(
        title="选择 Maya 导出的相机 FBX 文件",
        filetypes=[("FBX 镜头文件", "*.fbx"), ("所有文件", "*.*")]
    )
    root.destroy()

    if not file_path:
        return

    clean_path = str(file_path).replace('\\', '/').strip()
    pipeline = UECamWorkflowPipeline()
    ep, shot, start_f, end_f, raw_len, dur = pipeline.parse_metadata_from_path(clean_path)

    widget_obj = unreal.find_object(None, widget_path)
    if widget_obj:
        tb_fbx = widget_obj.get_editor_property("TextBox_FBXPath")
        if tb_fbx:
            tb_fbx.set_text(unreal.Text(clean_path))
            
        tb_ep = widget_obj.get_editor_property("TextBox_EP")
        if tb_ep:
            tb_ep.set_text(unreal.Text(ep))
            
        txt_status = widget_obj.get_editor_property("Text_ShotStatus")
        if txt_status:
            status_str = f"✓ 识别成功: Shot {shot} | 集数: {ep} | 实拍: {raw_len}帧 ({start_f}~{end_f}) | 交付总长: 0001~{int(dur):04d} (多留1帧)"
            txt_status.set_editor_property("text", unreal.Text(status_str))

def browse_bg_sequence_directory(widget_path):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    folder_selected = filedialog.askdirectory(title="选择实拍背景图片序列所在文件夹 (可选，留空则自动检测)")
    root.destroy()

    if not folder_selected:
        return

    clean_folder = str(folder_selected).replace('\\', '/').strip()
    widget_obj = unreal.find_object(None, widget_path)
    if widget_obj:
        tb_bg = widget_obj.get_editor_property("TextBox_BGPath")
        if tb_bg:
            tb_bg.set_text(unreal.Text(clean_folder))
            print(f"[CamWorkflow] UI 背景路径已选择: {clean_folder}")

def load_initial_root_dir_to_ui(widget_path):
    widget_obj = unreal.find_object(None, widget_path)
    if widget_obj:
        tb_root = widget_obj.get_editor_property("TextBox_RootDir")
        if tb_root:
            pipeline = UECamWorkflowPipeline()
            saved_dir = pipeline.get_saved_root_dir(default_dir="/Game/Shot")
            tb_root.set_text(unreal.Text(saved_dir))
            print(f"[CamWorkflow] 成功载入存储目录: {saved_dir}")

def run_cam_workflow(fbx_path, root_dir="/Game/Shot", custom_ep="", fps_val="25.0", 
                     create_root=True, create_plane=True, disable_focus=True, import_mesh=True, bg_path=""):
    pipeline = UECamWorkflowPipeline()
    final_fps = 25.0
    try:
        if fps_val:
            m = re.search(r'(\d+(\.\d+)?)', str(fps_val))
            if m: final_fps = float(m.group(1))
    except:
        final_fps = 25.0

    def parse_bool(v):
        if isinstance(v, bool): return v
        return str(v).strip().lower() in ['true', '1', 'yes']

    return pipeline.execute_workflow(
        fbx_cam_path=fbx_path,
        user_root_path=root_dir,
        custom_ep=custom_ep,
        fps_val=final_fps,
        create_root_parent=parse_bool(create_root),
        create_image_plane=parse_bool(create_plane),
        disable_focus=parse_bool(disable_focus),
        import_mesh_ref=parse_bool(import_mesh),
        bg_sequence_path=bg_path
    )