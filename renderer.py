"""
渲染引擎 v2 - 双轨解绑架构
- 视频轨：素材按 5-8 秒切分长镜头，xfade 拼接
- 字幕轨：独立 overlay 层，按总时长均匀分布
- 两条轨道互不触发，各自独立运行
- 支持 HEVC/H.265 输入（iPhone 视频）
"""

import os
import sys
import re
import subprocess
import tempfile
import shutil
import asyncio
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REGULAR = "C:/Windows/Fonts/msyh.ttc"

# 跨平台字体回退表（Linux 服务器部署时使用）
_FONT_FALLBACKS_REGULAR = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]
_FONT_FALLBACKS_BOLD = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
]


def resolve_font(path, bold=False):
    """解析字体路径：本地存在则直接用，否则按平台回退"""
    if path and os.path.exists(path):
        return path
    fallbacks = _FONT_FALLBACKS_BOLD if bold else _FONT_FALLBACKS_REGULAR
    for fb in fallbacks:
        if os.path.exists(fb):
            return fb
    return path  # 找不到就原样返回，让 PIL 报错时信息更明确

VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.webm', '.m4v'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
AUDIO_EXTS = {'.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg', '.wma'}


def safe_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def run_ffmpeg(args, check=True, timeout=900):
    """运行 FFmpeg，所有 libx264 编码默认 -threads 1 避免多线程崩溃"""
    cmd = [FFMPEG, '-y', '-hide_banner', '-loglevel', 'warning'] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except OSError as e:
        # Windows 上 subprocess 管道创建可能失败 ([Errno 22] Invalid argument)
        # 重试一次，不带 capture_output
        sys.stderr.write(f'[FFmpeg] subprocess OSError: {e}, retrying without pipes...\n')
        sys.stderr.flush()
        try:
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True, timeout=timeout)
        except OSError as e2:
            raise RuntimeError(f"FFmpeg subprocess failed: {e2}") from e2
    if check and result.returncode != 0:
        sys.stderr.write(f'\nFFmpeg RC={result.returncode}\n  STDERR: {result.stderr[-1200:] if result.stderr else "(none)"}\n')
        sys.stderr.flush()
        raise RuntimeError(f"FFmpeg failed (code {result.returncode}): {result.stderr[-500:] if result.stderr else 'no stderr'}")
    return result


def get_duration(path):
    """快速获取视频时长 — 只探测头部，不解码整个文件"""
    try:
        result = subprocess.run(
            [FFMPEG, '-i', str(path)],
            capture_output=True, text=True, timeout=30
        )
    except OSError:
        # Windows 管道创建失败时，退回到不用管道的方式
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


def get_file_type(filename):
    ext = Path(filename).suffix.lower()
    if ext in VIDEO_EXTS:
        return 'video'
    if ext in IMAGE_EXTS:
        return 'image'
    if ext in AUDIO_EXTS:
        return 'audio'
    return None


def wrap_text(draw, text, font, max_width):
    lines = []
    current = ""
    for char in text:
        test = current + char
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = char
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def make_text_png(text, target_w, target_h, font_path, font_size, position,
                  output_path, stroke_width=3, max_width_ratio=0.85):
    font_path = resolve_font(font_path, bold=("bd" in os.path.basename(str(font_path)).lower()))
    max_width = int(target_w * max_width_ratio)
    img = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, font_size)

    lines = wrap_text(draw, text, font, max_width)
    line_height = int(font_size * 1.4)
    total_height = len(lines) * line_height

    if position == "center":
        y = (target_h - total_height) // 2
    else:
        y = target_h - 280 - total_height

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (target_w - text_w) // 2
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 220))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_height

    img.save(output_path)


class VideoRenderer:
    """
    双轨解绑渲染器

    架构：
      Phase 1 — 视频轨：素材 → 5-8s 长镜头切分 → xfade 拼接 → video_track.mp4
      Phase 2 — 字幕轨：字幕列表 → 按总时长均匀分布 → PNG overlay → with_subs.mp4
      Phase 3 — BGM：混入背景音乐 → output.mp4

    视频轨和字幕轨完全独立：
    - 视频切分基于素材时长，与字幕数量无关
    - 字幕分布基于视频总时长，与视频切分点无关
    """

    def __init__(self, materials, config, output_path,
                 bgm_path=None, title=None, subtitles=None, ending=None,
                 custom_effect=None, target_duration=None, adapt_strategy='smart',
                 subtitle_font=None, subtitle_font_size=None,
                 narration_enabled=False,
                 narration_voice='zh-CN-XiaoxiaoNeural', narration_rate=1.0,
                 narration_volume=1.0, bgm_volume=0.3,
                 watermark=None,
                 progress_callback=None):
        self.materials = materials
        self.config = config
        self.output_path = output_path
        self.bgm_path = bgm_path
        self.title = title
        self.subtitles = [s.strip() for s in (subtitles or []) if s and s.strip()]
        self.ending = ending
        self.custom_effect = custom_effect or ""
        self.target_duration = target_duration
        self.adapt_strategy = adapt_strategy
        self.subtitle_font = subtitle_font
        self.subtitle_font_size = subtitle_font_size  # None = 用模板默认
        self.narration_enabled = narration_enabled
        self.narration_voice = narration_voice
        self.narration_rate = narration_rate
        self.narration_volume = narration_volume
        self.bgm_volume = bgm_volume
        self.watermark = watermark  # dict: path/position/animation/size/opacity
        self.progress_callback = progress_callback

        # 根据自定义效果描述调整配置
        if self.custom_effect:
            self._apply_custom_effect()

    def _progress(self, percent, message):
        if self.progress_callback:
            self.progress_callback(percent, message)

    def _apply_custom_effect(self):
        """
        根据自定义效果描述中的关键词调整渲染参数。
        支持的关键词：
          冷色调 → 降饱和 + 偏蓝
          暖色调 → 提暖 + 偏黄
          快节奏 → 短镜头 + 快转场
          慢节奏 → 长镜头 + 慢转场
          电影感 → 高对比 + 低饱和 + letterbox 感
          黑白 / 单色 → 去饱和
          高对比 → 提对比度
          柔和 / 清新 → 降对比 + 提亮
          复古 → 降饱和 + 偏黄
          赛博朋克 → 高饱和 + 高对比
        """
        effect = self.custom_effect.lower()
        cg = self.config.get("color_grade", {})
        vt = self.config.get("video_track", {})

        # 确保字段存在
        cg.setdefault("saturation", 1.0)
        cg.setdefault("brightness", 0.0)
        cg.setdefault("contrast", 1.0)
        cg.setdefault("gamma", 1.0)

        changes = []

        if "冷色调" in effect or "冷色" in effect or "偏蓝" in effect:
            cg["saturation"] = min(cg["saturation"], 0.85)
            cg["gamma"] = min(cg["gamma"], 0.95)
            changes.append("冷色调")

        if "暖色调" in effect or "暖色" in effect or "偏黄" in effect or "偏暖" in effect:
            cg["saturation"] = max(cg["saturation"], 1.05)
            cg["brightness"] = max(cg["brightness"], 0.03)
            changes.append("暖色调")

        if "黑白" in effect or "单色" in effect or "去色" in effect:
            cg["saturation"] = 0.0
            changes.append("黑白")

        if "电影感" in effect or "电影" in effect or "cinema" in effect:
            cg["saturation"] = min(cg["saturation"], 0.88)
            cg["contrast"] = max(cg["contrast"], 1.1)
            cg["gamma"] = min(cg["gamma"], 0.95)
            changes.append("电影感")

        if "高对比" in effect or "强对比" in effect:
            cg["contrast"] = max(cg["contrast"], 1.15)
            changes.append("高对比")

        if "柔和" in effect or "清新" in effect or "日系" in effect:
            cg["contrast"] = min(cg["contrast"], 0.92)
            cg["brightness"] = max(cg["brightness"], 0.04)
            cg["saturation"] = min(cg["saturation"], 0.9)
            changes.append("柔和清新")

        if "复古" in effect or "怀旧" in effect:
            cg["saturation"] = min(cg["saturation"], 0.75)
            cg["contrast"] = min(cg["contrast"], 0.95)
            changes.append("复古")

        if "赛博" in effect or "cyber" in effect or "霓虹" in effect:
            cg["saturation"] = max(cg["saturation"], 1.3)
            cg["contrast"] = max(cg["contrast"], 1.2)
            changes.append("赛博朋克")

        if "快节奏" in effect or "快剪" in effect or "快速" in effect:
            vt["clip_duration_min"] = max(2, vt.get("clip_duration_min", 5) - 2)
            vt["clip_duration_max"] = max(3, vt.get("clip_duration_max", 8) - 3)
            vt["transition_duration"] = max(0.2, vt.get("transition_duration", 0.6) - 0.2)
            changes.append("快节奏")

        if "慢节奏" in effect or "慢剪" in effect or "缓慢" in effect:
            vt["clip_duration_min"] = vt.get("clip_duration_min", 5) + 2
            vt["clip_duration_max"] = vt.get("clip_duration_max", 8) + 3
            vt["transition_duration"] = vt.get("transition_duration", 0.6) + 0.3
            changes.append("慢节奏")

        # 写回 config
        self.config["color_grade"] = cg
        self.config["video_track"] = vt

        if changes:
            sys.stderr.write(f"[custom_effect] 应用效果: {', '.join(changes)}\n")
            sys.stderr.flush()

    def render(self):
        out_cfg = self.config["output"]
        target_w = out_cfg["width"]
        target_h = out_cfg["height"]
        fps = out_cfg["fps"]

        visual_materials = [m for m in self.materials if m["type"] in ("video", "image")]
        if not visual_materials:
            raise ValueError("没有视频或图片素材")

        tmp_dir = tempfile.mkdtemp(prefix="webrender_")
        self._tmp_dir = tmp_dir

        try:
            # === Phase 1: 构建视频轨 ===
            self._progress(5, "构建视频轨：切分长镜头...")
            video_track_path = self._build_video_track(
                tmp_dir, target_w, target_h, fps, visual_materials
            )
            total_duration = get_duration(video_track_path)
            self._progress(40, f"视频轨完成：{total_duration:.1f}s")

            # === Phase 2: 叠加字幕轨（独立层）===
            if self.subtitles:
                self._progress(
                    45,
                    f"叠加字幕轨：{len(self.subtitles)} 条字幕，"
                    f"每 {total_duration / len(self.subtitles):.1f}s 一条"
                )
                final_video = self._overlay_subtitles(
                    video_track_path, total_duration, tmp_dir,
                    target_w, target_h, fps
                )
                safe_remove(video_track_path)
            else:
                final_video = video_track_path

            # === Phase 2.5: 叠加水印 ===
            if self.watermark and self.watermark.get("path") and \
               os.path.exists(self.watermark["path"]):
                self._progress(72, "叠加水印...")
                wm_video = self._overlay_watermark(
                    final_video, total_duration, tmp_dir,
                    target_w, target_h, fps
                )
                safe_remove(final_video)
                final_video = wm_video

            # === Phase 3: AI 配音生成 ===
            narration_path = None
            if self.narration_enabled and self.subtitles:
                self._progress(78, "生成 AI 配音...")
                narration_path = self._generate_narration(tmp_dir)
                if narration_path:
                    self._progress(83, "配音生成完成")
                else:
                    self._progress(83, "配音生成失败，跳过")

            # === Phase 4: 混音（配音 + BGM）===
            if narration_path and self.bgm_path and os.path.exists(self.bgm_path):
                self._progress(85, "混入配音和背景音乐...")
                self._mix_narration_bgm(final_video, narration_path, self.output_path)
                safe_remove(final_video)
            elif narration_path:
                self._progress(85, "混入配音...")
                self._mix_narration_only(final_video, narration_path, self.output_path)
                safe_remove(final_video)
            elif self.bgm_path and os.path.exists(self.bgm_path):
                self._progress(85, "混入背景音乐...")
                self._mix_bgm(final_video, self.output_path)
                safe_remove(final_video)
            else:
                self._progress(90, "封装输出...")
                run_ffmpeg(['-i', final_video, '-c', 'copy', self.output_path])
                safe_remove(final_video)

            self._progress(100, "渲染完成!")
            return True

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # =================================================================
    # Phase 1: 视频轨 — 素材按 5-8 秒切分长镜头，xfade 拼接
    # =================================================================

    def _build_video_track(self, tmp_dir, target_w, target_h, fps, visual_materials):
        track_cfg = self.config.get("video_track", {})
        min_dur = track_cfg.get("clip_duration_min", 5)
        max_dur = track_cfg.get("clip_duration_max", 8)
        transition_dur = track_cfg.get("transition_duration", 0.6)

        # 预计算：每个素材的可用时长（考虑手动裁剪）
        mat_durations = []
        for mat in visual_materials:
            if mat["type"] == "video":
                d = get_duration(mat["path"])
                if d <= 0:
                    mat_durations.append(0)
                    continue
                # 手动裁剪：使用用户设定的起止时间
                if self.adapt_strategy == 'manual':
                    trim_start = mat.get("trimStart", 0) or 0
                    trim_end = mat.get("trimEnd") or d
                    effective_dur = max(0.5, trim_end - trim_start)
                    mat_durations.append(effective_dur)
                else:
                    mat_durations.append(d)
            else:
                mat_durations.append((min_dur + max_dur) / 2)

        total_available = sum(mat_durations)
        if total_available <= 0:
            raise ValueError("没有可用的视频/图片素材")

        # 计算目标时长和缩放比例
        scale = 1.0
        speed_factor = 1.0  # 整体变速因子
        if self.target_duration and self.target_duration > 0:
            title_dur = 0
            if self.title and self.config.get("title", {}).get("enabled", False):
                title_dur = self.config.get("title", {}).get("duration", 2.5)
            ending_dur = 0
            if self.config.get("ending", {}).get("enabled", False) or self.ending:
                ending_dur = self.config.get("ending", {}).get("duration", 2.5)

            body_target = self.target_duration - title_dur - ending_dur
            if body_target > 0:
                if self.adapt_strategy == 'speed':
                    # 整体变速：scale 转为速度因子
                    speed_factor = total_available / body_target
                    sys.stderr.write(
                        f"[duration] speed mode: target={body_target:.1f}s, "
                        f"available={total_available:.1f}s, speed={speed_factor:.2f}x\n"
                    )
                    sys.stderr.flush()
                else:
                    # 智能截取 / 手动裁剪：按比例缩放
                    scale = body_target / total_available
                    sys.stderr.write(
                        f"[duration] target={self.target_duration}s, strategy={self.adapt_strategy}, "
                        f"body_target={body_target:.1f}s, available={total_available:.1f}s, scale={scale:.2f}\n"
                    )
                    sys.stderr.flush()

        segments = []

        for i, mat in enumerate(visual_materials):
            name = mat.get("name", Path(mat["path"]).name)
            self._progress(
                5 + int(i / max(len(visual_materials), 1) * 30),
                f"切分素材 {i+1}/{len(visual_materials)}: {name}"
            )

            if mat["type"] == "video":
                full_dur = mat_durations[i]
                if full_dur <= 0:
                    continue

                # 手动裁剪：确定实际截取的起止位置
                if self.adapt_strategy == 'manual':
                    trim_start = mat.get("trimStart", 0) or 0
                    trim_end = mat.get("trimEnd") or get_duration(mat["path"])
                    actual_start = trim_start
                    actual_dur = max(0.5, trim_end - trim_start)
                else:
                    actual_start = 0
                    actual_dur = full_dur

                # 整体变速模式：每段用原始时长，之后统一调速
                if self.adapt_strategy == 'speed':
                    allocated = actual_dur
                else:
                    allocated = actual_dur * scale

                target_seg = (min_dur + max_dur) / 2
                num_segs = max(1, round(allocated / target_seg))
                seg_dur = allocated / num_segs
                seg_dur = max(1.0, seg_dur)

                for j in range(num_segs):
                    if self.adapt_strategy == 'manual':
                        # 手动模式：从裁剪区域开始计算
                        seg_start = actual_start + j * (actual_dur / num_segs)
                    else:
                        seg_start = j * (full_dur / num_segs)

                    seg_path = os.path.join(tmp_dir, f"seg_{len(segments):03d}.mp4")

                    if self.adapt_strategy == 'speed' and speed_factor != 1.0:
                        # 整体变速：先提取原始段，再调速
                        self._process_video_segment_speed(
                            mat["path"], seg_start, seg_dur, seg_path,
                            target_w, target_h, fps, speed_factor
                        )
                    else:
                        self._process_video_segment(
                            mat["path"], seg_start, seg_dur, seg_path,
                            target_w, target_h, fps
                        )
                    segments.append((seg_path, seg_dur))
            else:
                if self.adapt_strategy == 'speed':
                    seg_dur = mat_durations[i] / speed_factor
                else:
                    seg_dur = mat_durations[i] * scale
                seg_dur = max(1.0, seg_dur)
                seg_path = os.path.join(tmp_dir, f"seg_{len(segments):03d}.mp4")
                self._process_image_segment(
                    mat["path"], seg_dur, seg_path,
                    target_w, target_h, fps
                )
                segments.append((seg_path, seg_dur))

        if not segments:
            raise ValueError("没有可用的视频/图片素材")

        # 组装完整视频轨：标题片头 + 视频段 + 片尾
        all_parts = []
        all_durations = []

        # 标题片头
        if self.title and self.config.get("title", {}).get("enabled", False):
            title_path = os.path.join(tmp_dir, "title_card.mp4")
            self._make_card(title_path, self.title, "title", target_w, target_h, fps)
            all_parts.append(title_path)
            title_cfg = self.config.get("title", {})
            all_durations.append(title_cfg.get("duration", 2.5))

        # 视频段
        all_parts.extend([s[0] for s in segments])
        all_durations.extend([s[1] for s in segments])

        # 片尾
        ending_cfg = self.config.get("ending", {})
        if ending_cfg.get("enabled", False) or self.ending:
            ending_path = os.path.join(tmp_dir, "ending_card.mp4")
            ending_text = self.ending or ending_cfg.get("text", "关注我们 了解更多")
            self._make_card(ending_path, ending_text, "ending", target_w, target_h, fps)
            all_parts.append(ending_path)
            all_durations.append(ending_cfg.get("duration", 2.5))

        # xfade 拼接
        self._progress(38, f"拼接视频轨：{len(all_parts)} 段 (交叉溶解 {transition_dur}s)...")
        video_path = os.path.join(tmp_dir, "video_track.mp4")
        self._concatenate(all_parts, all_durations, video_path, transition_dur)
        return video_path

    def _process_video_segment(self, input_path, start, duration, output_path,
                               target_w, target_h, fps):
        """从源视频提取一段，缩放裁切到目标尺寸，应用色调。支持 HEVC/H.265 输入。"""
        cg = self.config.get("color_grade", {})
        eq_str = ""
        if cg.get("saturation", 1.0) != 1.0 or cg.get("contrast", 1.0) != 1.0 or \
           cg.get("brightness", 0.0) != 0.0 or cg.get("gamma", 1.0) != 1.0:
            eq_str = f",eq=saturation={cg.get('saturation', 1.0)}:brightness={cg.get('brightness', 0.0)}:contrast={cg.get('contrast', 1.0)}:gamma={cg.get('gamma', 1.0)}"

        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"fps={fps},format=yuv420p{eq_str}"
        )
        run_ffmpeg([
            '-analyzeduration', '0',
            '-probesize', '5000000',
            '-ss', f'{start:.3f}',
            '-i', input_path,
            '-t', f'{duration:.3f}',
            '-vf', vf,
            '-c:v', 'libx264', '-preset', 'fast',
            '-an',
            '-threads', '1',
            output_path
        ])

    def _process_video_segment_speed(self, input_path, start, duration, output_path,
                                      target_w, target_h, fps, speed_factor):
        """整体变速处理：提取视频段后用 setpts 调整播放速度"""
        cg = self.config.get("color_grade", {})
        eq_str = ""
        if cg.get("saturation", 1.0) != 1.0 or cg.get("contrast", 1.0) != 1.0 or \
           cg.get("brightness", 0.0) != 0.0 or cg.get("gamma", 1.0) != 1.0:
            eq_str = f",eq=saturation={cg.get('saturation', 1.0)}:brightness={cg.get('brightness', 0.0)}:contrast={cg.get('contrast', 1.0)}:gamma={cg.get('gamma', 1.0)}"

        # setpts: speed_factor > 1 = 加快（帧时间戳压缩），< 1 = 放慢
        pts_factor = 1.0 / speed_factor

        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"setpts={pts_factor}*PTS,"
            f"fps={fps},format=yuv420p{eq_str}"
        )
        run_ffmpeg([
            '-analyzeduration', '0',
            '-probesize', '5000000',
            '-ss', f'{start:.3f}',
            '-i', input_path,
            '-t', f'{duration:.3f}',
            '-vf', vf,
            '-c:v', 'libx264', '-preset', 'fast',
            '-an',
            '-threads', '1',
            output_path
        ])

    def _process_image_segment(self, input_path, duration, output_path,
                               target_w, target_h, fps):
        """图片生成指定时长的视频段，应用色调"""
        cg = self.config.get("color_grade", {})
        eq_str = ""
        if cg.get("saturation", 1.0) != 1.0 or cg.get("contrast", 1.0) != 1.0 or \
           cg.get("brightness", 0.0) != 0.0 or cg.get("gamma", 1.0) != 1.0:
            eq_str = f",eq=saturation={cg.get('saturation', 1.0)}:brightness={cg.get('brightness', 0.0)}:contrast={cg.get('contrast', 1.0)}:gamma={cg.get('gamma', 1.0)}"

        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"format=yuv420p{eq_str},fps={fps}"
        )
        run_ffmpeg([
            '-loop', '1', '-i', input_path,
            '-t', f'{duration:.3f}',
            '-vf', vf,
            '-c:v', 'libx264', '-preset', 'fast',
            '-threads', '1',
            output_path
        ])

    # =================================================================
    # Phase 2: 字幕轨 — 独立 overlay 层，按总时长均匀分布
    # =================================================================

    def _overlay_subtitles(self, video_path, total_duration, tmp_dir,
                           target_w, target_h, fps):
        """
        字幕作为独立覆盖层叠加到视频上。

        - 字幕列表按总时长均匀分布：每条字幕占 total_duration / N 秒
        - 字幕时间轴完全独立于视频切分点
        - 视频切换时字幕不重置，保持自己的节奏
        """
        sub_cfg = self.config.get("subtitle_track", {})
        # 优先使用用户选择的字体/字号，否则用模板配置
        font_path = self.subtitle_font or sub_cfg.get("font", FONT_REGULAR)
        font_size = self.subtitle_font_size or sub_cfg.get("font_size", 56)
        stroke_width = sub_cfg.get("stroke_width", 3)
        max_width_ratio = sub_cfg.get("max_width_ratio", 0.85)

        num_subs = len(self.subtitles)
        if num_subs == 0:
            return video_path
        slot_dur = total_duration / num_subs

        # 逐条叠加：每次只 2 个输入（当前视频 + 1 条字幕），内存有界。
        # 原先把 N 个 -loop 1 无限图片输入一次性塞进同一条 filtergraph，
        # 字幕多时所有无限流被缓冲导致 OOM（Cannot allocate memory）。
        current = video_path
        for idx, text in enumerate(self.subtitles):
            png_path = os.path.join(tmp_dir, f"sub_{idx:03d}.png")
            make_text_png(
                text, target_w, target_h, font_path, font_size,
                "bottom", png_path, stroke_width, max_width_ratio
            )
            start = idx * slot_dur
            end = (idx + 1) * slot_dur
            self._progress(
                45 + int(idx / max(num_subs, 1) * 35),
                f"字幕 {idx+1}/{num_subs}: \"{text[:20]}...\" @ {start:.1f}s-{end:.1f}s"
            )
            # 最后一条直接输出最终结果，其余输出中间累加文件
            if idx == num_subs - 1:
                output_path = os.path.join(tmp_dir, "with_subs.mp4")
            else:
                output_path = os.path.join(tmp_dir, f"subs_acc_{idx:03d}.mp4")
            run_ffmpeg([
                '-i', current,
                '-loop', '1', '-framerate', str(fps), '-i', png_path,
                '-filter_complex',
                f"[0:v][1:v]overlay=0:0:"
                f"enable='between(t,{start:.3f},{end:.3f})'[vout]",
                '-map', '[vout]',
                '-c:v', 'libx264', '-preset', 'fast',
                '-pix_fmt', 'yuv420p',
                '-t', f'{total_duration:.3f}',
                '-threads', '1',
                output_path
            ])
            current = output_path

        return current

    # =================================================================
    # Phase 2.5: 水印 overlay — 位置 / 大小 / 透明度 / 动画
    # =================================================================

    def _overlay_watermark(self, video_path, total_duration, tmp_dir,
                           target_w, target_h, fps):
        """
        将水印图片叠加到视频上。
        - position: 九宫格位置（40px 边距）
        - size: 水印宽度占视频宽度的百分比
        - opacity: 不透明度 10-100
        - animation: none / fade / slide / pulse
        """
        wm = self.watermark
        position = wm.get("position", "bottom-right")
        animation = wm.get("animation", "none")
        size_pct = wm.get("size", 15) / 100.0
        opacity = wm.get("opacity", 90) / 100.0

        margin = 40

        # --- 位置表达式（overlay 变量：W/H 主画面，w/h 水印）---
        pos_map = {
            "top-left":      (f"{margin}", f"{margin}"),
            "top-center":    ("(W-w)/2", f"{margin}"),
            "top-right":     (f"W-w-{margin}", f"{margin}"),
            "middle-left":   (f"{margin}", "(H-h)/2"),
            "center":        ("(W-w)/2", "(H-h)/2"),
            "middle-right":  (f"W-w-{margin}", "(H-h)/2"),
            "bottom-left":   (f"{margin}", f"H-h-{margin}"),
            "bottom-center": ("(W-w)/2", f"H-h-{margin}"),
            "bottom-right":  (f"W-w-{margin}", f"H-h-{margin}"),
        }
        x_expr, y_expr = pos_map.get(position, pos_map["bottom-right"])

        # --- 水印流滤镜链 ---
        wm_filters = [f"scale={int(target_w * size_pct)}:-1", "format=rgba"]

        # 不透明度
        if opacity < 1.0:
            wm_filters.append(f"colorchannelmixer=aa={opacity:.2f}")

        # --- 动画处理 ---
        slide_dur = 0.8
        fade_out_st = max(0, total_duration - 1.0)

        if animation == "fade":
            wm_filters.append("fade=t=in:st=0:d=1:alpha=1")
            wm_filters.append(f"fade=t=out:st={fade_out_st:.2f}:d=1:alpha=1")

        elif animation == "pulse":
            # 呼吸：缩放在 100%~105% 之间脉动，周期 2.5s
            wm_filters.append(
                "scale=w='iw*(1+0.05*sin(2*PI*t/2.5))':"
                "h='ih*(1+0.05*sin(2*PI*t/2.5))':eval=frame"
            )

        elif animation == "slide":
            # 滑入：从最近的边缘滑入，位置表达式随时间变化
            # 注意：表达式内的逗号必须转义为 \, 否则被当作滤镜分隔符
            if "left" in position:
                x_expr = (
                    f"if(lt(t\\,{slide_dur})\\,"
                    f"-w+({margin}+w)*(t/{slide_dur})\\,{margin})"
                )
            elif "right" in position:
                x_expr = (
                    f"if(lt(t\\,{slide_dur})\\,"
                    f"W-(w+{margin})*(t/{slide_dur})\\,W-w-{margin})"
                )
            elif position == "top-center":
                y_expr = (
                    f"if(lt(t\\,{slide_dur})\\,"
                    f"-h+({margin}+h)*(t/{slide_dur})\\,{margin})"
                )
            elif position == "bottom-center":
                y_expr = (
                    f"if(lt(t\\,{slide_dur})\\,"
                    f"H-(h+{margin})*(t/{slide_dur})\\,H-h-{margin})"
                )
            else:  # center → 淡入代替
                wm_filters.append(f"fade=t=in:st=0:d={slide_dur}:alpha=1")

        wm_chain = ",".join(wm_filters)

        filter_complex = f"[1:v]{wm_chain}[wm];[0:v][wm]overlay={x_expr}:{y_expr}[vout]"

        output_path = os.path.join(tmp_dir, "with_wm.mp4")

        run_ffmpeg([
            '-i', video_path,
            '-loop', '1', '-framerate', str(fps), '-i', self.watermark["path"],
            '-filter_complex', filter_complex,
            '-map', '[vout]',
            '-c:v', 'libx264', '-preset', 'fast',
            '-pix_fmt', 'yuv420p',
            '-t', f'{total_duration:.3f}',
            '-threads', '1',
            output_path
        ])

        return output_path

    # =================================================================
    # Phase 3: BGM 混音
    # =================================================================

    def _mix_bgm(self, video_path, output_path):
        music_cfg = self.config.get("music", {})
        volume = self.bgm_volume if hasattr(self, 'bgm_volume') else music_cfg.get("volume", 0.5)
        fade_in = music_cfg.get("fade_in", 0.5)
        fade_out = music_cfg.get("fade_out", 1.5)

        video_dur = get_duration(video_path)
        af = (f"volume={volume},"
              f"afade=t=in:st=0:d={fade_in},"
              f"afade=t=out:st={max(0, video_dur - fade_out):.1f}:d={fade_out}")

        run_ffmpeg([
            '-i', video_path, '-i', self.bgm_path,
            '-map', '0:v:0', '-map', '1:a:0',
            '-c:v', 'copy',
            '-af', af,
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            output_path
        ])

    # =================================================================
    # Phase 3: AI 配音生成 (edge-tts)
    # =================================================================

    def _generate_narration(self, tmp_dir):
        """
        使用 edge-tts 将字幕文本合成为配音音频。
        字幕文本拼接为一段连续的旁白，语速可调。
        """
        try:
            import edge_tts
        except ImportError:
            sys.stderr.write("[narration] edge-tts not installed, skipping\n")
            sys.stderr.flush()
            return None

        # 拼接字幕为旁白脚本
        narration_text = "。".join(self.subtitles)
        if not narration_text.strip():
            return None

        # 语速转换：1.0 -> +0%, 0.8 -> -20%, 1.2 -> +20%
        rate_percent = int(round((self.narration_rate - 1.0) * 100))
        rate_str = f"{rate_percent:+d}%"

        output_path = os.path.join(tmp_dir, "narration.mp3")

        sys.stderr.write(
            f"[narration] voice={self.narration_voice}, rate={rate_str}, "
            f"text_len={len(narration_text)}\n"
        )
        sys.stderr.flush()

        async def _gen():
            communicate = edge_tts.Communicate(
                narration_text, self.narration_voice, rate=rate_str
            )
            await communicate.save(output_path)

        try:
            # Windows 上 ProactorEventLoop 在非主线程中会报 [Errno 22]，
            # 必须改用 SelectorEventLoop
            if sys.platform == 'win32':
                loop = asyncio.SelectorEventLoop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(_gen())
                finally:
                    loop.close()
            else:
                asyncio.run(_gen())

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path
            sys.stderr.write("[narration] generated file is empty\n")
            sys.stderr.flush()
            return None
        except Exception as e:
            import traceback
            sys.stderr.write(f"[narration] edge-tts failed: {e}\n")
            sys.stderr.write(traceback.format_exc())
            sys.stderr.flush()
            return None

    # =================================================================
    # Phase 4: 混音 — 配音 + BGM / 配音-only
    # =================================================================

    def _mix_narration_bgm(self, video_path, narration_path, output_path):
        """
        混合配音和背景音乐：
        - 配音音量：用户可调（默认 100%）
        - BGM 音量：用户可调（默认 30%）
        """
        music_cfg = self.config.get("music", {})
        fade_in = music_cfg.get("fade_in", 0.5)
        fade_out = music_cfg.get("fade_out", 1.5)

        video_dur = get_duration(video_path)

        # BGM 音频滤镜：降音量 + 淡入淡出
        bgm_af = (
            f"volume={self.bgm_volume},"
            f"afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={max(0, video_dur - fade_out):.1f}:d={fade_out}"
        )

        # filter_complex: 配音[1:a] + BGM[2:a] 混合
        filter_complex = (
            f"[1:a]volume={self.narration_volume}[nav];"
            f"[2:a]{bgm_af}[bgm];"
            f"[nav][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )

        run_ffmpeg([
            '-i', video_path,
            '-i', narration_path,
            '-i', self.bgm_path,
            '-filter_complex', filter_complex,
            '-map', '0:v:0', '-map', '[aout]',
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            output_path
        ])

    def _mix_narration_only(self, video_path, narration_path, output_path):
        """仅混入配音，无 BGM"""
        run_ffmpeg([
            '-i', video_path,
            '-i', narration_path,
            '-map', '0:v:0', '-map', '1:a:0',
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            output_path
        ])

    # =================================================================
    # 辅助：标题/片尾卡片
    # =================================================================

    def _make_card(self, output_path, text, cfg_section, target_w, target_h, fps):
        cfg = self.config.get(cfg_section, {})
        duration = cfg.get("duration", 2.5)
        font_size = cfg.get("font_size", 48)
        font_path = cfg.get("font", FONT_REGULAR if cfg_section == "ending" else FONT_BOLD)
        bg_color = cfg.get("background_color", [20, 20, 30])
        fade_dur = cfg.get("fade_duration", 0.6)

        png_path = output_path.replace('.mp4', '_text.png')
        make_text_png(text, target_w, target_h, font_path, font_size, "center", png_path)

        bg_hex = f"0x{bg_color[0]:02x}{bg_color[1]:02x}{bg_color[2]:02x}"
        fade_out_st = max(0, duration - fade_dur)
        vf = (f"[0:v][1:v]overlay=0:0,format=yuv420p,"
              f"fade=t=in:st=0:d={fade_dur},"
              f"fade=t=out:st={fade_out_st:.1f}:d={fade_dur}")

        run_ffmpeg([
            '-f', 'lavfi', '-i',
            f'color=c={bg_hex}:s={target_w}x{target_h}:d={duration}:r={fps}',
            '-i', png_path,
            '-filter_complex', vf,
            '-c:v', 'libx264', '-preset', 'fast',
            '-r', str(fps),
            '-t', str(duration),
            '-threads', '1',
            output_path
        ])
        safe_remove(png_path)

    def _concatenate(self, clips, durations, output_path, transition_dur):
        """
        xfade 拼接 —— 采用二叉两两合并（递归），避免把 N 个输入一次性塞进
        一条超长 filtergraph 导致 FFmpeg 缓冲所有帧而内存爆炸（OOM / "Cannot
        allocate memory"）。每次 xfade 只有 2 个输入，内存有界；合并层级为
        log2(N)，总合并次数 N-1。每段合并后用实测时长计算下一层 offset，
        同时消除时长漂移累积。
        """
        if len(clips) == 1:
            run_ffmpeg(['-i', clips[0], '-c', 'copy', output_path])
            return

        tmp = getattr(self, '_tmp_dir', tempfile.mkdtemp(prefix="xfade_"))
        _counter = {'n': 0}

        def _xfade2(a_path, a_dur, b_path, b_dur, out_path):
            """两段交叉溶解；返回合并后视频的实际时长"""
            # 保护：任一段短于转场则不溶解，退化为硬拼接（同参数可直接 concat）
            if a_dur < transition_dur or b_dur < transition_dur:
                run_ffmpeg([
                    '-i', a_path, '-i', b_path,
                    '-filter_complex',
                    f"[0:v][1:v]concat=n=2:v=1:a=0[vout]",
                    '-map', '[vout]',
                    '-c:v', 'libx264', '-preset', 'fast',
                    '-pix_fmt', 'yuv420p', '-threads', '1',
                    out_path
                ])
                return get_duration(out_path)

            offset = max(0.0, a_dur - transition_dur)
            run_ffmpeg([
                '-i', a_path, '-i', b_path,
                '-filter_complex',
                f"[0:v][1:v]xfade=transition=fade:"
                f"duration={transition_dur}:offset={offset:.3f}[vout]",
                '-map', '[vout]',
                '-c:v', 'libx264', '-preset', 'fast',
                '-pix_fmt', 'yuv420p', '-threads', '1',
                out_path
            ])
            return get_duration(out_path)

        def _merge(paths, durs):
            """递归二叉合并，返回 (最终路径, 实际时长)"""
            if len(paths) == 1:
                return paths[0], durs[0]
            if len(paths) == 2:
                out = os.path.join(tmp, f"xf_{_counter['n']:04d}.mp4")
                _counter['n'] += 1
                d = _xfade2(paths[0], durs[0], paths[1], durs[1], out)
                safe_remove(paths[0])
                safe_remove(paths[1])
                return out, d
            mid = len(paths) // 2
            lp, ld = _merge(paths[:mid], durs[:mid])
            rp, rd = _merge(paths[mid:], durs[mid:])
            out = os.path.join(tmp, f"xf_{_counter['n']:04d}.mp4")
            _counter['n'] += 1
            d = _xfade2(lp, ld, rp, rd, out)
            safe_remove(lp)
            safe_remove(rp)
            return out, d

        final_path, _ = _merge(list(clips), list(durations))
        if final_path != output_path:
            run_ffmpeg(['-i', final_path, '-c', 'copy', output_path])
            safe_remove(final_path)
