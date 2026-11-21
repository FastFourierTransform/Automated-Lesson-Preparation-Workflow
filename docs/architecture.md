# 工程架构

## 1. 设计目标

这个工程的目标是承载一整套自动化备课工作流，而不是单一的视频转 PPT 工具。因此代码按“共享核心 + 可插拔阶段”组织：

- **core**：与具体备课产物无关的能力，例如视频探测、逐帧读取、时间码、归一化坐标、项目路径约定、共享 Qt 控件。
- **stages**：每一种输入/输出转换的独立实现。当前已实现 `video_to_slides`，规划 `video_to_handout`、`ppt_to_handout`。
- **app**：只负责启动 Qt、选择阶段、把命令行文件路径转交给阶段窗口，不包含业务逻辑。

这样新增阶段时不需要改动现有阶段的算法或界面；复用能力则下沉到 `core`，避免复制粘贴。

## 2. 分层

```
run.py / python -m lesson_prep
        │
        ▼
lesson_prep/app.py                 启动器：字体、主题、阶段选择、打开文件
        │
        ├──────────────► lesson_prep/core/          共享核心
        │                  ├─ stage.py              Stage / StageInfo 契约
        │                  ├─ geometry.py           Rect、裁剪、缩放适配
        │                  ├─ timecode.py           时间码
        │                  ├─ media/                视频与图片 I/O
        │                  ├─ project/              项目文件命名与资源路径
        │                  └─ ui/                   共享 Qt 组件
        │
        ▼
lesson_prep/stages/
        ├─ video_to_slides/     已实现：视频 → PPT
        ├─ video_to_handout/    规划中：视频 → 讲义
        └─ ppt_to_handout/      规划中：PPT → 讲义
```

依赖规则：

1. `core` 不得导入任何 `stages` 下的模块。
2. 阶段可以导入 `core`，但阶段之间不得互相导入。
3. 只有确实会被两个以上阶段使用的内容才放进 `core`；仅服务于一个阶段的逻辑留在该阶段内。
4. 阶段可以复用其他阶段产出的文件，但应通过数据文件/接口而不是导入对方 UI 或内部函数。

## 3. 阶段契约

契约定义在 `lesson_prep/core/stage.py`。

### StageInfo

| 字段 | 说明 |
| --- | --- |
| `id` | 稳定标识，用于 `--stage`、项目文件和日志，例如 `video_to_slides` |
| `name` | 中文显示名，例如“视频转 PPT” |
| `summary` | 一句话说明 |
| `inputs` | 输入类型说明 |
| `outputs` | 输出类型说明 |
| `status` | `available` 或 `planned` |
| `order` | 在启动器/列表中的排序 |

### Stage

| 字段 | 说明 |
| --- | --- |
| `info` | 上表的阶段元数据 |
| `create_window` | 返回主窗口的工厂函数；规划阶段可为 `None` |
| `open_path(window, path)` | 启动时打开文件的回调；返回值表示是否处理 |
| `file_suffixes` | 该阶段接受的文件后缀，用于按文件类型自动选择阶段 |

一个阶段的最小实现：

```python
# lesson_prep/stages/my_stage/__init__.py
from ...core.stage import Stage, StageInfo

def _create_window():
    from .ui.main_window import MainWindow
    return MainWindow()

def _open_path(window, path):
    window.open_file(path)
    return True

STAGE = Stage(
    info=StageInfo(
        id="my_stage",
        name="我的阶段",
        summary="说明这个阶段做什么。",
        inputs="输入类型",
        outputs="输出类型",
        status="available",
        order=40,
    ),
    create_window=_create_window,
    open_path=_open_path,
    file_suffixes=(".pptx",),
)
```

在 `lesson_prep/stages/__init__.py` 中注册：

```python
from .my_stage import STAGE as MY_STAGE

STAGES = tuple(
    sorted(
        (VIDEO_TO_SLIDES, VIDEO_TO_HANDOUT, PPT_TO_HANDOUT, MY_STAGE),
        key=lambda stage: stage.info.order,
    )
)
```

`create_window` 使用延迟导入（在函数内部导入 UI），避免启动器列出阶段时加载所有 Qt 窗口。

## 4. 阶段选择与启动

`lesson_prep/app.py` 按以下顺序选择阶段：

1. 命令行显式指定 `--stage <id>`。
2. 提供了文件路径时，选择第一个声明匹配后缀的可用阶段。
3. 否则使用 `DEFAULT_STAGE_ID`（当前为 `video_to_slides`）。

规划阶段不能启动，启动器会输出提示并返回非零退出码。`--list-stages` 会列出所有阶段、输入输出和状态。

## 5. 共享核心模块

| 模块 | 职责 |
| --- | --- |
| `core/stage.py` | 阶段契约和注册类型 |
| `core/geometry.py` | 归一化 `Rect`、像素换算、裁剪、相对坐标、无拉伸适配、BGR→QImage |
| `core/timecode.py` | `HH:MM:SS(.mmm)` 解析与格式化 |
| `core/media/models.py` | `VideoInfo` 元数据 |
| `core/media/probe.py` | FFprobe + OpenCV 元数据探测与校验 |
| `core/media/reader.py` | 帧精确读取、顺序窗口采样、资源释放 |
| `core/media/sampler.py` | FFmpeg 管道流式采样 |
| `core/media/utils.py` | Unicode 路径图片读写、缩略图 |
| `core/project/paths.py` | 项目文件名、`_assets` 目录、资源相对路径解析 |
| `core/ui/player.py` | OpenCV 预览播放器 |
| `core/ui/preview_canvas.py` | 视频画面显示、归一化区域框选与拖动调整 |
| `core/ui/image_dialog.py` | 可缩放大图预览 |
| `core/ui/theme.py` | 全局 Qt 样式表 |
| `core/ui/icons.py` | 应用图标 |

### 什么不应该放进 core

- 页面候选、PPT 页面状态、摄像头处理策略等视频转 PPT 专属模型。
- 某个阶段的导出目录结构、PPTX 生成逻辑。
- 某个阶段专用的复核面板、设置对话框和后台 Worker。

这些应留在对应阶段内。如果以后“视频转讲义”也需要摄像头排除逻辑，再把通用部分提取到 `core`，而不是现在提前抽象。

## 6. 项目文件与资源约定

当前每个阶段独立管理自己的项目文件。以视频转 PPT 为例：

```
lesson.lsp.json
lesson_assets/
├─ runs/<timestamp>_<id>/
│  └─ pages/<page_id>/
│     ├─ candidates/   # 原始候选截图
│     └─ thumbs/       # 缩略图
```

约定：

- 项目 JSON 和同名 `_assets` 文件夹必须一起移动。
- 项目内保存的资源路径一律相对于 `_assets` 根目录，并使用 `/` 分隔。
- JSON 顶层包含 `schema_version`、`stage`、`app_version`、`assets_folder`。
- `stage` 用于防止把某个阶段的项目误交给另一个阶段打开。
- 导入旧项目时，缺失 `stage` 视为 `video_to_slides`，保持向后兼容。

未来如果要做跨阶段串联，可以新增统一的 workflow 项目，引用各阶段的独立项目文件；当前不提前引入这层复杂度。

## 7. 界面复用

`core/ui` 只放与业务无关的控件：

- `VideoPlayer`：只负责播放和定位，不关心“页面候选”。
- `PreviewCanvas`：显示画面并输出归一化 `Rect`，不关心区域是 PPT 还是摄像头。
- `ImagePreviewDialog`：显示任意图片。
- `theme` / `icons`：视觉样式。

阶段 UI 负责把业务状态绑定到这些控件。例如视频转 PPT 的 `PreviewCanvas` 同时显示 PPT 区域和多个摄像头区域，但画布本身只理解“标签 + 矩形”。

## 8. 新增阶段检查清单

- [ ] 新建 `lesson_prep/stages/<id>/` 包，导出 `STAGE`。
- [ ] 在 `lesson_prep/stages/__init__.py` 注册。
- [ ] 阶段自己的模型放在该阶段内；通用能力复用 `core`。
- [ ] 如果阶段需要项目文件，使用 `core/project/paths.py` 的命名和资源目录约定，并在 JSON 中写 `stage`。
- [ ] 如果阶段需要打开文件，实现 `open_path` 和 `file_suffixes`。
- [ ] 补充 `docs/stages/<id>.md`。
- [ ] 添加单元测试和至少一条端到端/UI 测试。
- [ ] 运行 `python -m pytest -q`、`python run.py --list-stages`、`python run.py --stage <id>`。

## 9. 规划阶段

| 阶段 | 计划输入 | 计划输出 | 可复用内容 |
| --- | --- | --- | --- |
| `video_to_handout` | 网课视频 | 结构化讲义草稿 | `core/media`、`core/ui`；可选复用视频转 PPT 的页面分割结果 |
| `ppt_to_handout` | PPT / PPTX | 结构化讲义草稿 | `core/project`、`core/ui`；PPTX 解析需要新增依赖或使用 python-pptx |

阶段说明见：

- [视频转讲义](stages/video_to_handout.md)
- [PPT 转讲义](stages/ppt_to_handout.md)
