# 视频剪辑工坊

投素材 → 选模板 → 一键出片。本地/云端均可运行的自动视频剪辑 Web 应用。

输出 9:16 竖屏视频（1080x1920），适配抖音 / 视频号 / 小红书。

## 功能

- **素材管理**：拖拽上传视频/图片/音频，排序、删除、BGM 自动识别
- **风格模板**：预设模板 + 自定义效果关键词 + 上传参考视频自动提取模板
- **我的模板**：提取的模板自动保存，支持重命名/删除
- **字幕系统**：独立字幕轨与画面解绑，6 种内置字体 + 自定义字体上传 + 字号调节
- **AI 配音**：edge-tts 5 种音色，语速/配音音量/BGM 音量独立调节
- **水印**：上传图片水印，九宫格定位，淡入淡出/滑入/呼吸动画，大小透明度可调
- **时长控制**：预设时长或自定义，智能截取/整体变速/手动裁剪三种适配策略
- **出片发布**：在线预览、MP4 下载、发布文案生成、纯视频/SRT 字幕单独导出

## 本地运行（Windows）

```bash
pip install -r requirements.txt
python app.py
```

访问 http://localhost:5000

或直接双击 `start_webapp.bat`（带崩溃自动重启）。

## Docker 部署

```bash
docker build -t video-editor .
docker run -p 5000:5000 video-editor
```

## 部署到 Render / Railway

1. 将本目录推送到 GitHub 仓库
2. 在 Render.com / Railway 新建 Web Service，选择该仓库
3. 平台自动识别 Dockerfile 构建
4. 注意：上传的文件在免费套餐的重启后会丢失（临时文件系统）

## 技术栈

- 后端：Flask + FFmpeg（imageio-ffmpeg）+ Pillow + edge-tts
- 前端：原生 HTML/CSS/JS，黑白灰极简风格
- 渲染管线：视频轨 → 字幕轨 → 水印 → AI 配音 → 混音
