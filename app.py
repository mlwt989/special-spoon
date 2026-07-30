#!/usr/bin/env python3
"""
自动视频剪辑 Web 应用 - Flask 后端
启动: python app.py
访问: http://localhost:5000
"""

import os
import sys
import json
import uuid
import shutil
import threading
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory

# 添加父目录到 path 以便 import renderer
sys.path.insert(0, str(Path(__file__).parent))
from renderer import VideoRenderer, get_file_type, get_duration

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
PRESETS_DIR = BASE_DIR / "presets"
STATIC_DIR = BASE_DIR / "static"
FONTS_DIR = BASE_DIR / "fonts"
WATERMARK_DIR = BASE_DIR / "watermarks"

for d in [UPLOAD_DIR, OUTPUT_DIR, FONTS_DIR, WATERMARK_DIR]:
    d.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(STATIC_DIR))
app.config['MAX_CONTENT_LENGTH'] = 2048 * 1024 * 1024  # 2GB

# 全局任务状态
tasks = {}


@app.route('/')
def index():
    return send_from_directory(str(STATIC_DIR), 'index.html')


@app.route('/api/templates')
def get_templates():
    templates = []
    for f in sorted(PRESETS_DIR.glob('*.json')):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                cfg = json.load(fh)
            templates.append({
                "id": f.stem,
                "name": cfg.get("name", f.stem),
                "description": cfg.get("description", ""),
                "aspect": f'{cfg["output"]["width"]}:{cfg["output"]["height"]}',
                "config": cfg
            })
        except Exception:
            pass
    return jsonify(templates)


@app.route('/api/upload', methods=['POST'])
def upload_files():
    if 'files' not in request.files:
        return jsonify({"error": "没有文件"}), 400

    session_id = request.form.get('session_id', str(uuid.uuid4())[:8])
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(exist_ok=True)

    uploaded = []
    for f in request.files.getlist('files'):
        if not f.filename:
            continue
        ftype = get_file_type(f.filename)
        if ftype is None:
            continue
        save_path = session_dir / f.filename
        f.save(str(save_path))
        uploaded.append({
            "name": f.filename,
            "path": str(save_path),
            "type": ftype,
            "size": save_path.stat().st_size
        })

    # 按文件名排序
    uploaded.sort(key=lambda x: x["name"])

    return jsonify({
        "session_id": session_id,
        "files": uploaded
    })


@app.route('/api/render', methods=['POST'])
def start_render():
    data = request.json
    session_id = data.get('session_id')
    template_id = data.get('template_id')
    materials = data.get('materials', [])
    title = data.get('title', '')
    subtitles = data.get('subtitles', [])
    ending = data.get('ending', '')
    bgm_name = data.get('bgm_name', '')
    custom_effect = data.get('custom_effect', '')
    target_duration = data.get('target_duration', 0)  # 0 = 自动
    adapt_strategy = data.get('adapt_strategy', 'smart')
    subtitle_font = data.get('subtitle_font', '')
    subtitle_font_size = data.get('subtitle_font_size', 0)  # 0 = 用模板默认
    narration_enabled = data.get('narration_enabled', False)
    narration_voice = data.get('narration_voice', 'zh-CN-XiaoxiaoNeural')
    narration_rate = data.get('narration_rate', 1.0)
    narration_volume = data.get('narration_volume', 1.0)
    bgm_volume = data.get('bgm_volume', 0.3)
    watermark = data.get('watermark')  # dict or None

    if not materials:
        return jsonify({"error": "没有素材"}), 400

    # 加载模板
    preset_path = PRESETS_DIR / f'{template_id}.json'
    if not preset_path.exists():
        return jsonify({"error": f"模板不存在: {template_id}"}), 400

    with open(preset_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # BGM 路径
    bgm_path = None
    if bgm_name:
        bgm_candidate = UPLOAD_DIR / session_id / bgm_name
        if bgm_candidate.exists():
            bgm_path = str(bgm_candidate)

    # 字幕处理
    sub_list = [s.strip() for s in subtitles if s and s.strip()]

    # 输出路径
    task_id = str(uuid.uuid4())[:8]
    output_path = str(OUTPUT_DIR / f'output_{task_id}.mp4')

    # 初始化任务状态
    tasks[task_id] = {
        "status": "rendering",
        "progress": 0,
        "message": "准备中...",
        "output_path": output_path,
        "error": None,
        "subtitles": sub_list,
        "duration": 0
    }

    # 准备素材列表
    mat_list = []
    for m in materials:
        mat_list.append({
            "path": m["path"],
            "type": m["type"],
            "name": m.get("name", "")
        })

    def progress_cb(percent, message):
        tasks[task_id]["progress"] = percent
        tasks[task_id]["message"] = message

    def render_thread():
        try:
            renderer = VideoRenderer(
                materials=mat_list,
                config=config,
                output_path=output_path,
                bgm_path=bgm_path,
                title=title if title else None,
                subtitles=sub_list,
                ending=ending if ending else None,
                custom_effect=custom_effect if custom_effect else None,
                target_duration=target_duration if target_duration > 0 else None,
                adapt_strategy=adapt_strategy,
                subtitle_font=subtitle_font if subtitle_font else None,
                subtitle_font_size=subtitle_font_size if subtitle_font_size > 0 else None,
                narration_enabled=narration_enabled,
                narration_voice=narration_voice,
                narration_rate=narration_rate,
                narration_volume=narration_volume,
                bgm_volume=bgm_volume,
                watermark=watermark,
                progress_callback=progress_cb
            )
            renderer.render()
            tasks[task_id]["status"] = "done"
            tasks[task_id]["progress"] = 100

            # 获取视频时长
            try:
                dur = get_duration(output_path)
                tasks[task_id]["duration"] = round(dur, 1)
            except Exception:
                pass

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            sys.stderr.write(f"\n[RENDER ERROR] Task {task_id}\n{tb}\n")
            sys.stderr.flush()
            tasks[task_id]["status"] = "error"
            # 提供更友好的错误信息
            err_str = str(e)
            if 'Errno 22' in err_str or 'Invalid argument' in err_str:
                tasks[task_id]["error"] = "系统资源问题（管道创建失败），请关闭其他程序后重试"
            else:
                tasks[task_id]["error"] = err_str

    thread = threading.Thread(target=render_thread, daemon=True)
    thread.start()

    return jsonify({"task_id": task_id})


@app.route('/api/status/<task_id>')
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(tasks[task_id])


@app.route('/api/output/<task_id>')
def download_output(task_id):
    if task_id not in tasks:
        return jsonify({"error": "任务不存在"}), 404
    task = tasks[task_id]
    if task["status"] != "done":
        return jsonify({"error": "渲染未完成"}), 400
    return send_file(task["output_path"], as_attachment=False,
                     download_name=f'video_{task_id}.mp4')


@app.route('/api/download/<task_id>')
def download_file(task_id):
    if task_id not in tasks:
        return jsonify({"error": "任务不存在"}), 404
    task = tasks[task_id]
    if task["status"] != "done":
        return jsonify({"error": "渲染未完成"}), 400
    return send_file(task["output_path"], as_attachment=True,
                     download_name=f'video_{task_id}.mp4')


def analyze_reference_video(video_path):
    """
    分析参考视频，提取剪辑模板参数：
    - 时长、分辨率、帧率、宽高比
    - 场景切换点（FFmpeg scene detection）→ 平均镜头时长 → 剪辑节奏
    - 转场风格推断
    返回模板配置 dict
    """
    import re

    # 1. 基本信息：时长、分辨率、帧率
    # 用 ffprobe 快速读取头部，大文件也不会卡
    try:
        probe = subprocess.run(
            [FFMPEG, '-analyzeduration', '0', '-probesize', '5000000',
             '-i', video_path],
            capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        sys.stderr.write(f"[analyze] probe failed: {e}\n")
        sys.stderr.flush()
        raise RuntimeError(f"无法读取视频信息（文件可能损坏或格式不支持）")
    info = probe.stderr

    duration = 0.0
    width = 1080
    height = 1920
    fps = 30

    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', info)
    if m:
        h, mi, s = m.groups()
        duration = int(h) * 3600 + int(mi) * 60 + float(s)

    m = re.search(r',\s*(\d{3,4})x(\d{3,4})', info)
    if m:
        width = int(m.group(1))
        height = int(m.group(2))

    m = re.search(r'(\d+(?:\.\d+)?)\s*fps', info)
    if m:
        fps = int(float(m.group(1)))

    # 宽高比判断
    ratio = width / height if height else 0.5625
    if ratio > 1.2:
        aspect_label = "16:9"
        out_w, out_h = 1920, 1080
    elif ratio < 0.7:
        aspect_label = "9:16"
        out_w, out_h = 1080, 1920
    else:
        aspect_label = "1:1"
        out_w, out_h = 1080, 1080

    # 2. 场景检测：用 FFmpeg select 滤镜检测场景切换点
    # 策略：降低帧率到 5fps 减少解码量 + 只分析前 60 秒 + 单线程
    analyze_dur = min(duration, 60) if duration > 0 else 30
    scene_cmd = [
        FFMPEG, '-y', '-hide_banner',
        '-analyzeduration', '0', '-probesize', '5000000',
        '-i', video_path,
        '-t', str(analyze_dur),
        '-an',
        '-vf', "fps=5,select='gt(scene,0.3)',showinfo",
        '-f', 'null', '-',
        '-threads', '1'
    ]

    try:
        scene_result = subprocess.run(
            scene_cmd,
            capture_output=True, text=True, timeout=300
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write("[analyze] scene detection timed out, using defaults\n")
        sys.stderr.flush()
        scene_result = None
    except OSError:
        try:
            scene_result = subprocess.run(
                scene_cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, timeout=300
            )
        except Exception:
            scene_result = None

    # 解析 showinfo 输出，提取 pts_time
    scene_times = []
    if scene_result and scene_result.stderr:
        for line in scene_result.stderr.split('\n'):
            m = re.search(r'pts_time:(\d+\.?\d*)', line)
            if m:
                scene_times.append(float(m.group(1)))

    # 第一个场景点视为第一镜头的结束
    # 计算镜头时长
    if len(scene_times) >= 2:
        shot_durations = []
        prev = 0.0
        for t in scene_times:
            shot_durations.append(t - prev)
            prev = t
        # 最后一个镜头到分析结束
        shot_durations.append(analyze_dur - prev)

        avg_shot = sum(shot_durations) / len(shot_durations)
    elif len(scene_times) == 1:
        avg_shot = (scene_times[0] + (analyze_dur - scene_times[0])) / 2
    else:
        # 没有检测到场景切换，整段是一个镜头
        avg_shot = analyze_dur if analyze_dur > 0 else 6.0

    # 3. 根据平均镜头时长推断剪辑节奏
    avg_shot = max(1.0, min(15.0, avg_shot))

    if avg_shot < 2.5:
        pacing = "快节奏"
        clip_min, clip_max = 2, 4
        transition_dur = 0.3
    elif avg_shot < 5.0:
        pacing = "中等节奏"
        clip_min, clip_max = 3, 5
        transition_dur = 0.5
    else:
        pacing = "慢节奏"
        clip_min, clip_max = 5, 8
        transition_dur = 0.8

    # 4. 构建模板配置
    template_config = {
        "name": f"参考视频模板",
        "description": f"从参考视频提取 · {pacing} · 平均镜头{avg_shot:.1f}s · {aspect_label}",
        "output": {
            "width": out_w,
            "height": out_h,
            "fps": min(fps, 30),
            "format": "mp4",
            "codec": "h264",
            "bitrate": "8M"
        },
        "video_track": {
            "clip_duration_min": clip_min,
            "clip_duration_max": clip_max,
            "transition_type": "fade",
            "transition_duration": transition_dur
        },
        "subtitle_track": {
            "enabled": True,
            "font": "C:/Windows/Fonts/msyh.ttc",
            "font_size": 56,
            "stroke_width": 3,
            "max_width_ratio": 0.85
        },
        "title": {
            "enabled": True,
            "duration": 2.5,
            "font_size": 52,
            "font": "C:/Windows/Fonts/msyhbd.ttc",
            "background_color": [20, 20, 30],
            "fade_duration": 0.6
        },
        "ending": {
            "enabled": False,
            "duration": 2.5,
            "font_size": 42,
            "font": "C:/Windows/Fonts/msyh.ttc",
            "background_color": [20, 20, 30],
            "fade_duration": 0.6
        },
        "music": {
            "enabled": False,
            "volume": 0.5,
            "fade_in": 0.5,
            "fade_out": 1.5
        },
        "color_grade": {
            "saturation": 1.0,
            "brightness": 0.0,
            "contrast": 1.0,
            "gamma": 1.0
        }
    }

    analysis_summary = {
        "duration": round(duration, 1),
        "resolution": f"{width}x{height}",
        "fps": fps,
        "aspect": aspect_label,
        "scene_count": len(scene_times),
        "avg_shot_duration": round(avg_shot, 1),
        "pacing": pacing,
        "clip_range": f"{clip_min}-{clip_max}s",
        "transition": f"fade {transition_dur}s"
    }

    return template_config, analysis_summary


FFMPEG = None
def _get_ffmpeg():
    global FFMPEG
    if FFMPEG is None:
        import imageio_ffmpeg
        FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    return FFMPEG


@app.route('/api/analyze-video', methods=['POST'])
def analyze_video():
    """上传参考视频，分析并提取剪辑模板"""
    global FFMPEG
    if FFMPEG is None:
        _get_ffmpeg()

    if 'file' not in request.files:
        return jsonify({"error": "没有文件"}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({"error": "没有文件名"}), 400

    # 保存到临时文件
    import tempfile
    tmp_path = os.path.join(tempfile.gettempdir(), f"ref_{uuid.uuid4().hex[:8]}_{f.filename}")
    f.save(tmp_path)

    try:
        template_config, summary = analyze_reference_video(tmp_path)
        return jsonify({
            "config": template_config,
            "analysis": summary
        })
    except Exception as e:
        return jsonify({"error": f"分析失败: {str(e)}"}), 500
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@app.route('/api/save-template', methods=['POST'])
def save_template():
    """保存自定义模板到 presets/ 目录"""
    data = request.json
    name = data.get('name', '自定义模板')
    config = data.get('config')

    if not config:
        return jsonify({"error": "没有配置"}), 400

    # 生成模板 ID：中文转拼音或用时间戳
    import time
    template_id = f"custom_{int(time.time())}"

    # 确保 name 写入 config
    config['name'] = name

    preset_path = PRESETS_DIR / f'{template_id}.json'
    with open(preset_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    aspect = f'{config["output"]["width"]}:{config["output"]["height"]}'

    return jsonify({
        "id": template_id,
        "name": name,
        "description": config.get("description", ""),
        "aspect": aspect,
        "config": config
    })


@app.route('/api/upload-watermark', methods=['POST'])
def upload_watermark():
    """上传水印图片"""
    if 'watermark' not in request.files:
        return jsonify({"error": "没有文件"}), 400

    f = request.files['watermark']
    if not f.filename:
        return jsonify({"error": "没有文件名"}), 400

    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ('png', 'jpg', 'jpeg', 'webp'):
        return jsonify({"error": "不支持的图片格式"}), 400

    import time
    safe_name = f"wm_{int(time.time())}.{ext}"
    save_path = WATERMARK_DIR / safe_name
    f.save(str(save_path))

    return jsonify({
        "path": str(save_path),
        "url": f"/api/watermark-preview/{safe_name}",
        "name": f.filename
    })


@app.route('/api/watermark-preview/<filename>')
def watermark_preview(filename):
    """水印预览图"""
    return send_from_directory(str(WATERMARK_DIR), filename)


@app.route('/api/upload-font', methods=['POST'])
def upload_font():
    """上传自定义字体文件"""
    if 'font' not in request.files:
        return jsonify({"error": "没有文件"}), 400

    f = request.files['font']
    if not f.filename:
        return jsonify({"error": "没有文件名"}), 400

    # 验证扩展名
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ('ttf', 'ttc', 'otf', 'woff', 'woff2'):
        return jsonify({"error": "不支持的字体格式，请上传 .ttf / .ttc / .otf"}), 400

    # 保存到 fonts/ 目录，用原名+时间戳避免冲突
    import time
    safe_name = f"{Path(f.filename).stem}_{int(time.time())}.{ext}"
    save_path = FONTS_DIR / safe_name
    f.save(str(save_path))

    return jsonify({
        "name": Path(f.filename).stem,
        "path": str(save_path),
        "original_name": f.filename
    })


@app.route('/api/delete-font', methods=['POST'])
def delete_font():
    """删除自定义字体文件"""
    data = request.json
    font_path = data.get('path', '')
    if not font_path:
        return jsonify({"error": "没有路径"}), 400

    # 安全检查：只允许删除 fonts/ 目录下的文件
    p = Path(font_path)
    if p.parent != FONTS_DIR:
        return jsonify({"error": "非法路径"}), 403

    if p.exists():
        p.unlink()

    return jsonify({"ok": True})


@app.route('/api/rename-template', methods=['POST'])
def rename_template():
    """重命名自定义模板"""
    data = request.json
    template_id = data.get('id', '')
    new_name = data.get('name', '').strip()

    if not template_id or not new_name:
        return jsonify({"error": "缺少参数"}), 400

    preset_path = PRESETS_DIR / f'{template_id}.json'
    if not preset_path.exists():
        return jsonify({"error": "模板不存在"}), 404

    with open(preset_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    config['name'] = new_name

    with open(preset_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True, "name": new_name})


@app.route('/api/delete-template', methods=['POST'])
def delete_template():
    """删除自定义模板"""
    data = request.json
    template_id = data.get('id', '')

    if not template_id:
        return jsonify({"error": "缺少模板ID"}), 400

    # 只允许删除 custom_ 前缀的模板
    if not template_id.startswith('custom_'):
        return jsonify({"error": "预设模板不可删除"}), 403

    preset_path = PRESETS_DIR / f'{template_id}.json'
    if not preset_path.exists():
        return jsonify({"error": "模板不存在"}), 404

    preset_path.unlink()
    return jsonify({"ok": True})


@app.route('/api/export-video-only/<task_id>')
def export_video_only(task_id):
    """导出纯视频（无字幕无音频）"""
    if task_id not in tasks:
        return jsonify({"error": "任务不存在"}), 404

    task = tasks[task_id]
    if task["status"] != "done":
        return jsonify({"error": "渲染未完成"}), 400

    # 用 FFmpeg 提取纯视频流（去掉音频）
    output_path = str(OUTPUT_DIR / f'video_only_{task_id}.mp4')
    try:
        run_ffmpeg([
            '-i', task["output_path"],
            '-map', '0:v:0',
            '-c:v', 'copy',
            '-an',
            output_path
        ])
        return send_file(output_path, as_attachment=True,
                         download_name=f'video_only_{task_id}.mp4')
    except Exception as e:
        return jsonify({"error": f"导出失败: {str(e)}"}), 500


@app.route('/api/export-subtitles/<task_id>')
def export_subtitles(task_id):
    """导出 SRT 字幕文件"""
    if task_id not in tasks:
        return jsonify({"error": "任务不存在"}), 404

    task = tasks[task_id]
    if task["status"] != "done":
        return jsonify({"error": "渲染未完成"}), 400

    # 从任务信息中提取字幕和时间
    subtitles = task.get("subtitles", [])
    total_dur = task.get("duration", 60)

    if not subtitles:
        return jsonify({"error": "没有字幕数据"}), 400

    # 生成 SRT
    srt_path = str(OUTPUT_DIR / f'subtitles_{task_id}.srt')
    slot_dur = total_dur / len(subtitles)

    def fmt_time(seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(srt_path, 'w', encoding='utf-8') as f:
        for i, text in enumerate(subtitles):
            start = i * slot_dur
            end = (i + 1) * slot_dur
            f.write(f"{i + 1}\n")
            f.write(f"{fmt_time(start)} --> {fmt_time(end)}\n")
            f.write(f"{text}\n\n")

    return send_file(srt_path, as_attachment=True,
                     download_name=f'subtitles_{task_id}.srt')


@app.route('/api/cleanup/<session_id>', methods=['POST'])
def cleanup_session(session_id):
    session_dir = UPLOAD_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
    return jsonify({"ok": True})


if __name__ == '__main__':
    print("=" * 50)
    print("  自动视频剪辑器 Web 应用")
    print("  访问: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=False)
