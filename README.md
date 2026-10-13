# interview-recording-review

把面试录屏、音频或已有转写整理成带原录屏时间索引的问答，再依据实际回答复盘技术、项目理解和表达。

这是供Codex等支持`SKILL.md`的助手复用的中文Skill，附本地媒体准备与语音转写脚本。脚本生成核对材料，问答归并、事实核对和面试复盘由助手按证据完成。

## 安装与使用

复制给Codex即可安装：

```text
安装这个Skill：https://github.com/wind127/interview-recording-review/tree/main/skills/interview-recording-review
```

把仓库中的`skills/interview-recording-review`完整目录复制到你的Skill目录。Codex的通常位置为`~/.codex/skills/`；用户自定义位置时以其配置为准。

调用示例：

```text
$interview-recording-review 整理这份面试录屏：/path/to/interview.mp4，保留时间索引并复盘。
```

也可以直接要求“整理并复盘这份面试录像”，由助手按Skill描述选择。

如果只提供已有转写，可以直接复盘，不需要下载模型。音视频转写使用Python 3.10及更高版本，建议创建隔离环境：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe skills/interview-recording-review/scripts/recording.py prepare "interview.mp4" --work-dir "interview/work"
.venv\Scripts\python.exe skills/interview-recording-review/scripts/recording.py transcribe --work-dir "interview/work" --model small --device cpu
```

安装后的Skill仍自带`scripts/requirements.txt`，可直接用其绝对路径安装依赖。Linux/macOS将Python入口改为`.venv/bin/python`。

## 你会得到什么

- 面试时间线与按追问链归并的真实问答。
- 当时回答摘要、支持证据、理解缺口和未覆盖能力。
- 按优先级排列的改进答法、需补事实和复练题。
- 工具可用时增加一页HTML概览；Markdown报告可独立使用。

本地脚本输出`metadata.json`、音频、参考帧，以及分次运行的JSONL/TXT/SRT和运行状态。裁片转写仍使用原录屏时间；已完成的同配置结果可复用，失败结果保留，不把部分识别宣称为完整成功。

默认在录屏旁创建同名文件夹（去掉扩展名）：报告和概览放在根目录，核对材料放在`work/`。例如`面试录屏/某次面试.mp4`的结果保存到`面试录屏/某次面试/`；用户指定位置时以其要求为准。

## 设计边界

- 自动转写可能漏词、误识别或产生幻觉；重要数字、术语与轻声片段需要复核。
- 没有说话人自动识别；角色由实际语义与录音证据确认。
- 当时回答、项目材料、技术补充与建议答法分开记录。
- 不给未经校准的精确总分或通过概率，未覆盖不等于不掌握。
- Skill发布包只包含通用流程与合成示例，真实录屏和个人复盘是任务资料。

GPU、低显存、依赖兼容和重点裁片示例见[本地运行说明](skills/interview-recording-review/references/local-runtime.md)。CPU是默认路径；需要GPU时按环境显式启用。[faster-whisper官方运行要求](https://github.com/SYSTRAN/faster-whisper#requirements)

## 目录

```text
skills/interview-recording-review/
  SKILL.md
  agents/openai.yaml
  scripts/recording.py
  scripts/requirements.txt
  references/local-runtime.md
  references/review.md
  references/report-template.md
examples/synthetic-review.md
tests/test_recording.py
```

示例为[合成面试复盘](examples/synthetic-review.md)，不包含真实候选人的资料。

## 验证

```powershell
python -m unittest discover -s tests -v
```

测试涵盖裁片原时间偏移、越界时间、重复/低置信信号、生成中失败的部分结果保留、完成结果复用及变动音频拒绝。另应在本地用可访问的短音视频做`prepare → transcribe`冒烟检查；转写可读并不证明逐字准确。

采用[MIT许可证](LICENSE)。
