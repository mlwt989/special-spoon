// === 状态 ===
const state = {
  sessionId: null,
  materials: [],
  templates: [],
  selectedTemplate: null,
  templateTab: 'preset',  // preset | custom
  bgmFile: null,
  subtitles: [],
  renderTaskId: null,
  pollTimer: null,
  // 自定义效果
  customEffect: '',
  // 视频时长（0 = 自动）
  targetDuration: 0,
  // 素材适配策略: smart | speed | manual
  adaptStrategy: 'smart',
  // 字幕字体
  subtitleFont: 'C:/Windows/Fonts/msyh.ttc',
  // 字幕字号
  subtitleFontSize: 56,
  // 用户上传的自定义字体
  customFonts: [],
  // 参考视频分析结果
  refAnalysis: null,
  refTemplateConfig: null,
  // AI 配音
  narrationEnabled: false,
  narrationVoice: 'zh-CN-XiaoxiaoNeural',
  narrationRate: 1.0,
  narrationVolume: 1.0,
  bgmVolume: 0.3,
  // 水印
  watermarkPath: null,
  watermarkName: null,
  watermarkPos: 'bottom-right',
  watermarkAnim: 'none',
  watermarkSize: 15,
  watermarkOpacity: 90,
  // 最近一次渲染失败的技术详情（供开发者复制到剪贴板排查）
  lastErrorDetail: null
};

// === 初始化 ===
async function init() {
  await loadTemplates();
  setupDropZone();
  setupRefUpload();
  setupCustomEffect();
  setupNarration();
  setupDuration();
  setupFontUpload();
  setupFontSize();
  setupWatermark();
}

// === 模板加载 ===
async function loadTemplates() {
  try {
    const res = await fetch('/api/templates');
    state.templates = await res.json();
    renderTemplates();
  } catch (e) {
    document.getElementById('templateList').innerHTML =
      '<div class="field-empty">模板加载失败</div>';
  }
}

// === 模板选项卡 ===
function switchTemplateTab(tab) {
  state.templateTab = tab;
  document.querySelectorAll('.template-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tab);
  });
  renderTemplates();
}

function renderTemplates() {
  const container = document.getElementById('templateList');

  // 按选项卡过滤：预设模板 = 无 custom_ 前缀；我的模板 = custom_ 前缀
  const filtered = state.templateTab === 'preset'
    ? state.templates.filter(t => !t.id.startsWith('custom_'))
    : state.templates.filter(t => t.id.startsWith('custom_'));

  if (!filtered.length) {
    const msg = state.templateTab === 'preset' ? '没有可用模板' : '还没有自定义模板，上传参考视频自动生成';
    container.innerHTML = `<div class="field-empty">${msg}</div>`;
    return;
  }

  container.innerHTML = filtered.map(t => `
    <div class="template-card ${state.selectedTemplate === t.id ? 'selected' : ''}"
         onclick="selectTemplate('${t.id}')">
      <div class="template-name">${escapeHtml(t.name)}</div>
      <div class="template-desc">${escapeHtml(t.description)}</div>
      <span class="template-aspect">${t.aspect}</span>
      ${t.id.startsWith('custom_') ? `
        <div class="template-card-actions" onclick="event.stopPropagation()">
          <button class="template-action-btn" onclick="renameTemplate('${t.id}', '${escapeJsString(t.name)}')">重命名</button>
          <button class="template-action-btn danger" onclick="deleteTemplate('${t.id}', '${escapeJsString(t.name)}')">删除</button>
        </div>
      ` : ''}
    </div>
  `).join('');
}

function selectTemplate(id) {
  state.selectedTemplate = id;
  renderTemplates();
  updateRenderBtn();
}

// === 模板重命名 ===
function renameTemplate(id, currentName) {
  const card = document.querySelector(`.template-card[onclick*="${id}"]`);
  if (!card) return;

  const nameEl = card.querySelector('.template-name');
  const oldHtml = nameEl.innerHTML;

  nameEl.innerHTML = `<input type="text" class="template-rename-input" value="${currentName}" onclick="event.stopPropagation()">`;
  const input = nameEl.querySelector('input');
  input.focus();
  input.select();

  async function save() {
    const newName = input.value.trim();
    if (!newName || newName === currentName) {
      nameEl.innerHTML = oldHtml;
      return;
    }
    try {
      const res = await fetch('/api/rename-template', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, name: newName })
      });
      const data = await res.json();
      if (data.error) {
        showToast('重命名失败: ' + data.error);
        nameEl.innerHTML = oldHtml;
      } else {
        // 更新本地状态
        const tpl = state.templates.find(t => t.id === id);
        if (tpl) tpl.name = newName;
        nameEl.textContent = newName;
        showToast('已重命名');
      }
    } catch (e) {
      showToast('重命名失败: ' + e.message);
      nameEl.innerHTML = oldHtml;
    }
  }

  input.addEventListener('blur', save);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape') { input.value = currentName; input.blur(); }
  });
}

// === 模板删除 ===
async function deleteTemplate(id, name) {
  if (!confirm(`确定删除模板"${name}"吗？`)) return;

  try {
    const res = await fetch('/api/delete-template', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id })
    });
    const data = await res.json();
    if (data.error) {
      showToast('删除失败: ' + data.error);
      return;
    }

    state.templates = state.templates.filter(t => t.id !== id);
    if (state.selectedTemplate === id) {
      state.selectedTemplate = null;
      updateRenderBtn();
    }
    renderTemplates();
    showToast('模板已删除');
  } catch (e) {
    showToast('删除失败: ' + e.message);
  }
}

// === 自定义效果 ===
function setupCustomEffect() {
  const input = document.getElementById('customEffectInput');
  input.addEventListener('input', () => {
    state.customEffect = input.value.trim();
  });
}

function addEffectTag(tag) {
  const input = document.getElementById('customEffectInput');
  const current = input.value.trim();
  if (current.includes(tag)) return;
  input.value = current ? `${current}、${tag}` : tag;
  state.customEffect = input.value.trim();
}

// === 字幕字体选择 ===
function selectFont(btn) {
  document.querySelectorAll('.font-btn').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
  state.subtitleFont = btn.dataset.font;
}

// === 字幕字号 ===
function setupFontSize() {
  const slider = document.getElementById('fontSize');
  const value = document.getElementById('fontSizeValue');
  slider.addEventListener('input', () => {
    state.subtitleFontSize = parseInt(slider.value);
    value.textContent = state.subtitleFontSize;
  });
}

// === 自定义字体上传 ===
function setupFontUpload() {
  const input = document.getElementById('fontFileInput');
  input.addEventListener('change', async (e) => {
    if (!e.target.files.length) return;
    const file = e.target.files[0];
    input.value = '';

    // 验证格式
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['ttf', 'ttc', 'otf', 'woff', 'woff2'].includes(ext)) {
      showToast('请上传 .ttf / .ttc / .otf 字体文件');
      return;
    }

    // 上传
    const formData = new FormData();
    formData.append('font', file);

    try {
      const res = await fetch('/api/upload-font', { method: 'POST', body: formData });
      const data = await res.json();

      if (data.error) {
        showToast('上传失败: ' + data.error);
        return;
      }

      // 添加到自定义字体列表
      state.customFonts.push({
        name: data.name,
        path: data.path
      });
      renderCustomFonts();

      // 自动选中新上传的字体
      state.subtitleFont = data.path;
      document.querySelectorAll('.font-btn').forEach(b => b.classList.remove('selected'));
      showToast(`字体 "${data.name}" 已上传`);

    } catch (e) {
      showToast('上传失败: ' + e.message);
    }
  });
}

function renderCustomFonts() {
  const container = document.getElementById('customFontList');
  if (!state.customFonts.length) {
    container.style.display = 'none';
    return;
  }

  container.style.display = 'flex';
  container.innerHTML = state.customFonts.map((f, i) => `
    <button class="font-btn ${state.subtitleFont === f.path ? 'selected' : ''}"
            data-font="${f.path}"
            onclick="selectCustomFont(${i})">
      ${f.name}
      <span class="font-remove" onclick="event.stopPropagation(); removeCustomFont(${i})" title="删除">&#10005;</span>
    </button>
  `).join('');
}

function selectCustomFont(index) {
  const font = state.customFonts[index];
  if (!font) return;
  state.subtitleFont = font.path;
  document.querySelectorAll('.font-btn').forEach(b => b.classList.remove('selected'));
  renderCustomFonts();
}

async function removeCustomFont(index) {
  const font = state.customFonts[index];
  if (!font) return;

  // 从服务器删除
  try {
    await fetch('/api/delete-font', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: font.path })
    });
  } catch (e) { /* ignore */ }

  // 如果删除的是当前选中的字体，回到默认
  if (state.subtitleFont === font.path) {
    state.subtitleFont = 'C:/Windows/Fonts/msyh.ttc';
    document.querySelectorAll('.font-btn').forEach((b, i) => b.classList.toggle('selected', i === 0));
  }

  state.customFonts.splice(index, 1);
  renderCustomFonts();
}

// === 视频时长选择 ===
function setupDuration() {
  const customInput = document.getElementById('customDuration');
  customInput.addEventListener('input', () => {
    const val = parseInt(customInput.value);
    if (val > 0) {
      document.querySelectorAll('.duration-btn').forEach(b => b.classList.remove('selected'));
      state.targetDuration = val;
      updateAdaptVisibility();
    } else if (!customInput.value) {
      document.querySelectorAll('.duration-btn')[0].classList.add('selected');
      state.targetDuration = 0;
      updateAdaptVisibility();
    }
  });
}

function selectDuration(btn) {
  document.querySelectorAll('.duration-btn').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
  document.getElementById('customDuration').value = '';
  state.targetDuration = parseInt(btn.dataset.duration);
  updateAdaptVisibility();
}

function updateAdaptVisibility() {
  const section = document.getElementById('adaptStrategySection');
  section.style.display = state.targetDuration > 0 ? 'block' : 'none';
}

function onAdaptStrategyChange() {
  state.adaptStrategy = document.getElementById('adaptStrategy').value;
  // 手动裁剪时，为每个素材添加起止时间输入
  if (state.adaptStrategy === 'manual') {
    renderMaterials();
  }
}

// === AI 配音 ===
function setupNarration() {
  const toggle = document.getElementById('narrationToggle');
  const label = document.getElementById('narrationToggleLabel');
  const settings = document.getElementById('narrationSettings');
  const rateSlider = document.getElementById('narrationRate');
  const rateValue = document.getElementById('narrationRateValue');
  const narrationVolSlider = document.getElementById('narrationVolume');
  const narrationVolValue = document.getElementById('narrationVolumeValue');
  const bgmVolSlider = document.getElementById('bgmVolume');
  const bgmVolValue = document.getElementById('bgmVolumeValue');

  toggle.addEventListener('change', () => {
    state.narrationEnabled = toggle.checked;
    label.textContent = toggle.checked ? '开启' : '关闭';
    settings.style.display = toggle.checked ? 'flex' : 'none';
  });

  rateSlider.addEventListener('input', () => {
    state.narrationRate = parseFloat(rateSlider.value);
    rateValue.textContent = state.narrationRate.toFixed(2) + 'x';
  });

  narrationVolSlider.addEventListener('input', () => {
    state.narrationVolume = parseFloat(narrationVolSlider.value);
    narrationVolValue.textContent = Math.round(state.narrationVolume * 100) + '%';
  });

  bgmVolSlider.addEventListener('input', () => {
    state.bgmVolume = parseFloat(bgmVolSlider.value);
    bgmVolValue.textContent = Math.round(state.bgmVolume * 100) + '%';
  });
}

function selectVoice(card) {
  document.querySelectorAll('.voice-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
  state.narrationVoice = card.dataset.voice;
}

// === 水印 ===
function setupWatermark() {
  const input = document.getElementById('watermarkInput');
  input.addEventListener('change', async (e) => {
    if (!e.target.files.length) return;
    const file = e.target.files[0];
    input.value = '';

    const ext = file.name.split('.').pop().toLowerCase();
    if (!['png', 'jpg', 'jpeg', 'webp'].includes(ext)) {
      showToast('请上传 PNG / JPG 图片');
      return;
    }

    const formData = new FormData();
    formData.append('watermark', file);

    try {
      const res = await fetch('/api/upload-watermark', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.error) {
        showToast('上传失败: ' + data.error);
        return;
      }

      state.watermarkPath = data.path;
      state.watermarkName = file.name;

      // 显示预览和设置面板
      document.getElementById('watermarkPreview').src = data.url;
      document.getElementById('watermarkName').textContent = file.name;
      document.getElementById('watermarkSettings').style.display = 'flex';
    } catch (e) {
      showToast('上传失败: ' + e.message);
    }
  });

  // 大小滑块
  const sizeSlider = document.getElementById('wmSize');
  const sizeValue = document.getElementById('wmSizeValue');
  sizeSlider.addEventListener('input', () => {
    state.watermarkSize = parseInt(sizeSlider.value);
    sizeValue.textContent = state.watermarkSize + '%';
  });

  // 不透明度滑块
  const opSlider = document.getElementById('wmOpacity');
  const opValue = document.getElementById('wmOpacityValue');
  opSlider.addEventListener('input', () => {
    state.watermarkOpacity = parseInt(opSlider.value);
    opValue.textContent = state.watermarkOpacity + '%';
  });
}

function selectWmPos(btn) {
  document.querySelectorAll('.wm-pos-btn').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
  state.watermarkPos = btn.dataset.pos;
}

function selectWmAnim(btn) {
  document.querySelectorAll('.wm-anim-tag').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
  state.watermarkAnim = btn.dataset.anim;
}

function removeWatermark() {
  state.watermarkPath = null;
  state.watermarkName = null;
  document.getElementById('watermarkSettings').style.display = 'none';
}

// === 参考视频上传与分析 ===
function setupRefUpload() {
  const zone = document.getElementById('refUploadZone');
  const input = document.getElementById('refFileInput');

  zone.addEventListener('click', () => input.click());

  zone.addEventListener('dragover', e => {
    e.preventDefault();
    zone.classList.add('dragover');
  });

  zone.addEventListener('dragleave', e => {
    if (e.target === zone) zone.classList.remove('dragover');
  });

  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      analyzeRefVideo(e.dataTransfer.files[0]);
    }
  });

  input.addEventListener('change', e => {
    if (e.target.files.length) {
      analyzeRefVideo(e.target.files[0]);
    }
    input.value = '';
  });
}

async function analyzeRefVideo(file) {
  const zone = document.getElementById('refUploadZone');
  const analysisDiv = document.getElementById('refAnalysis');

  // 验证是视频
  const ext = file.name.split('.').pop().toLowerCase();
  const videoExts = ['mp4','mov','avi','mkv','flv','wmv','webm','m4v'];
  if (!videoExts.includes(ext)) {
    showToast('请上传视频文件');
    return;
  }

  // 显示分析中状态
  const fileSizeMB = (file.size / 1024 / 1024).toFixed(0);
  zone.classList.add('analyzing');
  zone.querySelector('.ref-upload-title').textContent = '分析中...';
  zone.querySelector('.ref-upload-hint').textContent = `${file.name} · ${fileSizeMB}MB · 正在提取剪辑节奏`;

  // 超时提示（30秒还没返回就提醒）
  const slowTimer = setTimeout(() => {
    zone.querySelector('.ref-upload-title').textContent = '仍在分析中...';
    zone.querySelector('.ref-upload-hint').textContent = '视频较大，请耐心等待';
  }, 30000);

  const formData = new FormData();
  formData.append('file', file);

  try {
    // 5分钟超时保护
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 300000);

    const res = await fetch('/api/analyze-video', {
      method: 'POST',
      body: formData,
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    clearTimeout(slowTimer);
    const data = await res.json();

    if (data.error) {
      clearTimeout(slowTimer);
      showToast('分析失败: ' + data.error);
      resetRefZone();
      return;
    }

    // 保存分析结果
    state.refAnalysis = data.analysis;
    state.refTemplateConfig = data.config;

    // 自动保存模板
    await autoSaveRefTemplate(data.config);

    // 显示分析结果
    analysisDiv.style.display = 'block';
    analysisDiv.innerHTML = `
      <div class="ref-analysis-card">
        <div class="ref-analysis-row">
          <span class="ref-analysis-label">分辨率</span>
          <span class="ref-analysis-value">${data.analysis.resolution}</span>
        </div>
        <div class="ref-analysis-row">
          <span class="ref-analysis-label">时长</span>
          <span class="ref-analysis-value">${data.analysis.duration}s</span>
        </div>
        <div class="ref-analysis-row">
          <span class="ref-analysis-label">帧率</span>
          <span class="ref-analysis-value">${data.analysis.fps}fps</span>
        </div>
        <div class="ref-analysis-row">
          <span class="ref-analysis-label">画幅</span>
          <span class="ref-analysis-value">${data.analysis.aspect}</span>
        </div>
        <div class="ref-analysis-row">
          <span class="ref-analysis-label">场景切换</span>
          <span class="ref-analysis-value">${data.analysis.scene_count} 次</span>
        </div>
        <div class="ref-analysis-row">
          <span class="ref-analysis-label">平均镜头</span>
          <span class="ref-analysis-value">${data.analysis.avg_shot_duration}s</span>
        </div>
        <div class="ref-analysis-row">
          <span class="ref-analysis-label">节奏</span>
          <span class="ref-analysis-value">${data.analysis.pacing}</span>
        </div>
        <div class="ref-analysis-row">
          <span class="ref-analysis-label">镜头范围</span>
          <span class="ref-analysis-value">${data.analysis.clip_range}</span>
        </div>
        <div class="ref-analysis-row">
          <span class="ref-analysis-label">转场</span>
          <span class="ref-analysis-value">${data.analysis.transition}</span>
        </div>
      </div>
      <button class="ref-analysis-save" onclick="saveRefTemplate()">
        保存为模板并使用
      </button>
    `;

    resetRefZone();
  } catch (e) {
    clearTimeout(slowTimer);
    const msg = e.name === 'AbortError'
      ? '分析超时，视频可能过大，请尝试用较短的视频'
      : '分析失败: ' + e.message;
    showToast(msg);
    resetRefZone();
  }
}

function resetRefZone() {
  const zone = document.getElementById('refUploadZone');
  zone.classList.remove('analyzing');
  zone.querySelector('.ref-upload-title').textContent = '上传参考视频';
  zone.querySelector('.ref-upload-hint').textContent = '自动分析剪辑节奏并生成模板';
}

// 自动保存参考视频模板
async function autoSaveRefTemplate(config) {
  try {
    const res = await fetch('/api/save-template', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: `参考模板 ${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`,
        config: config
      })
    });
    const data = await res.json();

    if (!data.error) {
      // 刷新模板列表
      await loadTemplates();
      // 切换到"我的模板"选项卡并选中新模板
      state.selectedTemplate = data.id;
      switchTemplateTab('custom');
      updateRenderBtn();
      showToast('模板已自动保存');
    }
  } catch (e) {
    // 静默失败，不影响分析结果展示
  }
}

// === 拖拽上传 ===
function setupDropZone() {
  const zone = document.getElementById('dropZone');
  const input = document.getElementById('fileInput');

  zone.addEventListener('click', () => input.click());

  zone.addEventListener('dragover', e => {
    e.preventDefault();
    zone.classList.add('dragover');
  });

  zone.addEventListener('dragleave', e => {
    if (e.target === zone) zone.classList.remove('dragover');
  });

  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    handleFiles(e.dataTransfer.files);
  });

  input.addEventListener('change', e => {
    handleFiles(e.target.files);
    input.value = '';
  });
}

async function handleFiles(fileList) {
  const files = Array.from(fileList);
  if (!files.length) return;

  const validExts = ['mp4','mov','avi','mkv','flv','wmv','webm','m4v',
                     'jpg','jpeg','png','bmp','webp','tiff',
                     'mp3','wav','aac','m4a','flac','ogg','wma'];
  const valid = files.filter(f => {
    const ext = f.name.split('.').pop().toLowerCase();
    return validExts.includes(ext);
  });

  if (!valid.length) {
    showToast('请上传视频、图片或音频文件');
    return;
  }

  if (!state.sessionId) {
    state.sessionId = Math.random().toString(36).substring(2, 10);
  }

  const formData = new FormData();
  valid.forEach(f => formData.append('files', f));
  formData.append('session_id', state.sessionId);

  const uploadInner = document.querySelector('.upload-inner');
  const originalHTML = uploadInner.innerHTML;
  uploadInner.innerHTML = `
    <svg class="upload-icon" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" style="animation: spin 1s linear infinite">
      <path d="M21 12a9 9 0 1 1-6.219-8.56" stroke-linecap="round"/>
    </svg>
    <p class="upload-title">上传中... <span class="upload-pct">0%</span></p>
  `;

  try {
    const data = await uploadWithProgress(formData, (pct) => {
      const t = uploadInner.querySelector('.upload-pct');
      if (t) t.textContent = pct + '%';
    });

    data.files.forEach(f => {
      if (!state.materials.find(m => m.name === f.name)) {
        state.materials.push(f);
      }
    });

    const audioFile = data.files.find(f => f.type === 'audio');
    if (audioFile && !state.bgmFile) {
      state.bgmFile = audioFile;
    }

    renderMaterials();
    renderBGM();
    updateRenderBtn();
  } catch (e) {
    showToast('上传失败: ' + e.message);
  } finally {
    uploadInner.innerHTML = originalHTML;
  }
}

// 带真实上传进度 + 5 分钟超时保护的上传（fetch 拿不到 upload.onprogress）
function uploadWithProgress(formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const timeoutId = setTimeout(() => xhr.abort(), 300000);
    xhr.open('POST', '/api/upload');

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round(e.loaded / e.total * 100));
      }
    };

    xhr.onload = () => {
      clearTimeout(timeoutId);
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch (err) {
          reject(new Error('服务器响应解析失败'));
        }
      } else {
        let msg = '上传失败 (HTTP ' + xhr.status + ')';
        try {
          const j = JSON.parse(xhr.responseText);
          if (j && j.error) msg = j.error;
        } catch (_) { /* ignore */ }
        reject(new Error(msg));
      }
    };
    xhr.onerror = () => {
      clearTimeout(timeoutId);
      reject(new Error('网络错误，上传失败'));
    };
    xhr.onabort = () => {
      clearTimeout(timeoutId);
      reject(new Error('上传超时（5 分钟），请检查网络后重试'));
    };

    xhr.send(formData);
  });
}

// === 素材列表（视频轨）===
function renderMaterials() {
  const container = document.getElementById('materialsList');
  const clearBtn = document.getElementById('clearBtn');
  const countBadge = document.getElementById('materialCount');

  const visualMaterials = state.materials.filter(m => m.type === 'video' || m.type === 'image');

  if (!visualMaterials.length) {
    container.innerHTML = '';
    clearBtn.style.display = 'none';
    countBadge.style.display = 'none';
    return;
  }

  clearBtn.style.display = 'flex';
  countBadge.style.display = 'inline-block';
  countBadge.textContent = visualMaterials.length;

  const showTrim = state.adaptStrategy === 'manual' && state.targetDuration > 0;

  container.innerHTML = visualMaterials.map((m, i) => {
    const icon = m.type === 'video'
      ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>'
      : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="1"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>';
    const sizeStr = m.size > 1024 * 1024
      ? (m.size / 1024 / 1024).toFixed(1) + ' MB'
      : (m.size / 1024).toFixed(0) + ' KB';

    const trimHtml = showTrim && m.type === 'video' ? `
      <div class="material-trim-inputs">
        <label>起</label>
        <input type="number" class="trim-start" data-idx="${i}" value="${m.trimStart || 0}" min="0" step="0.5" onchange="updateTrim(${i})">
        <label>止</label>
        <input type="number" class="trim-end" data-idx="${i}" value="${m.trimEnd || ''}" min="0" step="0.5" placeholder="末尾" onchange="updateTrim(${i})">
      </div>
    ` : '';

    return `
      <div class="material-item">
        <div class="material-thumb">${icon}</div>
        <div class="material-info">
          <div class="material-name">${m.name}</div>
          <div class="material-meta">${m.type.toUpperCase()} · ${sizeStr}</div>
          ${trimHtml}
        </div>
        <div class="material-actions-inline">
          <button class="btn-up" onclick="moveMaterial(${i}, -1)" ${i === 0 ? 'disabled' : ''}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg>
          </button>
          <button class="btn-down" onclick="moveMaterial(${i}, 1)" ${i === visualMaterials.length - 1 ? 'disabled' : ''}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
          <button class="btn-remove" onclick="removeMaterial(${i})">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </div>
    `;
  }).join('');
}

function updateTrim(index) {
  const visualMaterials = state.materials.filter(m => m.type === 'video' || m.type === 'image');
  const item = visualMaterials[index];
  if (!item) return;

  const startInput = document.querySelector(`.trim-start[data-idx="${index}"]`);
  const endInput = document.querySelector(`.trim-end[data-idx="${index}"]`);

  if (startInput) item.trimStart = parseFloat(startInput.value) || 0;
  if (endInput) item.trimEnd = endInput.value ? parseFloat(endInput.value) : null;
}

function moveMaterial(index, direction) {
  const visualMaterials = state.materials.filter(m => m.type === 'video' || m.type === 'image');
  const newIndex = index + direction;
  if (newIndex < 0 || newIndex >= visualMaterials.length) return;

  const item = visualMaterials[index];
  const target = visualMaterials[newIndex];
  const i1 = state.materials.indexOf(item);
  const i2 = state.materials.indexOf(target);
  [state.materials[i1], state.materials[i2]] = [state.materials[i2], state.materials[i1]];

  renderMaterials();
}

function removeMaterial(index) {
  const visualMaterials = state.materials.filter(m => m.type === 'video' || m.type === 'image');
  const item = visualMaterials[index];
  state.materials = state.materials.filter(m => m !== item);
  renderMaterials();
  updateRenderBtn();
}

function clearMaterials() {
  state.materials = [];
  state.bgmFile = null;
  renderMaterials();
  renderBGM();
  updateRenderBtn();
}

// === BGM ===
function renderBGM() {
  const container = document.getElementById('bgmStatus');
  if (state.bgmFile) {
    container.innerHTML = `
      <div class="bgm-file">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
        <span class="file-name">${state.bgmFile.name}</span>
        <span class="remove" onclick="removeBGM()">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </span>
      </div>
    `;
  } else {
    container.innerHTML = '<span class="field-empty">上传音频文件时自动识别</span>';
  }
}

function removeBGM() {
  state.bgmFile = null;
  renderBGM();
}

// === 字幕轨（独立于素材）===
function renderSubtitles() {
  const container = document.getElementById('subtitleList');
  if (!state.subtitles.length) {
    container.innerHTML = '<p class="field-empty">点击下方按钮添加字幕行</p>';
    return;
  }
  container.innerHTML = state.subtitles.map((text, i) => `
    <div class="subtitle-row">
      <span class="subtitle-num num">${String(i + 1).padStart(2, '0')}</span>
      <input type="text" class="subtitle-input"
             placeholder="第 ${i + 1} 行字幕"
             value="${escapeHtml(text)}"
             oninput="updateSubtitle(${i}, this.value)">
      <button class="sub-remove" onclick="removeSubtitle(${i})">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
  `).join('');
}

function addSubtitle() {
  state.subtitles.push('');
  renderSubtitles();
  setTimeout(() => {
    const inputs = document.querySelectorAll('.subtitle-input');
    if (inputs.length) inputs[inputs.length - 1].focus();
  }, 50);
}

function removeSubtitle(index) {
  state.subtitles.splice(index, 1);
  renderSubtitles();
}

function updateSubtitle(index, value) {
  state.subtitles[index] = value;
}

// === 渲染 ===
function updateRenderBtn() {
  const btn = document.getElementById('renderBtn');
  const hasMaterials = state.materials.filter(m => m.type === 'video' || m.type === 'image').length > 0;
  const hasTemplate = !!state.selectedTemplate;
  btn.disabled = !(hasMaterials && hasTemplate);
}

async function startRender() {
  const btn = document.getElementById('renderBtn');
  const progressArea = document.getElementById('progressArea');
  const resultArea = document.getElementById('resultArea');

  btn.disabled = true;
  btn.innerHTML = '<span>剪辑中</span><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 1s linear infinite"><path d="M21 12a9 9 0 1 1-6.219-8.56" stroke-linecap="round"/></svg>';
  progressArea.style.display = 'block';
  resultArea.style.display = 'none';

  const visualMaterials = state.materials.filter(m => m.type === 'video' || m.type === 'image');

  const payload = {
    session_id: state.sessionId,
    template_id: state.selectedTemplate,
    materials: visualMaterials,
    title: document.getElementById('titleInput').value.trim(),
    subtitles: state.subtitles.filter(s => s.trim()),
    ending: document.getElementById('endingInput').value.trim(),
    bgm_name: state.bgmFile ? state.bgmFile.name : '',
    custom_effect: state.customEffect,
    target_duration: state.targetDuration,
    adapt_strategy: state.adaptStrategy,
    subtitle_font: state.subtitleFont,
    subtitle_font_size: state.subtitleFontSize,
    narration_enabled: state.narrationEnabled,
    narration_voice: state.narrationVoice,
    narration_rate: state.narrationRate,
    narration_volume: state.narrationVolume,
    bgm_volume: state.bgmVolume,
    watermark: state.watermarkPath ? {
      path: state.watermarkPath,
      position: state.watermarkPos,
      animation: state.watermarkAnim,
      size: state.watermarkSize,
      opacity: state.watermarkOpacity
    } : null
  };

  try {
    const res = await fetch('/api/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (data.error) {
      showToast(data.error);
      resetBtn();
      return;
    }

    state.renderTaskId = data.task_id;
    pollProgress();
  } catch (e) {
    showToast('渲染请求失败: ' + e.message);
    resetBtn();
  }
}

function resetBtn() {
  const btn = document.getElementById('renderBtn');
  btn.disabled = false;
  btn.innerHTML = '<span>开始剪辑</span><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>';
  document.getElementById('progressArea').style.display = 'none';
}

function pollProgress() {
  if (state.pollTimer) clearInterval(state.pollTimer);

  // 停滞判断改为"网络连续失败"，不再用进度数值判断。
  // 原因：二叉合并 N 段时某整数百分比可能真实停留 >90s，旧逻辑会误判
  // "超时"并停止轮询，导致错过真正的 done 状态（服务器其实还在跑）。
  let failCount = 0;     // 连续网络/解析失败计数
  const maxFail = 30;    // 连续 30 次无成功响应（≈30s）= 真卡死
  const maxWait = 1200;  // 最多轮询 20 分钟，避免极端情况下永不停止
  let ticks = 0;

  state.pollTimer = setInterval(async () => {
    ticks++;
    if (ticks > maxWait) {
      clearInterval(state.pollTimer);
      showToast('渲染时间过长，已停止轮询；可刷新页面或重新渲染');
      resetBtn();
      return;
    }

    let data;
    try {
      const res = await fetch(`/api/status/${state.renderTaskId}`);

      // 服务器重启后任务不存在 → 404
      if (res.status === 404) {
        clearInterval(state.pollTimer);
        showToast('任务丢失（服务器可能已重启），请重新渲染');
        resetBtn();
        return;
      }

      data = await res.json();
    } catch (e) {
      // 网络抖动：单次失败继续轮询，连续失败才判定卡死
      failCount++;
      if (failCount >= maxFail) {
        clearInterval(state.pollTimer);
        showToast('网络中断或服务器无响应，请检查连接后重新渲染');
        resetBtn();
      }
      return;
    }

    failCount = 0; // 成功响应，重置失败计数

    // 任务不存在
    if (data.error) {
      clearInterval(state.pollTimer);
      showToast('任务不存在: ' + data.error);
      resetBtn();
      return;
    }

    const bar = document.getElementById('progressBar');
    const text = document.getElementById('progressText');
    const pct = document.getElementById('progressPct');

    bar.style.width = data.progress + '%';
    text.textContent = data.message;
    pct.textContent = data.progress + '%';

    if (data.status === 'done') {
      clearInterval(state.pollTimer);
      showResult();
    } else if (data.status === 'error') {
      // 后端已把真实 FFmpeg 报错存进 error_detail，前端完整透传
      showRenderError(data);
    }
  }, 1000);
}

function escapeHtml(str) {
  return String(str == null ? '' : str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// 仅用于内联 JS 字符串字面量参数（如 onclick="fn('...')"）。
// 注意：不能用 escapeHtml（HTML 实体会被解码回引号导致 JS 串提前闭合），
// 必须用反斜杠转义。
function escapeJsString(s) {
  return String(s == null ? '' : s)
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/"/g, '\\"')
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r');
}

// 渲染失败：展示友好信息 + 可复制的技术详情（呼应后端 error_detail 透传）
function showRenderError(data) {
  state.lastErrorDetail = data.error_detail || data.error || '';
  const area = document.getElementById('progressArea');
  area.innerHTML = `
    <div class="render-error">
      <div class="render-error-title">渲染失败</div>
      <div class="render-error-msg">${escapeHtml(data.error || '未知错误')}</div>
      ${state.lastErrorDetail ? `
      <details class="render-error-detail">
        <summary>查看技术详情（供开发者排查）</summary>
        <pre>${escapeHtml(state.lastErrorDetail)}</pre>
      </details>
      <button type="button" class="render-error-copy" onclick="copyErrorDetail()">复制错误详情</button>
      ` : ''}
    </div>
  `;
  resetBtn();
}

function copyErrorDetail() {
  if (!state.lastErrorDetail) return;
  const done = () => showToast('错误详情已复制到剪贴板');
  const fail = () => showToast('复制失败，请手动选择文本');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(state.lastErrorDetail).then(done).catch(fail);
  } else {
    fail();
  }
}

function showResult() {
  const btn = document.getElementById('renderBtn');
  const progressArea = document.getElementById('progressArea');
  const resultArea = document.getElementById('resultArea');
  const video = document.getElementById('previewVideo');
  const downloadLink = document.getElementById('downloadLink');

  btn.disabled = false;
  btn.innerHTML = '<span>开始剪辑</span><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>';
  progressArea.style.display = 'none';
  resultArea.style.display = 'block';

  const url = `/api/output/${state.renderTaskId}?t=${Date.now()}`;
  video.src = url;
  downloadLink.href = `/api/download/${state.renderTaskId}`;

  // 显示完成横幅
  showCompletionBanner();

  // 隐藏之前的文案区域
  document.getElementById('publishCopyArea').style.display = 'none';
}

// === 导出选项 ===
function exportResult(mode) {
  if (!state.renderTaskId) {
    showToast('没有可导出的任务');
    return;
  }

  switch (mode) {
    case 'full':
      // 下载完整版（当前输出）
      window.open(`/api/download/${state.renderTaskId}`, '_blank');
      break;

    case 'video_only':
      // 请求纯视频版本（无字幕无音频）
      window.open(`/api/export-video-only/${state.renderTaskId}`, '_blank');
      break;

    case 'subtitle':
      // 下载 SRT 字幕文件
      window.open(`/api/export-subtitles/${state.renderTaskId}`, '_blank');
      break;
  }
}

// === 完成通知横幅 ===
function showCompletionBanner() {
  // 移除已有的横幅
  const existing = document.querySelector('.completion-banner');
  if (existing) existing.remove();

  const banner = document.createElement('div');
  banner.className = 'completion-banner';
  banner.innerHTML = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
      <polyline points="22 4 12 14.01 9 11.01"/>
    </svg>
    <span>已生成完毕</span>
  `;
  document.body.appendChild(banner);

  // 3秒后自动消失
  setTimeout(() => {
    banner.classList.add('hiding');
    setTimeout(() => banner.remove(), 300);
  }, 3000);
}

// === 发布文案生成 ===
function generatePublishCopy() {
  const title = document.getElementById('titleInput').value.trim();
  const ending = document.getElementById('endingInput').value.trim();
  const subtitles = state.subtitles.filter(s => s && s.trim());
  const customEffect = state.customEffect;

  const copyArea = document.getElementById('publishCopyArea');
  const copyText = document.getElementById('publishCopyText');

  let text = '';

  // 标题/开场
  if (title) {
    text += `📌 ${title}\n\n`;
  }

  // 正文：将字幕重新排版成文案段落
  if (subtitles.length > 0) {
    subtitles.forEach((sub, i) => {
      text += `${sub.trim()}\n`;
    });
    text += '\n';
  }

  // 结尾引导语
  if (ending) {
    text += `👉 ${ending}\n\n`;
  }

  // 生成话题标签
  const tags = [];
  if (title) {
    // 从标题提取关键词作为标签
    const titleWords = title.replace(/[，。！？、：；""''（）【】]/g, ' ').split(/\s+/).filter(w => w.length >= 2);
    titleWords.slice(0, 3).forEach(w => tags.push(w));
  }
  if (customEffect) {
    const effectMap = {
      '电影感': '电影感剪辑', '冷色调': '冷色调', '暖色调': '暖色调',
      '快节奏': '快节奏剪辑', '黑白': '黑白摄影', '柔和清新': '日系清新',
      '复古': '复古风', '赛博朋克': '赛博朋克'
    };
    Object.keys(effectMap).forEach(k => {
      if (customEffect.includes(k)) tags.push(effectMap[k]);
    });
  }
  // 默认通用标签
  if (tags.length === 0) {
    tags.push('视频剪辑', '公司宣传', '创意视频');
  }

  // 去重
  const uniqueTags = [...new Set(tags)];

  // 平台标签格式
  const tagLine = uniqueTags.map(t => `#${t}`).join(' ');
  text += `${tagLine}\n\n`;

  // 平台提示
  text += `—\n`;
  text += `🎬 视频时长：${getVideoDuration() || '--'}秒\n`;
  text += `📐 画幅比例：9:16 竖屏\n`;
  text += `📱 适配平台：抖音 / 视频号 / 小红书`;

  copyText.value = text;
  copyArea.style.display = 'block';

  // 滚动到文案区域
  copyArea.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function getVideoDuration() {
  const video = document.getElementById('previewVideo');
  if (video && video.duration && !isNaN(video.duration)) {
    return Math.round(video.duration);
  }
  return null;
}

// 视频加载完成后获取时长
document.getElementById('previewVideo').addEventListener('loadedmetadata', () => {
  // 时长已可用，如果文案区域已显示则更新
  const copyText = document.getElementById('publishCopyText');
  if (copyText.value && getVideoDuration()) {
    copyText.value = copyText.value.replace(/视频时长：.*?秒/, `视频时长：${getVideoDuration()}秒`);
  }
});

// === 复制发布文案 ===
function copyPublishText() {
  const textarea = document.getElementById('publishCopyText');
  textarea.select();
  textarea.setSelectionRange(0, 99999);

  try {
    navigator.clipboard.writeText(textarea.value).then(() => {
      const btn = document.querySelector('.btn-copy-text');
      btn.classList.add('copied');
      btn.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
          <polyline points="22 4 12 14.01 9 11.01"/>
        </svg>
        已复制
      `;
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = `
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          复制
        `;
      }, 2000);
    });
  } catch (e) {
    // fallback
    document.execCommand('copy');
    showToast('已复制到剪贴板');
  }
}

function resetAll() {
  state.materials = [];
  state.subtitles = [];
  state.bgmFile = null;
  state.renderTaskId = null;
  state.customEffect = '';
  state.targetDuration = 0;
  state.adaptStrategy = 'smart';
  state.subtitleFont = 'C:/Windows/Fonts/msyh.ttc';
  state.subtitleFontSize = 56;
  state.customFonts = [];
  state.refAnalysis = null;
  state.refTemplateConfig = null;
  state.narrationEnabled = false;
  state.narrationVoice = 'zh-CN-XiaoxiaoNeural';
  state.narrationRate = 1.0;
  state.narrationVolume = 1.0;
  state.bgmVolume = 0.3;
  state.watermarkPath = null;
  state.watermarkName = null;
  state.watermarkPos = 'bottom-right';
  state.watermarkAnim = 'none';
  state.watermarkSize = 15;
  state.watermarkOpacity = 90;

  document.getElementById('titleInput').value = '';
  document.getElementById('endingInput').value = '';
  document.getElementById('customEffectInput').value = '';
  document.getElementById('customDuration').value = '';
  document.getElementById('adaptStrategy').value = 'smart';
  document.getElementById('adaptStrategySection').style.display = 'none';
  document.querySelectorAll('.duration-btn').forEach((b, i) => b.classList.toggle('selected', i === 0));
  document.querySelectorAll('.font-btn').forEach((b, i) => b.classList.toggle('selected', i === 0));
  document.getElementById('customFontList').style.display = 'none';
  document.getElementById('customFontList').innerHTML = '';
  document.getElementById('fontSize').value = '56';
  document.getElementById('fontSizeValue').textContent = '56';
  document.getElementById('narrationToggle').checked = false;
  document.getElementById('narrationToggleLabel').textContent = '关闭';
  document.getElementById('narrationSettings').style.display = 'none';
  document.getElementById('narrationRate').value = '1.0';
  document.getElementById('narrationRateValue').textContent = '1.00x';
  document.getElementById('narrationVolume').value = '1.0';
  document.getElementById('narrationVolumeValue').textContent = '100%';
  document.getElementById('bgmVolume').value = '0.3';
  document.getElementById('bgmVolumeValue').textContent = '30%';
  document.getElementById('watermarkSettings').style.display = 'none';
  document.getElementById('wmSize').value = '15';
  document.getElementById('wmSizeValue').textContent = '15%';
  document.getElementById('wmOpacity').value = '90';
  document.getElementById('wmOpacityValue').textContent = '90%';
  document.querySelectorAll('.wm-pos-btn').forEach(b => b.classList.toggle('selected', b.dataset.pos === 'bottom-right'));
  document.querySelectorAll('.wm-anim-tag').forEach(b => b.classList.toggle('selected', b.dataset.anim === 'none'));
  document.querySelectorAll('.voice-card').forEach((c, i) => {
    c.classList.toggle('selected', i === 0);
  });
  document.getElementById('resultArea').style.display = 'none';
  document.getElementById('progressArea').style.display = 'none';
  document.getElementById('refAnalysis').style.display = 'none';
  document.getElementById('publishCopyArea').style.display = 'none';
  document.getElementById('publishCopyText').value = '';

  renderMaterials();
  renderBGM();
  renderSubtitles();
  updateRenderBtn();
}

// === Toast 提示 ===
function showToast(msg) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = msg;
  toast.style.cssText = `
    position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%);
    background: #0A0A0A; color: #FFFFFF; padding: 14px 28px;
    border-radius: 2px; font-size: 14px; z-index: 9999;
    font-family: "Noto Sans SC", sans-serif;
    box-shadow: 0 4px 24px rgba(0,0,0,0.12);
    animation: toastIn 0.25s ease-out;
  `;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// === 启动 ===
init();
