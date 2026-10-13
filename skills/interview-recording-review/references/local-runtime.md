# 本地转写与兼容处理

## 准备环境

使用Python 3.10及更高版本。若桌面环境提供运行时发现工具，先读取它返回的Python路径；否则使用已配置的Python。建议在任务工作目录创建虚拟环境，再安装仓库根目录的`requirements.txt`或已安装Skill中的`scripts/requirements.txt`，不要改变宿主工具的全局包。

示例中的路径需要替换成当前用户提供的路径；脚本用参数传递，不依赖机器盘符。

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe skills/interview-recording-review/scripts/recording.py prepare "录屏.mp4" --work-dir "work/本次面试"
.venv\Scripts\python.exe skills/interview-recording-review/scripts/recording.py transcribe --work-dir "work/本次面试" --model small --device cpu
```

Linux/macOS使用`.venv/bin/python`。只需要文字复盘时，无需安装转写依赖。

## 文件与选项

`prepare`输出`metadata.json`、16kHz单声道`audio.flac`，以及可选参考帧。默认每300秒一帧。`--no-frames`关闭截图；`--frame-every 120`改采样间隔。只有音频时不生成截图。准备结果标明截取范围及原录屏偏移。

```powershell
python recording.py prepare "录屏.mp4" --work-dir "work/面试" --start 280 --end 1800 --no-frames
python recording.py transcribe --work-dir "work/面试" --run-id primary --model small --device cpu
```

`transcribe`输出`runs/<run-id>/segments.jsonl`、`transcript.txt`、`transcript.srt`及`run.json`。结果都是机器识别材料，不是已经核对的逐字稿。`run.json`保存运行状态、参数、所选音频指纹和时长。生成中逐段落盘；失败时保留部分结果并返回非零状态。相同输入和设置已经完整处理时直接复用；未完成结果需换`--run-id`或显式`--force`后重跑，不宣称实现了逐段断点续跑。

可疑片段单独处理，开始/结束均填写**原录屏秒数**。下面省略了`recording.py`之前的Skill脚本目录，执行时使用实际路径：

```powershell
python recording.py transcribe --work-dir "work/面试" --run-id verify-framework --model medium --device cpu --start 910 --end 985
```

其他选项：`--batch-size 4`启用批处理；默认0为串行。`--terms "Java,Redis,RRF"`提供少量必要术语；不用候选人姓名、大学、公司或整段参考答案作提示，以免污染轻声片段。`--model-cache`指定已有模型缓存。`--no-vad`仅在确实漏掉轻声语音时尝试，空白片段容易产生幻觉。`--local-files-only`可确保只使用已缓存模型。

批处理快，但不能以更快或更大模型认定内容一定更准确。至少逐片段对照重要问题、数字与轻声发言；若一版遗漏提问，另一版可提供定位线索，最终仍以录音证据为准。

## GPU兼容

默认CPU int8。用户环境已具备GPU运行库时，可使用`--device cuda --compute-type int8_float32`。`--cuda-libs`可重复指定库目录，脚本仅在当前进程加入搜索路径，不修改系统配置。小显存先用串行或较小批量。

当前faster-whisper官方说明：新版CTranslate2使用CUDA 12与cuDNN 9；CUDA 12+cuDNN 8可采用CTranslate2 4.4.0。[官方兼容说明](https://github.com/SYSTRAN/faster-whisper#gpu)

CUDA 12+cuDNN 8的隔离环境示例：

```powershell
python -m pip install "ctranslate2==4.4.0" "setuptools<81"
python recording.py transcribe --work-dir "work/面试" --model medium --device cuda --compute-type int8_float32 --cuda-libs "实际CUDA库目录"
```

4.4.0会用到`pkg_resources`，因此旧兼容方案需要对应版本的setuptools。运行库仍不匹配时，改用CPU或按官方说明配置；不自动在系统范围反复安装GPU包。

## 本次流程验证暴露的兼容点

- PyAV 19与faster-whisper 1.2.1组合中，音频解码可能报`metadata_errors`参数不支持；基线固定`av==16.0.1`。
- 新版转写信息与Segment是dataclass，不能假设有`_asdict()`。脚本兼容dataclass、映射和具备该方法的对象。
- 相同术语重复、模型输出长于源文件、提示词直接出现在背景噪声中，都可能是识别幻觉。脚本截断越界时间并记录质量信号，人工解释时不能把这些内容当作实际发言。
- `status=complete`、非零退出、文件存在是不同证据。只将生成器已消费完并写入完整运行状态的结果作为成功；异常保留`failed`及诊断。

## 隐私与费用

本地模式下载模型与依赖，音频传给本机模型。若改用云端识别，按用户授权和目标服务要求处理上传及费用。`work/`与`models/`不应进入Skill的公开包；截图常含会议口令和邮箱，应作为本地参考帧审查，而非默认示例图片。
