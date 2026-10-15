<div align="center">

# 🎬 VFX_Pipeline_CamSync

**面向 Maya、Unreal Engine 5.4 与 Foundry Nuke 的全流程影视特效自动化管线套件**  
*End-to-End Automated VFX Camera Sync, UE5 Shot Assembly, AI Video Matting & Nuke Auto-Comp Pipeline*

[![Maya](https://img.shields.io/badge/DCC-Autodesk%20Maya-37a5cc.svg)](#)
[![UE5](https://img.shields.io/badge/Engine-Unreal%20Engine%205.4-0e1128.svg)](#)
[![Nuke](https://img.shields.io/badge/DCC-Foundry%20Nuke-f5a623.svg)](#)
[![AI Matting](https://img.shields.io/badge/AI%20Backend-MatAnyone%202%20%7C%20RVM-success.svg)](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)
[![Python](https://img.shields.io/badge/Python-2.7%20%7C%203.x-yellow.svg)](#)
[![YouTube](https://img.shields.io/badge/YouTube-@zhaol2259-ff0000.svg)](https://www.youtube.com/@zhaol2259)

</div>

---

## 📖 项目概述 (Overview)

**`VFX_Pipeline_CamSync`** 是一套专为现代影视视效（VFX）与虚幻引擎（Unreal Engine 5）制片流程研发的**跨软件（Maya $\leftrightarrow$ Nuke $\leftrightarrow$ UE 5.4）全链路自动化工具集**（仓库内附带完整测试示例）。

在传统影视制作中，跟踪相机从 Maya 导入 UE 常面临**比例不一致、离世界原点过远导致精度抖动、起始帧号（1001 vs 0001）错位、变焦/定焦属性丢失、背景板对位繁琐以及后期 Nuke 多层合成连线耗时**等痛点。本管线通过统一的目录与命名规范，将四大核心生产环节彻底打通：

1. **Maya 端 (`Maya -> UE 镜头交付工具`)**：一站式完成厘米级人偶比例校对、原地轴心缩放、世界零点重定向、纯净相机烘焙与 `1001 -> 0001` 帧平移导出。
2. **Nuke 前置端 (`实拍预处理 + AI 发丝级抠像`)**：一键构建实拍 LogC/sRGB 预处理网络，并无缝调度配套算力仓 **[AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)**（**MatAnyone 2 + RVM**）生成发丝级透明底板 `bg_{shot}_####.png` 供 UE 对位。
3. **UE 5.4 端 (`镜头资产自动化交付管线`)**：一键解析 FBX 元数据，自动构建定序器（Level Sequence）、`Shot_Root` 绑定、全局共享 `ImagePlate` 实拍背景轨道（精确对齐素材帧长）以及自动开启 **Nanite** 的静态参考简模。
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
│  1. Autodesk Maya    │               │ 2. Foundry Nuke (前)  │                  │ 3. Unreal Engine 5.4 │
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

## 🛠️ 三大核心 DCC 工具深度解析 (Core Toolsets)

### 一、 Autodesk Maya：镜头标准化交付工具 (`LiangLiangCamExporter.py`)

专为 Matchmove（跟踪）与 Layout 环节打造，解决 Maya 与 UE 坐标系、比例及起始帧差异：

* **工程元数据与路径智能嗅探**：
  * 自动从文件名解析集数（保留原始大小写，如 `ep28` / `EP28`）与镜头号（`Shot`），读取当前帧速率（FPS）与帧范围。
  * 向上 6 层目录智能回溯嗅探是否存在 `ue/workarea` 规范目录并设为默认导出路径。
* **场景缩放与比例对准（UE 厘米标准）**：
  * **参考人偶系统**：自动寻址导入专属 `SM_Pose.fbx`（若无则自动生成 178cm 标准比例胶囊人偶），并开启 Reference 不可选显示模式。
  * **轴心吸附原地缩放**：选中跟踪师自带的参考物点击 **“🎯 选跟踪人偶 -> 吸附标准模型并对齐轴心”**，自动计算脚底包围盒最低点并将缩放组（`UE_Interactive_Scale_Pivot_Grp`）轴心与标准人偶精准吸附，支持 `1x`、`100x` 及滑块实时无极缩放，小人原地放大绝不飞走；同时自动将相机远裁剪面（`farClipPlane`）扩展至 `10,000,000` 防止破面。
* **虚幻空间坐标重定向（解决进 UE 离原点过远乱晃）**：
  * **🧭 相机首帧水平归零**：保持相机高度（Y）与相对运动 100% 无损，将第 1 帧相机的水平坐标（X, Z）平移对准世界原点 `(0, 0)`。
  * **📍 选中目标对准零点**：单选场景中的核心交互物（如台阶、地面点），一键将其底部中心对准世界原点 `(0, 0, 0)`。
  * **↩️ 还原原始世界坐标**：随时一键无损撤销归零偏移，恢复原始跟踪绝对坐标。
* **工业级纯净相机烘焙与导出**：
  * 创建全新纯净相机并通过父子约束逐帧烘焙世界空间位移与旋转，**严格执行关键帧白名单（仅保留 `translateX/Y/Z` 与 `rotateX/Y/Z`，强制锁定 `scale=1.0`）**。
  * **动/定焦智能判别 (`is_true_zoom_camera`)**：自动分析 `focalLength` 曲线差值——若为真变焦镜头则完整拷贝并平移变焦曲线；若为定焦镜头则彻底断开冗余关键帧，保留纯净静态焦距数值，并完整继承画幅尺寸（Film Aperture）。
  * **帧号自动平移**：导出的文件名为 `cam{shot}_{plate_start}_{plate_end}.fbx`（如 `cam2180_1001_1021.fbx`），但内部动画关键帧自动平移至 **`1 ~ duration` 帧**，完美对齐 UE 定序器 `0001` 起始标准。
  * **参考简模同步导出**：勾选后自动筛除参考人偶，将场景匹配简模或点云一键导出为 `{shot}_model_ref.fbx`。

---

### 二、 Unreal Engine 5.4：镜头资产全自动装配管线 (`LiangLiangUECamWorkflow.py`)

配合 Editor Utility Widget (UMG) 界面，在 UE 5.4 中实现“选好 FBX 一键生成完整可渲染镜头”：

* **工程 Shot 目录智能嗅探与记忆**：
  * 启动时自动递归扫描工程 `Content` 目录，精准定位既有规范目录（如 `/Game/EG1/Shot`），并将用户配置持久化保存至 `Saved/UECamWorkflowConfig.json`。
* **定序器 (Level Sequence) 与时间轴闭区间锁定**：
  * 自动从 `cam2180_1001_1021.fbx` 解析集数、镜头号、实拍帧长（`raw_shot_len = 21`）与交付总长（`duration = 22`，自动多留 1 帧把手）。
  * 自动在 `/Game/.../{EP}/Shot_{shot}` 下创建 `{ep}_cam{shot}` 定序器，导入相机 FBX 并将播放区间、视图区间、工作区间及 `Camera Cuts` 轨道严格铺满 `0001 ~ duration`。
* **相机专业属性修正与 `Shot_Root` 绑定**：
  * **焦点修正**：自动将 `CineCameraComponent` 的对焦模式设为 **`Do Not Override`**，杜绝导入后因默认自动对焦导致的画面虚焦。
  * **焦距轨道守护**：自动检测并補齐 `CurrentFocalLength` 浮点轨道与首尾关键帧。
  * **大纲收纳与總控绑定**：自动生成可移动总控空物体 `Shot_Root_{shot}`，通过 `MovieScene3DAttachTrack` 将相机锁死在总控节点上，并将所有镜头相关 Actor 统一收纳至世界大纲的 **`/!Cam`** 文件夹下。
* **全局共享媒体套组与 `ImagePlate` 实拍背景对位**：
  * 自动在 `Media/` 目录下创建或复用全局唯一的 `Global_MediaPlayer`、`Global_MediaTexture` 与双面无光照半透明材质 **`M_Global_MediaPlate`**（自动连接 RGB 至自发光、Alpha 至不透明度并编译）。
  * 自动在相机正前方 `400.0` 厘米处生成原生 **`ImagePlate_{shot}`** 并赋予对位材质。
  * **背景序列自动嗅探与真实帧长对齐**：自动向上 3 层目录嗅探包含 `plate`, `bg`, `source`, `render` 等关键词的序列帧文件夹，创建镜头专属 `ImgMediaSource`（`{ep}_cam{shot}_bg`），并在定序器中构建 `Media Track`，轨道长度严格对齐文件夹内实际图片张数。
* **参考简模强制 Static Mesh + Nanite 自动化导入**：
  * 自动扫描同目录下的非相机 `.fbx` 简模文件，命名为 `SM_Ref_{shot}`。
  * **彻底告别误识别为骨骼网格体**：底层强制配置 `FBXIT_STATIC_MESH`、`import_as_skeletal = False`、`combine_meshes = True`（合并碎模型），并**自动开启 `Build Nanite`（`nanite_settings.enabled = True`）**，导入后自动生成 Actor 挂入 `/!Cam` 与定序器中。

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

1. **模块 1：实拍预处理与输出 UE 底板 (`X: -60 ~ 580`)**
   * 自动识别序列帧或视频素材，内置 `ColorMode_Switch` 一键切换 **`标准普通素材 (sRGB / 直通)`** 与 **`电影机灰片 (LogC -> Linear 转正)`**（自动联动 `Read_Plate` 的 `raw` 属性）。
   * 预置 `Holdout_Roto_KEEP`、`Garbage_Roto_REMOVE` 与 `Keyer_Alpha`，输出 `Write_Final_PNG`（`workarea/bg/bg_{shot}_####.png`），渲染完毕自动弹窗打开文件夹。
2. **模块 2：MatAnyone 2 (CVPR 2026) & RVM 发丝级 AI 抠像模块 (`X: 680 ~ 1240`)**
   * 通过 `LL_AI_SUITE_ROOT` 环境变量或同级目录自动桥接 **[AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)**，弹出独立实时进度终端。
   * 支持 **5 种首帧 Roto 布尔引导模式**（`1_全自动只抠人`、`2_只保留Roto圈内的人`、`3_从人身上挖掉Roto区域`、`4_人加上Roto模块区域`、`5_完全按Roto区域抠像`）及 **中途故障帧局部补救 (`--start_at`)**。
   * 算完自动构建 `Read -> Shuffle -> Grade(提亮发丝) -> FilterErode(扩缩边) -> Blur(柔化) -> Copy -> Premult` 节点网，B 端正交承接左侧 `Copy_Alpha`，并自动将 `Write_Final_PNG` 与右侧 `Merge_Comp_Over` 前景端挂载至 `Premult_MatAnyone2`。
3. **模块 3：UE 渲染分层自动预合成主干区 (`X: 1340 ~ 1960`)**
   * 自动检索 `ue/publish/vXXX/render` 最新版本 EXR 序列，自动执行 `TimeOffset (+1000帧)` 对齐实拍帧号。
   * **单/多层自适应**：多层模式下按 `sky -> env -> key -> fill -> emi -> fog` 优先级自动排序，灯光层通过 `Grade + Merge(plus)` 链式叠加，雾效层自动构建 `Luminance Keyer + Grade + Merge(screen)`，最终汇入 `Merge_Comp_Over -> HorizonWriteNode -> Viewer1`。
4. **模块 4：分层 AOV 与 Cryptomatte 提取网 (`X: 2060 ~ 2980`)**
   * 自动识别 `Actor_ID` 与 `Material_ID` 序列，以 160px 标准间距拆出 `WorldDepth`、`WorldNormal`、`WorldPos` 三个 `Shuffle` 节点及双路 `Cryptomatte` 节点。

---

## 📂 仓库目录结构与示例说明 (Repository Structure & Examples)

```text
VFX_Pipeline_CamSync/
├── Maya/                                    # Autodesk Maya 镜头标准化交付工具
│   ├── LiangLiangCamExporter.py             # Maya -> UE 相机烘焙、比例对准与重定向核心脚本
│   └── SM_Pose.fbx                          # UE 标准厘米比例参考人偶模型
│
├── UE/                                      # Unreal Engine 5.4 镜头全自动装配管线
│   ├── LiangLiangUECamWorkflow.py           # UE 定序器、Media背景板、Nanite简模自动化组装脚本
│   └── Widgets/                             # 配套 Editor Utility Widget (UMG) 蓝图资产
│
├── Nuke/                                    # Foundry Nuke 预合成与 AI 抠像前端插件
│   └── NukeWorkflowTool/
│       ├── icons/                           # 自定义品牌图标库 (icon.png 等)
│       ├── init.py                          # Nuke 插件路径初始化
│       ├── menu.py                          # 左侧工具栏 + 顶部菜单栏双映射 & 一键热重载
│       ├── LiangLiangNukeWorkflow.py        # 四大合成模块与 AI 双引擎调度核心代码
│       └── 一键安装(双击运行).bat             # 自动部署脚本至当前用户 ~/.nuke 目录
│
└── Examples/                                # ★ 标准镜头工程目录结构与测试示例资产
    └── ep28_2180_demo/                      # 示例镜头 (含测试相机 FBX、参考简模、序列帧与 Nuke 模板)
```

---

## 🚀 快速安装与使用指南 (Installation & Usage)

### 1. Maya 端安装与使用
1. 将 `Maya/LiangLiangCamExporter.py` 与 `SM_Pose.fbx` 放入 Maya 用户脚本目录（如 `Documents/maya/scripts/`）。
2. 在 Maya Script Editor (Python 标签页) 中运行以下代码（可拖入工具架 Shelf 作为快捷按钮）：
   ```python
   import importlib
   import LiangLiangCamExporter
   importlib.reload(LiangLiangCamExporter)
   LiangLiangCamExporter.main()
   ```

### 2. Unreal Engine 5.4 端配置与使用
1. 确保 UE 5.4 工程已启用以下官方内置插件：
   * `Python Editor Script Plugin`
   * `Sequencer Scripting`
   * `Editor Scripting Utilities`
   * `Image Plate`
   * `Media Framework Utilities`
2. 将 `LiangLiangUECamWorkflow.py` 放入 UE 工程的 `Content/Python/` 目录（或配置到 Project Settings -> Python -> Additional Paths）。
3. 运行配套的 Editor Utility Widget，选择 Maya 导出的 `camXXXX_1001_1021.fbx` 并点击执行，即可一键完成定序器、背景板与 Nanite 简模组装。

### 3. Nuke 端安装与 AI 算力库关联
1. 进入 `Nuke/NukeWorkflowTool/` 目录，双击运行 **`一键安装(双击运行).bat`**，自动完成 Nuke 菜单与图标部署。
2. **启用 AI 发丝级抠像（可选但强烈推荐）**：
   * 克隆配套后端算力仓库 **[AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)**，解压其 Releases 中的 `python_embeded` 与模型权重包，并双击 `一键注册AI引擎环境(双击运行).bat` 即可与本管线自动连通。

---

## 👨‍💻 作者与联系方式 (Author & Links)

* **Author**: **LiangLiangArtist** (`LiangLiangVFX`)
* **Email**: `liangliangvfx@gmail.com`
* **GitHub**: [https://github.com/LiangLiangVFX](https://github.com/LiangLiangVFX)
* **YouTube**: [https://www.youtube.com/@zhaol2259](https://www.youtube.com/@zhaol2259)
* **Companion AI Suite**: [https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)