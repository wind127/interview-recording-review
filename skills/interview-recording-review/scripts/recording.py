#!/usr/bin/env python3
"""本地准备和转写；只生成核对材料，不自动评价候选人。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path


def mapping(value):
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, '_asdict'):
        return value._asdict()
    raise TypeError(f'Unsupported record type: {type(value).__name__}')


def save_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    temporary.replace(path)


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def timestamp(seconds, srt=False):
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    whole, milliseconds = divmod(milliseconds, 1000)
    base = f'{hours:02d}:{minutes:02d}:{whole:02d}'
    return base + (f',{milliseconds:03d}' if srt else '')


def selection(lower, upper, start=None, end=None):
    start = lower if start is None else start
    end = upper if end is None else end
    if not all(math.isfinite(x) for x in (lower, upper, start, end)):
        raise ValueError('时间必须是有限秒数。')
    if lower < 0 or upper <= lower or start < lower or end > upper or end <= start:
        raise ValueError(f'截取范围需满足 {lower} <= start < end <= {upper}。')
    return start, end


def ffmpeg_executable(explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError('指定的ffmpeg不存在。')
        return str(path)
    found = shutil.which('ffmpeg')
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as error:
        raise RuntimeError('缺少ffmpeg；安装imageio-ffmpeg或通过--ffmpeg指定。') from error


def extract_audio(executable, source, destination, start, duration):
    temporary = destination.with_name(destination.stem + '.partial.flac')
    subprocess.run([executable, '-hide_banner', '-loglevel', 'error', '-y',
                    '-ss', str(start), '-i', str(source), '-t', str(duration),
                    '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'flac', str(temporary)], check=True)
    temporary.replace(destination)


def prepare(args):
    if not args.no_frames and (not math.isfinite(args.frame_every) or args.frame_every <= 0):
        raise ValueError('--frame-every需为大于0的有限秒数。')
    try:
        import av
    except ImportError as error:
        raise RuntimeError('准备媒体需要av；请在隔离环境安装requirements.txt。') from error
    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError('输入媒体不存在。')
    work = Path(args.work_dir).expanduser().resolve()
    if work == source or (work / 'audio.flac').resolve() == source:
        raise ValueError('输入文件不能被输出音频覆盖。')
    work.mkdir(parents=True, exist_ok=True)
    if (work / 'metadata.json').exists() and not args.force:
        raise FileExistsError('已有准备结果；请复用它、换工作目录或明确使用--force。')
    with av.open(str(source)) as container:
        if not container.streams.audio:
            raise ValueError('媒体没有音轨。')
        duration = container.duration / av.time_base if container.duration else None
        if not duration:
            lengths = [float(s.duration * s.time_base) for s in container.streams if s.duration is not None]
            duration = max(lengths) if lengths else None
        if not duration:
            raise ValueError('无法读取媒体时长。')
        has_video = bool(container.streams.video)
        streams = [{'index': s.index, 'type': s.type, 'codec': s.codec_context.name}
                   for s in container.streams]
    start, end = selection(0, float(duration), args.start, args.end)
    executable = ffmpeg_executable(args.ffmpeg)
    audio = work / 'audio.flac'
    extract_audio(executable, source, audio, start, end - start)
    frames = []
    if has_video and not args.no_frames:
        frame_dir = work / 'frames'
        frame_dir.mkdir(exist_ok=True)
        sec = start
        while sec < end:
            frame = frame_dir / f'frame-{round(sec * 1000):010d}.jpg'
            subprocess.run([executable, '-hide_banner', '-loglevel', 'error', '-y',
                            '-ss', str(sec), '-i', str(source), '-frames:v', '1',
                            '-vf', 'scale=1280:-2', str(frame)], check=True)
            if frame.is_file():
                frames.append({'time_seconds': sec, 'file': frame.relative_to(work).as_posix()})
            sec += args.frame_every
    stat = source.stat()
    metadata = {'schema_version': 1, 'source': str(source), 'source_bytes': stat.st_size,
                'source_mtime_ns': stat.st_mtime_ns, 'duration_seconds': duration,
                'selection_start': start, 'selection_end': end, 'streams': streams,
                'audio': 'audio.flac', 'audio_sha256': fingerprint(audio), 'frames': frames}
    save_json(work / 'metadata.json', metadata)
    print(json.dumps({'prepared': str(work), 'duration_seconds': duration,
                      'selection': [start, end], 'frames': len(frames)}, ensure_ascii=False))


def normalize_segment(segment, offset, length):
    raw = mapping(segment)
    start, end = float(raw['start']), float(raw['end'])
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError('模型返回了非有限时间戳。')
    flags = []
    if start < 0 or end > length:
        flags.append('timestamp_clamped')
    start, end = max(0.0, start), min(length, end)
    text = str(raw.get('text', '')).strip()
    if start >= length or end <= start or not text:
        return None
    if raw.get('compression_ratio', 0) > 2.4:
        flags.append('possible_repetition')
    if raw.get('avg_logprob', 0) < -1:
        flags.append('low_model_confidence')
    if raw.get('no_speech_prob', 0) > 0.6:
        flags.append('possible_non_speech')
    return {'start': start + offset, 'end': end + offset, 'text': text,
            'avg_logprob': raw.get('avg_logprob'), 'no_speech_prob': raw.get('no_speech_prob'),
            'compression_ratio': raw.get('compression_ratio'), 'quality_flags': flags}


def write_results(segments, output, offset, length, state, state_path):
    count, discarded, flagged, last_text, repetitions = 0, 0, 0, None, 0
    progress_at = 0
    with (output / 'segments.jsonl').open('w', encoding='utf-8') as raw, \
         (output / 'transcript.txt').open('w', encoding='utf-8') as txt, \
         (output / 'transcript.srt').open('w', encoding='utf-8') as srt:
        for segment in segments:
            row = normalize_segment(segment, offset, length)
            if row is None:
                discarded += 1
                continue
            repetitions = repetitions + 1 if row['text'] == last_text else 0
            last_text = row['text']
            if repetitions >= 2:
                row['quality_flags'].append('repeated_segment')
            count += 1
            flagged += bool(row['quality_flags'])
            raw.write(json.dumps(row, ensure_ascii=False) + '\n'); raw.flush()
            txt.write(f"[{timestamp(row['start'])}–{timestamp(row['end'])}] {row['text']}\n"); txt.flush()
            srt.write(f"{count}\n{timestamp(row['start'], True)} --> {timestamp(row['end'], True)}\n{row['text']}\n\n"); srt.flush()
            state.update(segments_written=count, flagged_segments=flagged,
                         discarded_segments=discarded, last_emitted_end=row['end'])
            if row['end'] - offset >= progress_at:
                save_json(state_path, state)
                print(f"已输出至原录屏 {timestamp(row['end'])}", flush=True)
                progress_at = row['end'] - offset + 60
    state.update(segments_written=count, flagged_segments=flagged, discarded_segments=discarded)


def transcribe(args):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}', args.run_id):
        raise ValueError('--run-id只允许64字符以内的字母、数字、点、下划线和短横线。')
    if args.batch_size < 0 or args.beam_size <= 0:
        raise ValueError('批量需非负，beam-size需大于0。')
    if args.terms and len(args.terms) > 200:
        raise ValueError('--terms最多200个字符，只提供少量术语。')
    work = Path(args.work_dir).expanduser().resolve()
    metadata = json.loads((work / 'metadata.json').read_text(encoding='utf-8'))
    audio = (work / metadata['audio']).resolve()
    if audio.parent != work:
        raise ValueError('准备音频必须位于工作目录。')
    digest = fingerprint(audio)
    if digest != metadata['audio_sha256']:
        raise ValueError('准备音频已变动，请重新prepare。')
    base, upper = float(metadata['selection_start']), float(metadata['selection_end'])
    start, end = selection(base, upper, args.start, args.end)
    output = work / 'runs' / args.run_id
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / 'run.json'
    compute = args.compute_type or ('int8_float32' if args.device == 'cuda' else 'int8')
    settings = {'model': args.model, 'device': args.device, 'compute_type': compute,
                'language': args.language, 'beam_size': args.beam_size,
                'batch_size': args.batch_size, 'vad': not args.no_vad, 'terms': args.terms,
                'start': start, 'end': end, 'audio_sha256': digest}
    if state_path.exists() and not args.force:
        previous = json.loads(state_path.read_text(encoding='utf-8'))
        files = ['segments.jsonl', 'transcript.txt', 'transcript.srt']
        if previous.get('status') == 'complete' and previous.get('settings') == settings and \
                all((output / file).is_file() for file in files):
            print(f'复用已完成结果：{output}')
            return
        raise FileExistsError('该run-id已有不同或未完成结果；请换run-id或显式--force。')
    state = {'schema_version': 1, 'status': 'running', 'settings': settings,
             'segments_written': 0, 'notice': '机器转写；需复核，未进行说话人识别。'}
    save_json(state_path, state)
    started = time.monotonic()
    dll_handles = []
    try:
        for directory in args.cuda_libs:
            lib = Path(directory).expanduser().resolve()
            if not lib.is_dir():
                raise FileNotFoundError('CUDA运行库目录不存在。')
            os.environ['PATH'] = str(lib) + os.pathsep + os.environ.get('PATH', '')
            if os.name == 'nt':
                dll_handles.append(os.add_dll_directory(str(lib)))
        from faster_whisper import BatchedInferencePipeline, WhisperModel
        selected_audio = audio
        if start != base or end != upper:
            selected_audio = output / 'clip.flac'
            extract_audio(ffmpeg_executable(args.ffmpeg), audio, selected_audio, start - base, end - start)
        model = WhisperModel(args.model, device=args.device, compute_type=compute,
                             cpu_threads=args.cpu_threads,
                             download_root=args.model_cache or str(work / 'models'),
                             local_files_only=args.local_files_only)
        options = {'language': None if args.language == 'auto' else args.language,
                   'beam_size': args.beam_size, 'vad_filter': not args.no_vad,
                   'temperature': 0.0, 'initial_prompt': args.terms or None}
        if args.batch_size:
            segments, info = BatchedInferencePipeline(model=model).transcribe(
                str(selected_audio), batch_size=args.batch_size, **options)
        else:
            segments, info = model.transcribe(str(selected_audio), condition_on_previous_text=False, **options)
        state['transcription_info'] = mapping(info)
        write_results(segments, output, start, end - start, state, state_path)
        state.update(status='complete', processed_original_range=[start, end],
                     elapsed_seconds=round(time.monotonic() - started, 2))
        save_json(state_path, state)
        print(f'转写完成，核对材料：{output}', flush=True)
    except (Exception, KeyboardInterrupt) as error:
        state.update(status='failed', error_type=type(error).__name__, error=str(error),
                     elapsed_seconds=round(time.monotonic() - started, 2))
        save_json(state_path, state)
        raise
    finally:
        for handle in dll_handles:
            handle.close()


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare', help='读取媒体、提取音频与参考帧')
    prep.add_argument('source')
    prep.add_argument('--work-dir', required=True)
    prep.add_argument('--start', type=float)
    prep.add_argument('--end', type=float)
    prep.add_argument('--frame-every', type=float, default=300)
    prep.add_argument('--no-frames', action='store_true')
    prep.add_argument('--force', action='store_true')
    prep.add_argument('--ffmpeg')
    prep.set_defaults(handler=prepare)
    asr = commands.add_parser('transcribe', help='转写已准备的音频，保留原录屏偏移')
    asr.add_argument('--work-dir', required=True)
    asr.add_argument('--run-id', default='primary')
    asr.add_argument('--model', default='small')
    asr.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    asr.add_argument('--compute-type')
    asr.add_argument('--language', default='zh')
    asr.add_argument('--beam-size', type=int, default=5)
    asr.add_argument('--batch-size', type=int, default=0)
    asr.add_argument('--cpu-threads', type=int, default=4)
    asr.add_argument('--terms', default='')
    asr.add_argument('--start', type=float)
    asr.add_argument('--end', type=float)
    asr.add_argument('--no-vad', action='store_true')
    asr.add_argument('--model-cache')
    asr.add_argument('--local-files-only', action='store_true')
    asr.add_argument('--cuda-libs', action='append', default=[])
    asr.add_argument('--force', action='store_true')
    asr.add_argument('--ffmpeg')
    asr.set_defaults(handler=transcribe)
    return root


def main():
    args = parser().parse_args()
    try:
        args.handler(args)
        return 0
    except KeyboardInterrupt:
        print('转写已中断，部分结果与failed状态已保留。', file=sys.stderr)
        return 130
    except Exception as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
