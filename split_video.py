#!/usr/bin/env python3
"""
视频拆解工具 - 把剪辑好的成品视频按镜头切换拆成多个素材片段

用法:
    python split_video.py 成品视频.mp4 [--out 输出目录] [--threshold 0.3]
                           [--min-seg 1.0] [--mode copy|precise]

示例:
    python split_video.py output.mp4
    python split_video.py output.mp4 --out ./clips --mode precise

说明:
    --mode precise  重编码，切点精确到帧（默认，推荐）
    --mode copy     流复制，快，但切点对齐最近关键帧（大关键帧间隔视频可能明显偏移）
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from splitter import split_video_by_scenes  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="按镜头切换拆分成品视频为素材片段")
    parser.add_argument("input", help="成品视频路径")
    parser.add_argument("--out", default=None, help="输出目录（默认: 视频同目录下的 <文件名>_clips/）")
    parser.add_argument("--threshold", type=float, default=0.3,
                        help="镜头检测灵敏度 0.1-1.0，越小越敏感（默认 0.3）")
    parser.add_argument("--min-seg", type=float, default=1.0,
                        help="最短片段秒数，短于此的片段并入前一段（默认 1.0）")
    parser.add_argument("--mode", choices=['copy', 'precise'], default='precise',
                        help="切割模式：precise 精确到帧（默认）/ copy 流复制快但可能偏移")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 文件不存在 - {input_path}")
        sys.exit(1)

    if args.out:
        out_dir = Path(args.out)
    else:
        out_dir = input_path.parent / f"{input_path.stem}_clips"

    print(f"输入: {input_path}")
    print(f"输出: {out_dir}")
    print(f"模式: {args.mode} | 灵敏度: {args.threshold} | 最短片段: {args.min_seg}s")
    print("=" * 50)

    start = time.time()
    segments = split_video_by_scenes(
        str(input_path), str(out_dir),
        threshold=args.threshold, min_seg=args.min_seg, mode=args.mode,
        progress_cb=lambda p, m: print(f"  [{p:3d}%] {m}", flush=True)
    )
    elapsed = time.time() - start

    print("=" * 50)
    print(f"拆解完成: 共 {len(segments)} 段, 耗时 {elapsed:.1f}s")
    for seg in segments:
        print(f"  {Path(seg['path']).name}  "
              f"{seg['start']:.1f}s ~ {seg['end']:.1f}s  ({seg['dur']:.1f}s)")


if __name__ == '__main__':
    main()
