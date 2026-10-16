<div align="center">

# 🎬 VFX_Pipeline_CamSync

**面向 Maya、Unreal Engine 5.4 与 Foundry Nuke 的全流程影视特效自动化管线套件**  
*End-to-End Automated VFX Camera Sync, UE5 Plugin Shot Assembly, Multi-Engine AI Matting & Nuke Auto-Comp Pipeline*

[![Maya](https://img.shields.io/badge/Maya-Drag%20%26%20Drop%20Installer-37a5cc.svg)](#)
[![UE5](https://img.shields.io/badge/UE%205.4-Standalone%20Plugin-0e1128.svg)](#)
[![Nuke](https://img.shields.io/badge/Nuke-One--Click%20Deploy-f5a623.svg)](#)
[![AI Matting](https://img.shields.io/badge/AI%20Engines-BiRefNet%20%7C%20MatAnyone2%20%7C%20SAM2Matting-success.svg)](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)
[![Python](https://img.shields.io/badge/Python-2.7%20%7C%203.x-yellow.svg)](#)
[![YouTube](https://img.shields.io/badge/YouTube-@zhaol2259-ff0000.svg)](https://www.youtube.com/@zhaol2259)

</div>

---

## 📖 项目概述 (Overview)

**`VFX_Pipeline_CamSync`** 是一套专为现代影视视效（VFX）与虚幻引擎（Unreal Engine 5）制片流程研发的**跨软件（Maya $\leftrightarrow$ Nuke $\leftrightarrow$ UE 5.4）全链路自动化管线工具集**（仓库内附带完整测试示例工程）。

针对传统影视制作中跨软件协同配置的痛点，本套工具在三大 DCC 软件端均实现了**零门槛自动化部署**（Maya 视口拖拽安装、UE5 独立插件包、Nuke 双击一键安装），并通过统一的镜头目录规范将四大核心生产环节彻底打通：

1. **Maya 端 (`LiangLiangCamExporter`)**：拖拽 `dragDropInstaller.mel` 至视口即可自动生成工具架按钮。一站式完成厘米级人偶比例校对、原地轴心缩放、世界零点重定向、纯净相机烘焙与 `1001 -> 0001` 帧平移导出。
2. **Nuke 前置端 (`实拍预处理 + 三大 SOTA AI 抠像引擎`)**：一键构建实拍 LogC/sRGB 预处理网络，无缝调度配套算力仓 **[AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)** 中的 **BiRefNet (2K高清万物)**、**MatAnyone 2 (CVPR 2026)** 与 **SAM2Matting (ECCV 2026)** 生成发丝级透明底板 `bg_{shot}_####.png` 供 UE 对位。
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
│ • 首帧/目标对准世界零点│  cam2180.fbx  │ • BiRefNet/MatAnyone2│  bg_2180.png     │ • 挂载 ImagePlate 对位│
│ • 动/定焦判别与纯烘焙 ├──────────────►│   /SAM2Matting AI抠像├─────────────────►│ • 简模转 Static+Nanite│
│ • 1001帧自动平移至 1 帧│  model_ref.fbx│ • 输出透明预乘前景底板 │                  │ • 渲染输出 EXR 与 ID 层│
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
1. 打开 Autodesk Maya，在资源管理器中按住 **`dragDropInstaller.mel`** 直接**拖拽并释放到 Maya 3D 视口中**。
2. 脚本将自动将 `LiangLiangCamExporter.py` 与 `SM_Pose.fbx` 部署至 `userScriptDir`，将 `icon.png` 部署至 `userPrefDir/icons/`，并在顶部工具架创建 **`[LiangLiangArtist]`** 专属标签页与 **`UE_Cam`** 启动图标。

### 2. Unreal Engine 5.4 端：独立插件化部署 (`Plugin`)
1. 将仓库中的 UE 插件文件夹复制到 UE 5.4 工程根目录下的 **`Plugins/`** 文件夹中。
2. 启动 UE 5.4 工程（确保已开启官方内置的 `Python Editor Script Plugin`、`Sequencer Scripting`、`Image Plate` 插件），打开插件面板选择相机 `.fbx` 即可一键组装。

### 3. Nuke 端：双击一键安装 (`一键安装(双击运行).bat`)
1. 进入 `Nuke/NukeWorkflowTool/` 目录，双击运行 **`一键安装(双击运行).bat`**，自动完成 Nuke 双栏菜单与图标部署。
2. **关联 AI 算力后端**：克隆 **[AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)**，解压其 Releases 环境包后双击 `一键注册AI引擎环境(双击运行).bat`，Nuke 即可自动桥接三大 AI 抠像引擎。

---

## 🛠️ 三大核心 DCC 工具深度解析 (Core Toolsets)

### 一、 Autodesk Maya：镜头标准化交付工具 (`LiangLiangCamExporter.py`)

* **工程元数据与路径嗅探**：自动解析集数（保留原始大小写）与镜头号，向上 6 层目录智能回溯嗅探 `ue/workarea` 规范目录。
* **厘米级比例对准与原地缩放**：一键加载 `SM_Pose.fbx` 标准参考人偶，选中跟踪参考物即可自动吸附脚底中心并对齐缩放组轴心（`UE_Interactive_Scale_Pivot_Grp`），支持 `1x`、`100x` 及滑块无极原地缩放，自动将相机 `farClipPlane` 设为 `10,000,000` 防止视口裁切。
* **虚幻空间坐标重定向**：提供 **🧭 相机首帧水平归零**、**📍 选中目标对准零点** 与 **↩️ 还原原始世界坐标** 三大功能，彻底解决进 UE 后离世界原点过远导致的精度抖动。
* **纯净相机烘焙与动/定焦判别**：逐帧烘焙世界坐标并严格过滤非 `Translate/Rotate` 通道（锁定 `scale=1.0`）；自动判别真变焦与定焦镜头；导出 `cam{shot}_{plate_start}_{plate_end}.fbx` 时自动将内部动画平移至 `1 ~ duration` 帧以对齐 UE `0001` 帧，并支持同步导出 `{shot}_model_ref.fbx` 简模。

---

### 二、 Unreal Engine 5.4：镜头资产全自动装配插件 (`LiangLiangUECamWorkflow.py`)

* **Shot 目录递归嗅探**：自动扫描 `Content` 目录匹配 `/Game/.../Shot` 路径并持久化记忆至 `Saved/UECamWorkflowConfig.json`。
* **定序器闭区间锁定与相机修正**：自动创建 `{ep}_cam{shot}` 定序器，锁定 `0001 ~ duration`（多留 1 帧把手）并铺满 `Camera Cuts`；自动将相机焦点设为 `Do Not Override`、补齐焦距轨道、生成 `Shot_Root_{shot}` 并通过 `Attach` 轨道锁死相机，全部 Actor 统一收纳至世界大纲 **`/!Cam`**。
* **全局共享媒体套组与 `ImagePlate` 对位**：自动构建 `M_Global_MediaPlate` 双面无光照半透明材质并赋予相机前方的 `ImagePlate_{shot}`；向上 3 层目录自动嗅探实拍序列帧，生成长度严格对齐实拍张数的 `Media Track`。
* **参考简模强制 Static Mesh + Nanite 导入**：自动将同目录参考简模以静态网格体合并导入（`import_as_skeletal=False`, `combine_meshes=True`），强制激活 **`Build Nanite`** 并挂入定序器。

---

### 三、 Foundry Nuke：四大正交预合成与多引擎 AI 抠像管线 (`LiangLiangNukeWorkflow.py`)

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
| **5. UE渲染分层自动预合成与ID拆层** | `Shuffle.png` | 构建模块 3 & 4：单/多层 UE 灯光(`plus`)与雾效(`screen`)合成、World AOV 拆层与 Cryptomatte |
| **6. 重新载入管线脚本** | `Refresh.png` | **一键全量热重载**：免重启 Nuke 即时刷新后端代码与双栏菜单 |

*(注：在 `MatAnyone 2`、`SAM2Matting` 与 `BiRefNet` 面板中选择 **“直接导回已生成的序列”**，可在 0.1 秒内无损切换不同引擎算好的 Alpha 序列并自动重新挂载 `Write_Final_PNG`、`Merge_Comp_Over` 与 `Viewer1`。)*

---

## 👨‍💻 作者与关联项目 (Author & Links)

* **Author**: **LiangLiangArtist** (`LiangLiangVFX`) | Email: `liangliangvfx@gmail.com`
* **GitHub**: [https://github.com/LiangLiangVFX](https://github.com/LiangLiangVFX) | **YouTube**: [https://www.youtube.com/@zhaol2259](https://www.youtube.com/@zhaol2259)
* **Companion AI Backend Suite**: [https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite](https://github.com/LiangLiangVFX/AI_VFX_Pipeline_Suite)