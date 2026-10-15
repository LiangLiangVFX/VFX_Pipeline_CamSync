<div align="center">

# 🎬 VFX_Pipeline_CamSync

**面向 Maya、Unreal Engine 5.4 与 Foundry Nuke 的全流程影视特效自动化管线套件**  
*End-to-End Automated VFX Camera Sync, UE5 Plugin Shot Assembly, AI Video Matting & Nuke Auto-Comp Pipeline*

[![Maya](https://img.shields.io/badge/Maya-Drag%20%26%20Drop%20Installer-37a5cc.svg)](#)
[![UE5](https://img.shields.io/badge/UE%205.4-Standalone%20Plugin-0e1128.svg)](#)
[![Nuke](https://img.shields.io/badge/Nuke-One--Click%20Deploy-f5a623.svg)](#)
[![AI Matting](https://img.shields.io/badge/AI%20Backend-MatAnyone%202%20%7C%20RVM-success.svg)](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)
[![Python](https://img.shields.io/badge/Python-2.7%20%7C%203.x-yellow.svg)](#)
[![YouTube](https://img.shields.io/badge/YouTube-@zhaol2259-ff0000.svg)](https://www.youtube.com/@zhaol2259)

</div>

---

## 📖 项目概述 (Overview)

**`VFX_Pipeline_CamSync`** 是一套专为现代影视视效（VFX）与虚幻引擎（Unreal Engine 5）制片流程研发的**跨软件（Maya $\leftrightarrow$ Nuke $\leftrightarrow$ UE 5.4）全链路自动化管线工具集**（仓库内附带完整测试示例工程）。

针对传统影视制作中跨软件协同配置的繁琐痛点，本套工具在三大 DCC 软件端均实现了**工业级零门槛自动化部署**（Maya 视口拖拽安装、UE5 独立插件包、Nuke 双击一键安装），并通过统一的镜头目录规范将四大核心生产环节彻底打通：

1. **Maya 端 (`LiangLiangCamExporter`)**：拖拽 `.mel` 至视口即可自动生成工具架按钮。一站式完成厘米级人偶比例校对、原地轴心缩放、世界零点重定向、纯净相机烘焙与 `1001 -> 0001` 帧平移导出。
2. **Nuke 前置端 (`实拍预处理 + AI 发丝级抠像`)**：一键构建实拍 LogC/sRGB 预处理网络，无缝调度配套算力仓 **[AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)**（**MatAnyone 2 + RVM**）生成发丝级透明底板 `bg_{shot}_####.png` 供 UE 对位。
3. **UE 5.4 插件端 (`UECamWorkflow Plugin`)**：插件化封装，一键解析 FBX 元数据，自动构建定序器（Level Sequence）、`Shot_Root` 绑定、全局共享 `ImagePlate` 实拍背景轨道（精确对齐素材帧长）以及自动开启 **Nanite** 的静态参考简模。
4. **Nuke 后置端 (`UE 分层自动预合成与 ID 拆层`)**：自动嗅探 UE 最新发布版本，自适应构建单层或多层灯光/雾效相加主干、AI 前景自动汇合（`Merge_Comp_Over`）以及 `WorldDepth / WorldNormal / WorldPos / Cryptomatte` 通道拆解网。

---

## 🔄 全流程数据流向图 (End-to-End Pipeline Architecture)

```text
  ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                           [标准镜头工作区规范] .../{ep}/{shot}/ue/                                │
  └───────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                  │
        ┌─────────────────────────────────────────┼─────────────────────────────────────────┐
        ▼                                         ▼                                         ▼
┌──────────────────────┐               ┌──────────────────────┐                  ┌──────────────────────┐
│  1. Autodesk Maya    │               │ 2. Foundry Nuke (前)  │                  │ 3. UE 5.4 (插件端)    │
│ ──────────────────── │               │ ──────────────────── │                  │ ──────────────────── │
│ • 吸附人偶 & 100x缩放 │               │ • 实拍 LogC/sRGB 转换 │                  │ • 自动建 LevelSequence│
│ • 首帧/目标对准世界零点│  cam2180.fbx  │ • MatAnyone 2 发丝抠像│  bg_2180.png     │ • 挂载 ImagePlate 对位│
│ • 动/定焦判别与纯烘焙 ├──────────────►│ • 输出透明预乘前景底板 ├─────────────────►│ • 简模转 Static+Nanite│
│ • 1001帧自动平移至 1 帧│  model_ref.fbx│   (workarea/bg/)     │                  │ • 渲染输出 EXR 与 ID 层│
└──────────────────────┘               └──────────┬───────────┘                  └──────────┬───────────┘
                                                  │                                         │
                                                  │           ┌─────────────────────────────┘
                                                  ▼           ▼ (ue/publish/vXXX/render/*.exr)
                                       ┌──────────────────────────────────────┐
                                       │         4. Foundry Nuke (后)          │
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
无需手动拷贝脚本或配置路径，采用工业级拖拽部署机制：
1. 打开 Autodesk Maya，在文件资源管理器中定位到本仓库的 Maya 工具目录。
2. 用鼠标左键按住 **`dragDropInstaller.mel`**，直接**拖拽并释放到 Maya 3D 视口（Viewport）中**。
3. 安装脚本将在后台自动完成以下操作并弹出成功提示：
   * 自动将核心代码 `LiangLiangCamExporter.py` 与标准参考人偶 `SM_Pose.fbx` 部署至 Maya 用户脚本目录（`userScriptDir`）；
   * 自动将专属图标 `icon.png` 部署至 Maya 用户图标目录（`userPrefDir/icons/`）；
   * 自动在 Maya 顶部工具架（Shelf）创建 **`[LiangLiangArtist]`** 专属标签页，并生成带热重载功能的 **`UE_Cam`** 启动图标，点击即可打开交付面板。

### 2. Unreal Engine 5.4 端：独立插件化部署 (`Plugin`)
UE 端已完整打包为标准虚幻引擎插件（内含 Python 自动化核心 `LiangLiangUECamWorkflow.py` 与 Editor Utility Widget 交互界面）：
1. 将仓库中的 UE 插件文件夹直接复制到你的 UE 5.4 工程根目录下的 **`Plugins/`** 文件夹中（若工程无 `Plugins` 文件夹则新建一个）。
2. 启动 UE 5.4 工程（确保工程已启用官方内置的 `Python Editor Script Plugin`、`Sequencer Scripting`、`Image Plate` 插件）。
3. 在编辑器中启动插件自带的镜头组装工具面板，选择 Maya 导出的相机 `.fbx` 即可一键组装。

### 3. Nuke 端：双击一键安装 (`一键安装(双击运行).bat`)
1. 进入仓库的 `Nuke/NukeWorkflowTool/` 目录，直接双击运行 **`一键安装(双击运行).bat`**，自动将脚本、双栏菜单与图标部署至 `~/.nuke`。
2. **关联 AI 算力后端（可选但推荐）**：克隆配套仓库 **[AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)**，解压其 Releases 环境包后双击 `一键注册AI引擎环境(双击运行).bat`，Nuke 即可通过 `LL_AI_SUITE_ROOT` 环境变量或同级目录自动桥接 **MatAnyone 2** 与 **RVM** 引擎。

---

## 🛠️ 三大核心 DCC 工具深度解析 (Core Toolsets)

### 一、 Autodesk Maya：镜头标准化交付工具 (`LiangLiangCamExporter.py`)

专为 Matchmove（跟踪）与 Layout 环节打造，彻底解决 Maya 与 UE 坐标系、比例及起始帧差异：

* **工程元数据与路径智能嗅探**：
  * 自动从文件名解析集数（原样保留大小写，如 `ep28` / `EP28`）与镜头号（`Shot`），读取当前帧速率（FPS）与帧范围。
  * 向上 6 层目录智能回溯嗅探是否存在 `ue/workarea` 规范目录并自动设为默认导出路径。
* **场景缩放与比例对准（UE 厘米标准）**：
  * **参考人偶系统**：自动加载 `SM_Pose.fbx` 标准比例人偶（若缺失则动态生成几何体参考人偶），并设为 Reference 防误选模式。
  * **轴心吸附原地缩放**：选中跟踪师自带的参考物点击 **“🎯 选跟踪人偶 -> 吸附标准模型并对齐轴心”**，自动计算脚底包围盒最低点并将缩放组（`UE_Interactive_Scale_Pivot_Grp`）轴心与标准人偶精准对齐；支持 `1x`、`100x` 及滑块实时无极缩放，原地放大绝不飞走，并自动扩展相机远裁剪面（`farClipPlane = 10,000,000`）防止视口破面。
* **虚幻空间坐标重定向（解决进 UE 离原点过远导致精度抖动）**：
  * **🧭 相机首帧水平归零**：保持相机高度（Y）与相对运动 100% 无损，将第 1 帧相机的水平坐标（X, Z）平移对准世界原点 `(0, 0)`。
  * **📍 选中目标对准零点**：单选场景中的核心交互参照物（如地面点、台阶），一键将其底部中心对准世界原点 `(0, 0, 0)`。
  * **↩️ 还原原始世界坐标**：随时一键无损撤销归零偏移，100% 恢复原始跟踪世界坐标。
* **工业级纯净相机烘焙与导出**：
  * 自动创建新相机并通过父子约束逐帧烘焙世界空间变换，**严格执行关键帧白名单（仅保留 `translateX/Y/Z` 与 `rotateX/Y/Z`，强制锁定 `scale=1.0`）**。
  * **动/定焦智能判别 (`is_true_zoom_camera`)**：自动计算 `focalLength` 曲线差值——真变焦镜头自动拷贝并平移变焦曲线；定焦镜头彻底断开冗余关键帧，保留纯净静态焦距数值，并完整继承画幅尺寸（Film Aperture）。
  * **帧号自动平移与简模同步导出**：导出文件命名为 `cam{shot}_{plate_start}_{plate_end}.fbx`（如 `cam2180_1001_1021.fbx`），内部动画自动平移至 **`1 ~ duration` 帧**（对齐 UE `0001` 帧），并支持同步导出排除参考人偶后的 `{shot}_model_ref.fbx` 匹配简模。

---

### 二、 Unreal Engine 5.4：镜头资产全自动装配插件 (`LiangLiangUECamWorkflow.py`)

* **工程规范目录递归嗅探**：
  * 自动扫描工程 `Content` 目录，精准定位既有规范路径（如 `/Game/EG1/Shot`），并将配置持久化保存至 `Saved/UECamWorkflowConfig.json`。
* **定序器 (Level Sequence) 闭区间锁定与相机修正**：
  * 自动从 FBX 文件名提取集数、镜头号、实拍帧长（`raw_shot_len`）与交付总长（`duration = raw_shot_len + 1`，预留 1 帧把手），将定序器与 `Camera Cuts` 轨道严格铺满 `0001 ~ duration`。
  * 自动将相机对焦模式设为 **`Do Not Override`** 防止画面虚焦，自动补齐 `CurrentFocalLength` 焦距轨道，生成 `Shot_Root_{shot}` 总控节点并通过 `Attach` 轨道锁死相机，所有 Actor 统一归类至世界大纲 **`/!Cam`** 文件夹。
* **全局共享媒体套组与 `ImagePlate` 实拍背景对位**：
  * 自动创建或复用 `Global_MediaPlayer`、`Global_MediaTexture` 与双面无光照半透明材质 **`M_Global_MediaPlate`**（自动连接 RGB 至自发光、Alpha 至不透明度）。
  * 自动在相机前方 `400.0` 厘米挂载原生 **`ImagePlate_{shot}`**，向上 3 层目录自动嗅探实拍序列帧文件夹，创建专属 `ImgMediaSource` 并在定序器生成严格对齐实拍张数的 `Media Track`（支持勾选框自主控制是否生成媒体轨道）。
* **参考简模强制 Static Mesh + Nanite 自动化导入**：
  * 自动扫描同目录下的非相机 `.fbx` 简模文件，命名为 `SM_Ref_{shot}`，强制锁定为静态网格体（`FBXIT_STATIC_MESH`、`import_as_skeletal = False`）、开启合并网格（`combine_meshes = True`）并**自动激活 `Build Nanite`**，导入后自动挂载至视口与定序器中。

---

### 三、 Foundry Nuke：四大正交预合成与 AI 抠像管线 (`LiangLiangNukeWorkflow.py`)

在 Nuke 中根据当前工程名自动解析上下文，从左至右构建 **四大零重叠正交模块**，并在左侧工具栏与顶部主菜单同步提供 **`LiangLiangVFX`** 菜单与**一键全量热重载**：

```text
 Y=-60 ───────────────────────────────────────────────────────────────────────────────────────────────────
       ┌────────────────────────┐   ┌────────────────────────┐   ┌────────────────────────┐   ┌──────────────────────────┐
       │ 1. 实拍预处理与输出底板  │   │ 2. 【AI 抠像与修补模块】 │   │ 3. UE 预合成主干区      │   │ 4. 分层 AOV 与 Cryptomatte│
       │    (X: -60 ~ 580)      │   │  MatAnyone 2 (CVPR2026)│   │   (单层 / 多层自适应)   │   │    (X: 2060 ~ 2980)      │
       │                        │   │     发丝级             │   │   (X: 1340 ~ 1960)     │   │                          │
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

* **模块 1：实拍预处理与输出 UE 底板 (`X: -60 ~ 580`)**：支持序列帧与视频格式，内置 `ColorMode_Switch` 一键切换 `标准普通素材 (sRGB)` 与 `电影机灰片 (LogC -> Linear)`，输出 `Write_Final_PNG`（`bg_{shot}_####.png`）并在渲染后自动打开文件夹。
* **模块 2：MatAnyone 2 (CVPR 2026) & RVM 发丝级 AI 抠像 (`X: 680 ~ 1240`)**：弹出实时进度终端，支持 **5 种首帧 Roto 布尔引导模式** 与 **中途故障帧局部补救 (`--start_at`)**，算完自动构建 `Read -> Shuffle -> Grade -> FilterErode -> Blur -> Copy -> Premult` 柔边修饰链，并自动把 `Write_Final_PNG` 与右侧 `Merge_Comp_Over` 前景端连过来。
* **模块 3：UE 渲染分层自动预合成主干区 (`X: 1340 ~ 1960`)**：自动扫描 `ue/publish/vXXX/render` 最新版本 EXR，自动对齐 `+1000` 帧偏移，自适应构建单层或多层灯光（`plus`）与雾效（`Luminance Key + screen`）合成链，末端输出 `HorizonWriteNode` 并自动挂载 `Viewer1`。
* **模块 4：分层 AOV 与 Cryptomatte 提取网 (`X: 2060 ~ 2980`)**：自动识别 `Actor_ID` 与 `Material_ID`，以 160px 标准间距拆出 `WorldDepth`、`WorldNormal`、`WorldPos` 三个 `Shuffle` 节点与双路 `Cryptomatte` 节点。

---

## 📂 仓库目录结构 (Repository Structure)

```text
VFX_Pipeline_CamSync/
├── Maya/                                    # Autodesk Maya 镜头标准化交付工具包
│   ├── dragDropInstaller.mel                # ★ 拖拽至 Maya 视口即可全自动安装并生成工具架按钮
│   ├── LiangLiangCamExporter.py             # Maya -> UE 相机烘焙、比例对准与重定向核心代码
│   ├── SM_Pose.fbx                          # UE 标准厘米比例参考人偶模型
│   └── icon.png                             # Maya 工具架专属图标
│
├── UE/                                      # Unreal Engine 5.4 镜头全自动装配插件包
│   └── UECamWorkflowPlugin/                 # ★ 直接放入 UE 工程 Plugins/ 目录即可使用
│       ├── Content/
│       │   ├── Python/
│       │   │   └── LiangLiangUECamWorkflow.py
│       │   └── Widgets/                     # Editor Utility Widget 交互面板资产
│       └── *.uplugin                        # 插件描述文件
│
├── Nuke/                                    # Foundry Nuke 预合成与 AI 抠像前端插件包
│   └── NukeWorkflowTool/
│       ├── icons/                           # 自定义品牌图标库 (icon.png 等)
│       ├── init.py                          # Nuke 插件路径初始化
│       ├── menu.py                          # 左侧工具栏 + 顶部菜单栏双映射 & 一键热重载
│       ├── LiangLiangNukeWorkflow.py        # 四大合成模块与 AI 双引擎调度核心代码
│       └── 一键安装(双击运行).bat             # ★ 双击自动部署至当前用户 ~/.nuke 目录
│
└── Examples/                                # ★ 标准镜头工程目录结构与测试示例资产
```

---

## 👨‍💻 作者与关联项目 (Author & Links)

* **Author**: **LiangLiangArtist** (`LiangLiangVFX`)
* **Email**: `liangliangvfx@gmail.com`
* **GitHub**: [https://github.com/LiangLiangVFX](https://github.com/LiangLiangVFX)
* **YouTube**: [https://www.youtube.com/@zhaol2259](https://www.youtube.com/@zhaol2259)
* **Companion AI Backend Suite**: [https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)