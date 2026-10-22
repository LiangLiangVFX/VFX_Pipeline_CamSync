<div align="center">

# 🎬 VFX_Pipeline_CamSync

**面向 Maya、Unreal Engine 5.3/5.4 与 Foundry Nuke 的全流程影视特效自动化管线套件**  
*End-to-End Automated VFX Camera Sync, UE5 Shot Assembly, Render Layer Split & MRQ Center, Multi-Engine AI Matting & Nuke Auto-Comp Pipeline*

[![Maya](https://img.shields.io/badge/Maya-Drag%20%26%20Drop%20Installer-37a5cc.svg)](#)
[![UE5](https://img.shields.io/badge/UE%205.3%20%7C%205.4-Standalone%20Plugin-0e1128.svg)](#)
[![MRQ](https://img.shields.io/badge/UE5%20MRQ-Render%20Layer%20v5.8%20Pro-10b981.svg)](#)
[![Nuke](https://img.shields.io/badge/Nuke-One--Click%20Deploy-f5a623.svg)](#)
[![AI Matting](https://img.shields.io/badge/AI%20Engines-BiRefNet%20%7C%20MatAnyone2%20%7C%20SAM2Matting-success.svg)](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)
[![Python](https://img.shields.io/badge/Python-2.7%20%7C%203.x-yellow.svg)](#)
[![YouTube](https://img.shields.io/badge/YouTube-@zhaol2259-ff0000.svg)](https://www.youtube.com/@zhaol2259)
[![Bilibili](https://img.shields.io/badge/Bilibili-LiangLiangArtist-19a3d6.svg)](https://space.bilibili.com/75504176)

</div>

---

## 📖 项目概述 (Overview)

**`VFX_Pipeline_CamSync`** 是一套专为现代影视视效（VFX）与虚幻引擎（Unreal Engine 5）制片流程研发的**跨软件（Maya $\leftrightarrow$ Nuke $\leftrightarrow$ UE 5.3/5.4）全链路自动化管线工具集**（仓库内附带完整测试示例工程）。

针对传统影视制作中跨软件协同配置繁琐、灯光雾效拆层易出错、多镜头批量渲染易串路径等痛点，本套工具在三大 DCC 软件端均实现了**零门槛自动化部署**（Maya 视口拖拽安装、UE5 独立插件包、Nuke 双击一键安装），并通过统一的镜头目录规范将**五大核心生产环节**彻底打通：

1. **Maya 端 (`LiangLiangCamExporter`)**：拖拽 `dragDropInstaller.mel` 至视口即可自动生成工具架按钮。一站式完成厘米级人偶比例校对、原地轴心缩放、世界零点重定向、纯净相机烘焙与 `1001 -> 0001` 帧平移导出。
2. **Nuke 前置端 (`实拍预处理 + 三大 SOTA AI 抠像引擎`)**：一键构建实拍 LogC/sRGB 预处理网络，无缝调度配套算力仓 **[AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)** 中的 **BiRefNet (2K高清万物)**、**MatAnyone 2 (CVPR 2026)** 与 **SAM2Matting (ECCV 2026)** 生成发丝级透明底板 `bg_{shot}_####.png` 供 UE 对位。
3. **UE 5.3/5.4 镜头装配端 (`LiangLiangUECamWorkflow`)**：插件化封装，一键解析 FBX 元数据，自动构建定序器（Level Sequence）、`Shot_Root` 绑定、全局共享 `ImagePlate` 实拍背景轨道（精确对齐素材帧长）以及自动开启 **Nanite** 的静态参考简模。
4. **UE 5.3/5.4 分层裂变与 MRQ 调度端 (`LiangLiangUERenderLayer v5.8 Studio Pro`)**：一键完成主关卡灯光/雾气子关卡自动拆分归类（0 卡顿跳过静态场景模型），支持**单层快速**与**多层全拆分（`env / key / sky / fill / heightfog / fog / emiss / ID_actor / ID_material`）**双模式序列裂变、纯净 `CVarPresets` 雾气控制台变量注入、多镜头 100% 独立路径隔离的 MRQ 批量队列调度，以及**每个镜头渲染完成即刻自动弹出对应输出目录**。
5. **Nuke 后置端 (`UE 分层自动预合成与 ID 拆层`)**：自动嗅探 UE 最新发布版本（`publish/vXXX/render`），自适应构建单层或多层灯光（`plus`）/雾效（`screen`）预合成主干、AI 前景自动汇合（`Merge_Comp_Over`）以及 `WorldDepth / WorldNormal / WorldPos / Cryptomatte` 通道拆解网。

---

## 🔄 全流程数据流向图 (End-to-End Pipeline Architecture)

```text
  ┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                              [标准镜头工作区规范] .../{ep}/{shot}/ue/                                   │
  └──────────────────────────────────────────────────┬─────────────────────────────────────────────────────┘
                                                     │
        ┌────────────────────────────────────────────┼────────────────────────────────────────────┐
        ▼                                            ▼                                            ▼
┌──────────────────────┐                  ┌──────────────────────┐                  ┌──────────────────────────────┐
│  1. Autodesk Maya    │                  │ 2. Foundry Nuke (前)  │                  │ 3. UE 5.3/5.4 (镜头装配端)    │
│ ──────────────────── │                  │ ──────────────────── │                  │ ──────────────────────────── │
│ • 吸附人偶 & 100x缩放 │                  │ • 实拍 LogC/sRGB 转换 │                  │ • 自动构建母版 LevelSequence  │
│ • 首帧/目标对准世界零点│   cam2180.fbx    │ • BiRefNet/MatAnyone2│   bg_2180.png    │ • 挂载 ImagePlate 实拍背景对位│
│ • 动/定焦判别与纯烘焙 ├─────────────────►│   /SAM2Matting AI抠像├─────────────────►│ • 参考简模转 Static + Nanite │
│ • 1001帧自动平移至 1 帧│   model_ref.fbx  │ • 输出透明预乘前景底板 │                  │ • 持久化记录镜头路径映射配置   │
└──────────────────────┘                  └──────────┬───────────┘                  └──────────────┬───────────────┘
                                                     │                                             │
                                                     │                                             ▼
                                                     │                              ┌──────────────────────────────┐
                                                     │                              │ 4. UE 5.3/5.4 (分层与MRQ中心) │
                                                     │                              │ ──────────────────────────── │
                                                     │                              │ • 灯光/雾自动拆分子关卡(0卡顿)│
                                                     │                              │ • 单层/多层序列裂变 & CVar雾控│
                                                     │                              │ • 三大AOV/ID预设深拷贝独立隔离│
                                                     │                              │ • 单镜头渲染完即刻弹出输出目录│
                                                     │                              └──────────────┬───────────────┘
                                                     │                                             │
                                                     │              ┌──────────────────────────────┘
                                                     ▼              ▼ (ue/publish/vXXX/render/*.exr)
                                          ┌──────────────────────────────────────┐
                                          │         5. Foundry Nuke (后)          │
                                          │ ──────────────────────────────────── │
                                          │ • 四大横向正交模块自动排布 (零重叠)    │
                                          │ • 单/多层灯光(Plus)与雾效(Screen)合成 │
                                          │ • AI 发丝前景自动连入 Merge_Comp_Over │
                                          │ • WorldDepth/Normal/Pos & Crypto 拆层│
                                          │ • HorizonWriteNode 输出最终预览 MOV   │
                                          └──────────────────────────────────────┘
```

---

## 🚀 极速安装指南 (Zero-Config Installation)

### 1. Maya 端：直接拖拽自动安装 (`dragDropInstaller.mel`)
1. 打开 Autodesk Maya，在资源管理器中按住 **`dragDropInstaller.mel`** 直接**拖拽并释放到 Maya 3D 视口中**。
2. 脚本将自动将 `LiangLiangCamExporter.py` 与 `SM_Pose.fbx` 部署至 `userScriptDir`，将 `icon.png` 部署至 `userPrefDir/icons/`，并在顶部工具架创建 **`[LiangLiangArtist]`** 专属标签页与 **`UE_Cam`** 启动图标。

### 2. Unreal Engine 5.3 / 5.4 端：独立插件化部署 (`Plugin`)
1. 将仓库中的 UE 插件文件夹复制到 UE 工程根目录下的 **`Plugins/`** 文件夹中。
2. 启动 UE 工程（确保已开启官方内置的 `Python Editor Script Plugin`、`Sequencer Scripting`、`Image Plate`、`Movie Render Queue`、`Movie Render Queue Additional Render Passes` 与 `Console Variables Editor` 插件）。
3. 通过插件工具栏即可一键唤起 **镜头资产全自动装配面板 (`LiangLiangUECamWorkflow`)** 与 **分层裂变及 MRQ 自动化调度中心 (`LiangLiangUERenderLayer`)**。

### 3. Nuke 端：双击一键安装 (`一键安装(双击运行).bat`)
1. 进入 `Nuke/NukeWorkflowTool/` 目录，双击运行 **`一键安装(双击运行).bat`**，自动完成 Nuke 双栏菜单与图标部署。
2. **关联 AI 算力后端**：克隆 **[AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)**，解压其 Releases 环境包后双击 `一键注册AI引擎环境(双击运行).bat`，Nuke 即可自动桥接三大 AI 抠像引擎。

---

## 🛠️ 四大核心模块深度解析 (Core Toolsets)

### 一、 Autodesk Maya：镜头标准化交付工具 (`LiangLiangCamExporter.py`)

* **工程元数据与路径嗅探**：自动解析集数（保留原始大小写）与镜头号，向上 6 层目录智能回溯嗅探 `ue/workarea` 规范目录。
* **厘米级比例对准与原地缩放**：一键加载 `SM_Pose.fbx` 标准参考人偶，选中跟踪参考物即可自动吸附脚底中心并对齐缩放组轴心（`UE_Interactive_Scale_Pivot_Grp`），支持 `1x`、`100x` 及滑块无极原地缩放，自动将相机 `farClipPlane` 设为 `10,000,000` 防止视口裁切。
* **虚幻空间坐标重定向**：提供 **🧭 相机首帧水平归零**、**📍 选中目标对准零点** 与 **↩️ 还原原始世界坐标** 三大功能，彻底解决进 UE 后离世界原点过远导致的精度抖动。
* **纯净相机烘焙与动/定焦判别**：逐帧烘焙世界坐标并严格过滤非 `Translate/Rotate` 通道（锁定 `scale=1.0`）；自动判别真变焦与定焦镜头；导出 `cam{shot}_{plate_start}_{plate_end}.fbx` 时自动将内部动画平移至 `1 ~ duration` 帧以对齐 UE `0001` 帧，并支持同步导出 `{shot}_model_ref.fbx` 简模。

---

### 二、 Unreal Engine 5：镜头资产全自动装配插件 (`LiangLiangUECamWorkflow.py`)

* **Shot 目录递归嗅探**：自动扫描 `Content` 目录匹配 `/Game/.../Shot` 路径并持久化记忆至 `Saved/UECamWorkflowConfig.json`。
* **定序器闭区间锁定与相机修正**：自动创建 `{ep}_cam{shot}` 定序器，锁定 `0001 ~ duration`（多留 1 帧把手）并铺满 `Camera Cuts`；自动将相机焦点设为 `Do Not Override`、补齐焦距轨道、生成 `Shot_Root_{shot}` 并通过 `Attach` 轨道锁死相机，全部 Actor 统一收纳至世界大纲 **`/!Cam`**。
* **全局共享媒体套组与 `ImagePlate` 对位**：自动构建 `M_Global_MediaPlate` 双面无光照半透明材质并赋予相机前方的 `ImagePlate_{shot}`；向上 3 层目录自动嗅探实拍序列帧，生成长度严格对齐实拍张数的 `Media Track`。
* **参考简模强制 Static Mesh + Nanite 导入**：自动将同目录参考简模以静态网格体合并导入（`import_as_skeletal=False`, `combine_meshes=True`），强制激活 **`Build Nanite`** 并挂入定序器。

---

### 三、 Unreal Engine 5：影视级分层裂变与 MRQ 自动化调度中心 (`LiangLiangUERenderLayer.py` v5.8 Studio Pro)

专为 UE 5.3 / 5.4 打造的工业级深色卡片式渲染调度中心，完美承接母版镜头定序器并向下游 Nuke 自动预合成输送标准化分层 EXR 序列：

#### 1. 双模式分层裂变体系与自发光总控
* **模式一：单层快速模式 (`single`)**：保留母版全关卡直出序列，并自动派生 `cam{shot}_ID_actor` 与 `cam{shot}_ID_material` 两个通道层，适合无需拆分灯光的快速交付镜头。
* **模式二：多层全拆分模式 (`multi`)**：从母版序列一键裂变生成 `cam{shot}_env`、`cam{shot}_key`、`cam{shot}_sky`、`cam{shot}_fill`、`cam{shot}_heightfog`、`cam{shot}_fog`、`cam{shot}_ID_actor`、`cam{shot}_ID_material` 全套子序列，自动剥离派生层的 `MediaTrack`、隐藏 `ImagePlate` 与 `SM_Ref` 对位简模，并注入前置 100 帧预热（`start_frame - 100`）的 `LevelVisibilityTrack`。
* **自发光独立层 (`cam{shot}_emiss`)**：单/多层模式均支持勾选生成，自动在 `/Game/{Project}/Shot/Collection` 下创建 `MPC_Global_Emiss` 材质参数集并注入控制轨道（`emiss` 层自动将 `Emiss` 标量设为 `1.0`，其余层自动设为 `0.0`）。
* **内容浏览器自动定位**：创建分层或重新入列后，UE 内容浏览器自动跳转并高亮生成的序列资产。

#### 2. 子关卡映射矩阵与 0 卡顿场景自动拆分
支持自定义前缀（`night_`、`day_`、`dusk_` 等），一键创建空白子关卡或自动将主关卡中的灯光与雾气 Actor 分类移入对应子关卡，并统一收纳至 Levels 面板的 **`[Light]`** 文件夹中（主渲染关卡自动保留 `PostProcessVolume`、相机与对位资产）：

| 角色标识 (`Role`) | 默认子关卡后缀 | 标准存放目录 | 子关卡包含内容与自动化拆分规则 |
| :--- | :--- | :--- | :--- |
| **`scence`** | `scence` | `Map/Scence` | 静态网格体(`StaticMesh`)、地形(`Landscape`)、建筑、植被（**自动跳过移动，0 卡顿**） |
| **`env`** | `{prefix}env_lgt` | `Map/Light` | 环境天光层：仅存放天光 (`SkyLight`) |
| **`key`** | `{prefix}key_lgt` | `Map/Light` | 主方向光层：仅存放主平行光 (`DirectionalLight` 太阳光/月光) |
| **`sky`** | `{prefix}sky_lgt` | `Map/Light` | 纯天空层（**不含场景模型**）：天空球 (`SM_SkySphere`/`BP_Sky`)、大气 (`SkyAtmosphere`)、体积云 |
| **`heightfog`** | `{prefix}heightfog` | `Map/Light` | 指数高度雾层：仅存放指数高度雾 (`ExponentialHeightFog`)，渲染时自动联带 `scence + key + env` |
| **`fill`** | `{prefix}fill01_lgt` | `Map/Light` | 场景补光层：局部点光源 (`PointLight`)、聚光灯 (`SpotLight`)、矩形光 (`RectLight`) |
| **`fog`** | `{prefix}fog` | `Map/Light` | 半透明雾片层：`EasyFog` 雾片蓝图、局部半透明雾气面片，渲染时自动联带 `scence + key + env` |

#### 3. 纯净 `CVarPresets` 雾气控制与底层防崩溃保护
* 自动在 `/Game/{Project}/Shot/CVarPresets` 下生成或复用三大控制台变量资产并注入定序器 `MovieSceneCVarTrack`：
  * **`CVar_HeightFog_Only`**（用于 `heightfog` 层）：`ShowFlag.Diffuse=0, Specular=0, Translucency=0, Fog=2`
  * **`CVar_EasyFog_Only`**（用于 `fog` 半透明雾片层）：`ShowFlag.Diffuse=0, Specular=0, Translucency=2, Fog=0`
  * **`CVar_Default_Restore`**（用于其余常规层保底还原）：四大 `ShowFlag` 全还原为 `2`
* **黑名单污染清洗与防崩机制**：内置 `POLLUTED_MRQ_CVARS` 清洗黑名单，并通过先载入空资产初始化 `ConsoleVariablesEditor` 底层智能指针（100% 根除 UE 底层 `SharedPointer.h:1113` 崩溃），确保每个预设严格只含 4 个 `ShowFlag` 参数，不影响 MRQ `Game Overrides` 正常工作。

#### 4. MRQ 三大预设绑定、多镜头 100% 独立隔离与即刻弹窗 (v5.8 核心升级)
* **三大预设智能匹配**：自动扫描并绑定插件内置（`/CamWorkflowTools/RenderConfig/`）或工程内的 `AOV_RenderSet`（Beauty 主渲染）、`AOV_RenderSet_ID_ACTOR` 与 `AOV_RenderSet_ID_Material`，自动激活 `Flush Level/Grass Streaming` 与 `Engine Warm Up Count >= 32`。
* **多镜头输出路径与相机视角 100% 独立隔离**：
  * 每个 MRQ Job 通过 `job.get_configuration().copy_from(preset_asset)` 独立深拷贝预设配置并各自锁定专属的 `output_directory`，彻底解决多镜头共用同一预设导致输出路径互相覆盖的问题。
  * 入列与拆层时自动校验并锁定每个序列的 `Camera Cut` 轨道严格绑定至当前镜头专属的 `CineCameraActor`；入列时仅精准清理当前镜头的旧 Job，100% 保留队列中已添加的其他镜头任务。
* **四级相机路径联动与智能版本策略**：
  * 自动读取 `UECamWorkflowConfig.json` 或背景 `ImgMediaSource` 逆向推导 `.../{ep}/{shot}/ue/publish/vXXX/render` 目录。
  * 支持 **自动递增新版本**（仅当当前版本如 `v001` 已有渲染图时才新建 `v002`，并自动清理未渲染的空版本文件夹）与 **直接替换当前版本**（**不删除已有渲染图片**，直接锁定当前版本目录待渲染时由 UE 覆盖）。
* **每个镜头 Sequence 渲染完成即刻自动弹出对应文件夹**：采用 `on_individual_job_finished_delegate` 与 Slate Tick 镜头文件时间基线双通道实时监听，队列中每渲染完一个镜头即刻自动弹出该镜头的 `render` 文件夹，全部渲染结束时自动兜底补齐弹出所有已渲染镜头的输出目录。

---

### 四、 Foundry Nuke：四大正交预合成与多引擎 AI 抠像管线 (`LiangLiangNukeWorkflow.py`)

在 Nuke 中从左至右构建 **四大零重叠正交模块**，并在左侧工具栏与顶部主菜单同步提供 **`LiangLiangVFX`** 菜单：

```text
 Y=-60 ───────────────────────────────────────────────────────────────────────────────────────────────────
       ┌────────────────────────┐   ┌────────────────────────┐   ┌────────────────────────┐   ┌──────────────────────────┐
       │ 1. 实拍预处理与输出底板  │   │ 2. 【AI 抠像与修补模块】 │   │ 3. UE 预合成主干区      │   │ 4. 分层 AOV 与 Cryptomatte│
       │    (X: -60 ~ 580)      │   │   BiRefNet / MatAnyone2│   │   (单层 / 多层自适应)   │   │    (X: 2060 ~ 2980)      │
       │                        │   │   / SAM2Matting 发丝级 │   │   (X: 1340 ~ 1960)     │   │                          │
       │  Read_Plate   Roto     │   │    (X: 680 ~ 1240)     │   │                        │   │  Actor_ID   Material_ID  │
       │      │         │       │   │                        │   │       Read_UE_BG       │   │     │            │       │
       │  Switch ──► Keyer      │   │            Read_Alpha  │   │           │            │   │  Crypto     4x Shuffles  │
       │      │         │       │   │                │       │   │     Grade / Merges     │   │                          │
       │  Copy_Alpha ◄──┘       │   │            Shuffle     │   │           │            │   │                          │
       │      │                 │   │                │       │   │           ▼            │   │                          │
       │      ├─────────────────┼───┼─► Dot_B     Grade      │   │    Merge_Comp_Over ◄───┼───┘ (前景自动连自 Premult_AI)
       │      ▼                 │   │     │          │       │   │           │            │
       │  Premult_Plate         │   │     │      FilterErode │   │    HorizonWriteNode    │
       │                        │   │     │          │       │   │           │            │
       │                        │   │     ▼        Blur      │   │        Viewer1         │
       │                        │   │  Copy_AI ◄─────┘       │   │                        │
       │                        │   │     │                  │   │                        │
       │                        │   │  Premult_MatAnyone2 ───┼───┼───────────┘            │
       │                        │   │     │                  │   │                        │
       │                        │   │  Write_Final_PNG       │   │                        │
       └────────────────────────┘   └────────────────────────┘   └────────────────────────┘   └──────────────────────────┘
 Y=650+ ──────────────────────────────────────────────────────────────────────────────────────────────────
       [模版由脚本自动生成 v1.0.0] (动态计算所有背板最大底边，统一放置在最下方且绝不重叠)
```

#### Nuke 菜单功能与三大 AI 引擎选型表

| 菜单项名称 | 绑定图标 | 适用场景与核心调参建议 |
| :--- | :---: | :--- |
| **1. 实拍预处理与输出UE底板** | `Keyer.png` | 构建模块 1：实拍读取、LogC/sRGB 色彩切换、Keylight 与 `Write_Final_PNG` 输出 |
| **2. [AI] BiRefNet 全自动高清万物抠像 (2K发丝与道具)** | `RotoPaint.png` | **无须画 Roto 全自动抠像**：支持 `1024`（高速）与 `2048`（原生 2K 极致发丝）切换，连人带随身武器/任意前景一体抠出 |
| **3. [AI] MatAnyone 2 发丝级目标锁定抠像 (CVPR 2026)** | `Tracker.png` | **人像发丝特写主力**：常规人像保持默认（`Warmup=10, Erode/Dilate=10`）；迎风蓬松乱发可将半径调至 `15~25`；细长道具调小至 `3~5` |
| **4. [AI] SAM2Matting 万物发丝级跟踪抠像 (ECCV 2026)** | `Cryptomatte.png` | **复杂动作/遮挡/非人道具主力**：默认采用 `SAM2.1_Base+` 规格；模式 5 下支持画粗略 Roto 圈触发 SAM 2.1 原生框选自动贴边 |
| **5. UE渲染分层自动预合成与ID拆层** | `Shuffle.png` | 构建模块 3 & 4：无缝读取 `LiangLiangUERenderLayer` 渲染输出的单/多层灯光(`plus`)、自发光(`emiss`)与雾效(`screen`)序列，自动构建 World AOV 拆层与 Cryptomatte |
| **6. 重新载入管线脚本** | `Refresh.png` | **一键全量热重载**：免重启 Nuke 即时刷新后端代码与双栏菜单 |

*(注：在 `MatAnyone 2`、`SAM2Matting` 与 `BiRefNet` 面板中选择 **“直接导回已生成的序列”**，可在 0.1 秒内无损切换不同引擎算好的 Alpha 序列并自动重新挂载 `Write_Final_PNG`、`Merge_Comp_Over` 与 `Viewer1`。)*

---

## 👨‍💻 作者与关联项目 (Author & Links)

* **Author**: **LiangLiangArtist** (`LiangLiangVFX`) | Email: `liangliangvfx@gmail.com`
* **GitHub**: [https://github.com/LiangLiangVFX](https://github.com/LiangLiangVFX)
* **YouTube**: [https://www.youtube.com/@zhaol2259](https://www.youtube.com/@zhaol2259)
* **Bilibili**: [https://space.bilibili.com/75504176](https://space.bilibili.com/75504176)
* **Companion AI Backend Suite**: [https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)