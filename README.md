# 自动化备课工作流

把网课视频、PPT 等原始素材加工成可直接用于备课和授课的产物。整个工程按**阶段（stage）**组织：每个阶段独立处理一种输入/输出转换，共享同一套视频读取、几何换算、项目文件和界面组件。

当前已实现 **视频转 PPT**；**视频转讲义**、**PPT 转讲义**已作为规划中的阶段注册，后续可以单独开发、单独测试、单独启动。

## 工作流总览

```
网课视频 ──► 视频转 PPT（已实现） ──► PNG / PPTX / JSON 清单
    │
    └─────► 视频转讲义（规划中） ──► 讲义草稿

PPT / PPTX ─► PPT 转讲义（规划中） ──► 讲义草稿
```

| 阶段 | 阶段 ID | 输入 | 输出 | 状态 | 文档 |
| --- | --- | --- | --- | --- | --- |
| 视频转 PPT | `video_to_slides` | 网课视频 | PNG、PPTX、JSON 清单、`.lsp.json` 项目 | 已实现 | [详细说明](docs/stages/video_to_slides.md) |
| 视频转讲义 | `video_to_handout` | 网课视频 | 讲义草稿（Markdown / Word / PDF，待定） | 规划中 | [阶段说明](docs/stages/video_to_handout.md) |
| PPT 转讲义 | `ppt_to_handout` | PPT / PPTX | 讲义草稿（Markdown / Word / PDF，待定） | 规划中 | [阶段说明](docs/stages/ppt_to_handout.md) |

查看当前注册的所有阶段：

```powershell
python run.py --list-stages
```

## 快速开始

### 1. 环境要求

- Python 3.10+（本项目在 Python 3.13 上验证）
- FFmpeg 和 FFprobe 建议安装在系统 PATH 中
  - Windows 可用 `winget install Gyan.FFmpeg`，或从 ffmpeg.org 下载后把 `bin` 目录加入 PATH。
  - 未安装 FFmpeg 时，视频粗扫描会自动回退到较慢的 OpenCV 逐帧扫描。

### 2. 安装依赖

```powershell
cd "C:\Users\lpc\Desktop\Work\Automated Lesson Preparation Workflow"
python -m pip install -r requirements.txt
```

已验证的主要依赖：

- PySide6 6.12.0
- opencv-python 5.0.0.93
- numpy 2.5.4
- scenedetect 0.7.3
- python-pptx 1.0.2
- Pillow 13.0.0
- pytest 9.2.0
- FFmpeg / FFprobe（系统安装）

### 3. 启动

默认启动已实现的“视频转 PPT”阶段：

```powershell
python run.py
# 或
python -m lesson_prep
```

显式指定阶段：

```powershell
python run.py --stage video_to_slides
```

启动后直接打开视频或项目文件：

```powershell
python run.py "D:\videos\lesson.mp4"
python run.py "D:\videos\lesson.lsp.json"
```

打开文件时，启动器会按文件后缀自动选择阶段；目前只有 `video_to_slides` 可用。

### 4. 视频转 PPT 使用流程

1. 导入视频，等待元数据探测完成；预览区可播放、暂停、拖动时间轴、前后 5 秒。
2. 设置正片开始/结束时间，可手动输入或点“取当前”。
3. 框选 PPT 区域；已有区域可直接拖动边框和四角/边中点控制点微调。
4. 如画面中有老师摄像头，设置摄像头数量（0–6），逐个框选并为每个区域选择忽略、裁剪、黑色遮罩或白色遮罩。
5. 调整分析参数（可选），点“开始分析”。
6. 在“候选页面复核”中查看大图、切换备选帧、删除/恢复、排序、保留/跳过、写备注。
7. 点“导出幻灯片…”生成 PNG、PPTX 和 JSON 清单。
8. 项目会保存为 `.lsp.json` + 同名 `_assets` 文件夹，两者需要一起移动。

完整的界面说明、检测原理、导出结构和已知限制见 [视频转 PPT 阶段文档](docs/stages/video_to_slides.md)。

## 项目结构

```
.
├─ run.py                        # 命令行入口（默认启动视频转 PPT）
├─ requirements.txt
├─ README.md
├─ docs/
│  ├─ architecture.md            # 分层、阶段契约、如何新增阶段
│  └─ stages/
│     ├─ video_to_slides.md      # 已实现阶段的完整说明
│     ├─ video_to_handout.md     # 视频转讲义（规划）
│     └─ ppt_to_handout.md       # PPT 转讲义（规划）
├─ lesson_prep/
│  ├─ app.py                     # QApplication 启动、阶段选择、打开文件
│  ├─ version.py                 # 应用名、阶段名、项目格式版本
│  ├─ core/                      # 所有阶段共享的能力
│  │  ├─ stage.py                # Stage / StageInfo 契约
│  │  ├─ geometry.py             # 归一化矩形、裁剪、缩放适配
│  │  ├─ timecode.py             # 时间码解析/格式化
│  │  ├─ media/                  # 视频探测、逐帧读取、FFmpeg 采样、图片 I/O
│  │  ├─ project/                # 项目文件命名、资源目录、相对路径解析
│  │  └─ ui/                     # 主题、播放器、预览画布、大图对话框、图标
│  ├─ stages/
│  │  ├─ __init__.py             # 阶段注册表
│  │  ├─ video_to_slides/        # 已实现：视频转 PPT
│  │  │  ├─ models.py            # 页面候选、摄像头、分析参数、项目数据
│  │  │  ├─ imaging.py           # 摄像头裁剪/遮罩
│  │  │  ├─ project.py           # .lsp.json 读写
│  │  │  ├─ analysis/            # 两级检测与稳定帧提取
│  │  │  ├─ export/              # PNG / PPTX / JSON 导出
│  │  │  └─ ui/                  # 主窗口、复核面板、设置/导出/回收站对话框
│  │  ├─ video_to_handout/       # 规划中：阶段描述已注册
│  │  └─ ppt_to_handout/         # 规划中：阶段描述已注册
│  └─ __main__.py
├─ scripts/generate_demo_video.py
├─ tests/
└─ test_artifacts/demo_lecture.mp4
```

各层依赖方向：

```
app.py ──► stages ──► core
```

只允许 `stage` 依赖 `core`，`core` 不反向依赖任何阶段。

- `core` 不包含任何具体备课阶段的业务模型，例如页面候选、摄像头区域、讲义模板等。
- 每个阶段可以拥有自己的数据模型、项目文件格式、分析/导出算法和窗口。
- 阶段之间不直接互相导入；需要复用的内容应下沉到 `core`。

更完整的架构说明和阶段契约见 [docs/architecture.md](docs/architecture.md)。

## 新增阶段

以新增 `my_stage` 为例：

1. 创建 `lesson_prep/stages/my_stage/`，在 `__init__.py` 中导出 `STAGE`：

```python
from ...core.stage import Stage, StageInfo

def _create_window():
    from .ui.main_window import MainWindow
    return MainWindow()

STAGE = Stage(
    info=StageInfo(
        id="my_stage",
        name="我的备课阶段",
        summary="一句话说明这个阶段做什么。",
        inputs="输入文件类型",
        outputs="输出文件类型",
        status="available",
        order=40,
    ),
    create_window=_create_window,
    file_suffixes=(".pptx",),
)
```

2. 在 `lesson_prep/stages/__init__.py` 中导入并加入 `STAGES`。
3. 阶段自己的模型、算法和界面放在该阶段目录内；通用视频读取、几何换算、项目路径和共享控件优先复用 `core`。
4. 补充 `docs/stages/my_stage.md` 和测试。
5. 运行 `python run.py --list-stages` 和 `python run.py --stage my_stage` 验证注册与启动。

规划中的阶段也可以在 `status="planned"` 下先注册，不需要实现窗口。

## 测试

```powershell
python -m pytest -q
```

最近一次完整测试结果：**49 passed**（约 12 秒，Python 3.13 / Windows，Qt 离屏后端）。

测试覆盖共享几何与时间码、视频探测/读取、两级页面检测、导出、项目保存与回收站、阶段注册与文件后缀选择，以及真实 Qt 界面上的导入/框选/分析/复核/导出流程。测试细节见 [视频转 PPT 阶段文档](docs/stages/video_to_slides.md#测试)。

## 已知限制

- “视频转讲义”和“PPT 转讲义”目前只有阶段定义，尚未实现。
- 各阶段目前各自使用独立项目文件（视频转 PPT 为 `.lsp.json`）；尚未提供跨阶段串联的“一个备课项目包含多个阶段产物”的统一项目格式。
- 视频转 PPT 的真实素材、长视频性能和动画细节限制，见 [阶段文档的已知限制](docs/stages/video_to_slides.md#已知限制)。


