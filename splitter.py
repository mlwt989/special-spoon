"""
视频拆解引擎 - 把剪辑好的成品视频按镜头切换拆成多个素材片段
- 场景检测：FFmpeg select=gt(scene,threshold)（与 renderer 同一方案）
- 切割方式：
  - copy 模式：-c copy 流复制，速度快但切点对齐关键帧（可能有 0.5-2s 偏差）
  - precise 模式：libx264 重编码，切点精确到帧
- 纯 FFmpeg 命令行，不依赖 MoviePy
"""

import os
import re
import sys
import subprocess
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.webm', '.m4v'}


def safe_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def get_duration(path):
    """快速获取视频时长 — 只探测头部，不解码整个文件"""
    try:
        result = subprocess.run(
            [FFMPEG, '-i', str(path)],
            capture_output=True, text=True, timeout=30
        )
    except OSError:
        try:
            result = subprocess.run(
                [FFMPEG, '-i', str(path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, timeout=30
            )
        except Exception:
            return 0.0
    for line in result.stderr.split('\n'):
        m = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', line)
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    return 0.0


def _detect_scene_times(path, start, window, threshold=0.3):
    """检测 [start, start+window] 区间内的镜头切换绝对时间点。

    返回升序的绝对时间列表（秒），不含 start 和 start+window。
    """
    cmd = [
        FFMPEG, '-hide_banner', '-analyzeduration', '0', '-probesize', '5000000',
        '-ss', f'{start:.3f}', '-t', f'{window:.3f}',
        '-i', str(path),
        '-vf', f"fps=5,select=gt(scene\\,{threshold}),showinfo",
        '-an', '-f', 'null', '-'
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        try:
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True, timeout=60)
        except Exception:
            return []
    if not result.stderr:
        return []
    bounds = []
    for line in result.stderr.split('\n'):
        m = re.search(r'pts_time:(\d+\.?\d*)', line)
        if m:
            t = float(m.group(1))
            if 0.0 < t < window - 0.05:
                bounds.append(start + t)
    # 去重 + 排序
    cleaned = []
    for t in sorted(bounds):
        if not cleaned or t - cleaned[-1] > 0.2:
            cleaned.append(t)
    return cleaned


def detect_all_boundaries(path, dur, threshold=0.3, window=150):
    """分窗口检测整段视频的镜头切换点，返回升序绝对时间列表。

    每窗口检测 150s（重叠 0.5s），避免单个长命令处理超长视频。
    """
    if dur <= 0:
        return []
    bounds = []
    pos = 0.0
    while pos < dur:
        w = min(window, dur - pos + 0.5)
        b = _detect_scene_times(path, pos, w, threshold)
        # 窗口边界附近的点留到下一窗口（重叠 0.5s 去重）
        bounds.extend([t for t in b if t > pos + 0.5])
        pos += window
    cleaned = []
    for t in sorted(bounds):
        if not cleaned or t - cleaned[-1] > 0.2:
            cleaned.append(t)
    return cleaned


def detect_keyframes(path, dur):
    """扫描全片关键帧（I 帧）的绝对时间点，用于 copy 模式切割对齐。

    用 -skip_frame nokey 只解码关键帧，速度快；返回升序时间列表。
    失败时返回 []（调用方回退到不吸附）。
    """
    if dur <= 0:
        return []
    cmd = [
        FFMPEG, '-hide_banner', '-analyzeduration', '0', '-probesize', '5000000',
        '-skip_frame', 'nokey',
        '-i', str(path),
        '-vf', 'showinfo',
        '-an', '-f', 'null', '-'
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        try:
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True, timeout=120)
        except Exception:
            return []
    if not result.stderr:
        return []
    frames = []
    for line in result.stderr.split('\n'):
        m = re.search(r'pts_time:(\d+\.?\d*)', line)
        if m:
            t = float(m.group(1))
            if 0.0 <= t <= dur:
                frames.append(t)
    # 去重 + 排序
    cleaned = []
    for t in sorted(frames):
        if not cleaned or t - cleaned[-1] > 0.05:
            cleaned.append(t)
    return cleaned


def _snap_to_keyframes(cuts, keyframes):
    """把内部切点吸附到最近的关键帧，保证 copy 模式每个片段从关键帧起刀。

    cuts: [0, t1, t2, ..., dur]；keyframes: 升序关键帧列表。
    返回吸附后的 cuts（起点 0 和终点 dur 不动）。
    """
    if not keyframes:
        return cuts
    new_cuts = [cuts[0]]
    for t in cuts[1:-1]:
        nearest = min(keyframes, key=lambda k: abs(k - t))
        if nearest > new_cuts[-1] and nearest < cuts[-1]:
            new_cuts.append(nearest)
        else:
            new_cuts.append(t)
    new_cuts.append(cuts[-1])
    # 保证严格递增，防止吸附后相邻切点重合
    result = [new_cuts[0]]
    for t in new_cuts[1:]:
        if t - result[-1] >= 0.1:
            result.append(t)
    return result


def _build_cut_points(cut_points, dur, min_seg=1.0):
    """把切割点列表 [0, t1, t2, ..., dur] 转成段列表，合并过碎的片段。

    返回 [(start, end), ...]，总时长约等于 dur。
    """
    cuts = sorted(set([0.0] + [b for b in cut_points if 0 < b < dur] + [dur]))
    # 合并太短的片段：把 < min_seg 的片段并入前一段
    merged = []
    for i in range(len(cuts) - 1):
        seg_start = cuts[i]
        seg_end = cuts[i + 1]
        seg_dur = seg_end - seg_start
        if merged and seg_dur < min_seg:
            # 并入前一段：前一段的 end 延到 seg_end
            merged[-1] = (merged[-1][0], seg_end)
        else:
            merged.append((seg_start, seg_end))
    return merged


def _run_ffmpeg(args, timeout=900):
    cmd = [FFMPEG, '-y', '-hide_banner', '-loglevel', 'warning'] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except OSError:
        try:
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True, timeout=timeout)
        except OSError as e2:
            raise RuntimeError(f"FFmpeg subprocess failed: {e2}") from e2
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed (code {result.returncode}): "
            f"{result.stderr[-500:] if result.stderr else 'no stderr'}"
        )
    return result


def split_video_by_scenes(input_path, output_dir, threshold=0.3, min_seg=1.0,
                          mode='copy', progress_cb=None):
    """把成品视频按镜头切换拆成多个素材片段。

    参数:
        input_path: 成品视频路径
        output_dir: 输出目录（自动创建）
        threshold: 场景检测阈值（0.1-1.0，越小越敏感）
        min_seg: 最短片段秒数，短于此的片段并入前一段
        mode: 'copy' 流复制（快）/ 'precise' 重编码（精确）
        progress_cb: 可选回调 progress_cb(percent, message)
    返回:
        [{"index": 1, "start": 0.0, "end": 3.2, "dur": 3.2, "path": "..."}, ...]
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dur = get_duration(input_path)
    if dur <= 0:
        raise ValueError("无法读取视频时长，文件可能损坏")

    def _report(p, msg):
        if progress_cb:
            try:
                progress_cb(p, msg)
            except Exception:
                pass

    _report(5, "检测镜头切换点...")
    boundaries = detect_all_boundaries(input_path, dur, threshold=threshold)

    # 先构造原始切点列表 [0, t1, t2, ..., dur]
    cuts = sorted(set([0.0] + [b for b in boundaries if 0 < b < dur] + [dur]))

    # copy 模式：把内部切点吸附到最近的关键帧，避免片段开头带上一镜头的尾巴
    # （流复制只能从关键帧起刀，不吸附就会把切点拉前/拉后到关键帧处）
    if mode == 'copy':
        _report(8, "扫描关键帧（对齐切点）...")
        keyframes = detect_keyframes(input_path, dur)
        if keyframes:
            cuts = _snap_to_keyframes(cuts, keyframes)
            # 吸附后可能产生过碎片段，重新合并
            segments = _build_cut_points(cuts, dur, min_seg=min_seg)
        else:
            _report(10, "关键帧扫描失败，改用精确重编码切分")
            mode = 'precise'
            segments = _build_cut_points(cuts, dur, min_seg=min_seg)
    else:
        segments = _build_cut_points(cuts, dur, min_seg=min_seg)

    stem = input_path.stem
    results = []
    total = len(segments)

    for i, (s, e) in enumerate(segments, start=1):
        seg_dur = e - s
        out_path = output_dir / f"{stem}_seg{i:03d}.mp4"
        _report(5 + int(90 * (i - 1) / total), f"切分第 {i}/{total} 段...")

        if mode == 'copy':
            args = [
                '-ss', f'{s:.3f}', '-t', f'{seg_dur:.3f}',
                '-i', str(input_path),
                '-map', '0:v:0', '-map', '0:a?',
                '-c', 'copy', '-avoid_negative_ts', 'make_zero',
                str(out_path)
            ]
        else:  # precise — 重编码保证切点精确（veryfast 提速 ~3x，60fps 视频友好）
            args = [
                '-ss', f'{s:.3f}', '-t', f'{seg_dur:.3f}',
                '-i', str(input_path),
                '-map', '0:v:0', '-map', '0:a?',
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                '-threads', '1',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                str(out_path)
            ]
        _run_ffmpeg(args)
        if not out_path.exists() or out_path.stat().st_size < 1024:
            raise RuntimeError(f"切分第 {i} 段失败：输出文件无效")

        results.append({
            "index": i,
            "start": round(s, 3),
            "end": round(e, 3),
            "dur": round(seg_dur, 3),
            "path": str(out_path)
        })

    _report(100, "拆解完成")
    return results
