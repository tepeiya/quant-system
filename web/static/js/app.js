/* ===== JS 工具 ===== */

// 统一Toast提示
function showToast(message, type = 'info', duration = 2600) {
    let box = document.getElementById('global-toast');
    if (!box) {
        box = document.createElement('div');
        box.id = 'global-toast';
        box.style.cssText = 'position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:99999;max-width:80%;padding:10px 14px;border-radius:10px;color:#fff;font-size:13px;box-shadow:0 8px 24px rgba(0,0,0,.25);display:none;';
        document.body.appendChild(box);
    }
    const color = type === 'error' ? '#d1242f' : (type === 'success' ? '#238636' : '#1f6feb');
    box.style.background = color;
    box.textContent = message;
    box.style.display = 'block';
    clearTimeout(window.__toastTimer);
    window.__toastTimer = setTimeout(() => box.style.display = 'none', duration);
}

// 通用API请求封装
async function apiFetch(url, options = {}) {
    const res = await fetch(url, options);
    let data = null;
    try { data = await res.json(); } catch (_) {}

    if (!res.ok) {
        const msg = (data && (data.message || data.error)) || `HTTP ${res.status}`;
        const trace = data && data.trace_id ? ` [trace:${data.trace_id}]` : '';
        throw new Error(msg + trace);
    }
    if (data && data.status === 'error') {
        const trace = data.trace_id ? ` [trace:${data.trace_id}]` : '';
        throw new Error((data.message || '请求失败') + trace);
    }
    return data;
}



// SPA 页面加载
async function loadPage(url, targetId = 'mainContent') {
    try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(resp.status);
        const html = await resp.text();
        document.getElementById(targetId).innerHTML = html;
        // 更新导航高亮
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        const page = url.split('/')[1] || 'dashboard';
        document.querySelector(`.nav-item[data-page="${page}"]`)?.classList.add('active');
    } catch (e) {
        document.getElementById(targetId).innerHTML = `<div class="panel">❌ 加载失败: ${e.message}</div>`;
    }
}

// 导航点击事件
document.addEventListener('DOMContentLoaded', () => {
    // 侧边栏导航
    document.querySelectorAll('.nav-item').forEach(el => {
        el.addEventListener('click', (e) => {
            e.preventDefault();
            const url = el.getAttribute('href');
            window.location.href = url;
            history.pushState({}, '', url);
            closeSidebar(); // 移动端导航后关侧栏
        });
    });
    
    // 浏览器回退
    window.addEventListener('popstate', () => {
        loadPage(window.location.pathname);
    });
});

// 工具函数
function $(id) { return document.getElementById(id); }
function formatCurrency(v) { return '$' + (v || 0).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2}); }
function formatPct(v) { return (v >= 0 ? '+' : '') + (v || 0).toFixed(2) + '%'; }
function pnlClass(v) { return v >= 0 ? 'positive' : 'negative'; }

// 加载登录用户
apiFetch('/auth/api/current_user').then(d => {
    const user = d.data || d;
    if (user && user.username) {
        const el = document.getElementById('loginUser');
        if (el) el.innerHTML = '<span class="user-dot"></span><span>' + user.username + '</span>' + (user.role === 'admin' ? ' <span style="font-size:10px;color:#d29922;">🔑</span>' : '') + '<span id="healthDot" style="margin-left:auto;font-size:11px;color:#8b949e;">⚪ 检查中</span>';
    }
}).catch(() => {});

let _healthDetail = null;

function toggleHealthPanel() {
    const panel = document.getElementById('healthPanel');
    if (!panel) return;
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    if (_healthDetail) renderHealthPanel(_healthDetail);
}

function copyHealthDiag() {
    if (!_healthDetail) return;
    const txt = JSON.stringify(_healthDetail, null, 2);
    navigator.clipboard.writeText(txt).then(() => showToast('已复制诊断信息', 'success')).catch(()=>showToast('复制失败', 'error'));
}

function renderHealthPanel(data) {
    const panel = document.getElementById('healthPanel');
    if (!panel) return;
    const checks = data.checks || {};
    const rows = Object.keys(checks).map(k => {
        const v = checks[k] || {};
        const icon = v.ok === false ? '🔴' : '🟢';
        const extra = v.error ? (' - ' + v.error) : (v.count ? (' - ' + v.count) : '');
        return `<div>${icon} <b>${k}</b>${extra}</div>`;
    }).join('');
    panel.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <b>系统健康详情</b>
        <button onclick="copyHealthDiag()" style="font-size:10px;padding:2px 6px;background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;">复制诊断</button>
      </div>
      <div style="margin-bottom:6px;color:#8b949e;">trace_id: ${data.trace_id || '-'} ${data.last_error_time ? ('| 最近错误: ' + data.last_error_time) : ''}</div>
      ${rows || '暂无数据'}
    `;
}

// 系统健康检查指示灯
async function updateHealthDot() {
    const dot = document.getElementById('healthDot');
    if (!dot) return;
    try {
        const d = await apiFetch('/api/health/full');
        _healthDetail = d;
        const st = d.status || 'degraded';
        if (st === 'ok') {
            dot.textContent = '🟢 正常';
            dot.style.color = '#3fb950';
            dot.title = '系统运行正常';
        } else {
            dot.textContent = '🟡 注意';
            dot.style.color = '#d29922';
            const checks = d.checks || {};
            const bad = Object.keys(checks).filter(k => checks[k] && checks[k].ok === false);
            dot.title = bad.length ? ('异常: ' + bad.join(', ')) : '部分模块降级';
        }
        // 如果面板已展开，刷新详情
        const panel = document.getElementById('healthPanel');
        if (panel && panel.style.display !== 'none') {
            renderHealthPanel(d);
        }
    } catch (e) {
        dot.textContent = '🔴 故障';
        dot.style.color = '#f85149';
        dot.title = e.message || '健康检查失败';
    }
}

setInterval(updateHealthDot, 30000);
updateHealthDot();

// ===== 响应式：侧边栏管理 =====
function openSidebar() {
    document.querySelector('.sidebar')?.classList.add('open');
    document.querySelector('.sidebar-overlay')?.classList.add('show');
}

function closeSidebar() {
    document.querySelector('.sidebar')?.classList.remove('open');
    document.querySelector('.sidebar-overlay')?.classList.remove('show');
}

document.addEventListener('DOMContentLoaded', () => {
    // 添加汉堡按钮和遮罩
    const app = document.querySelector('.app');
    if (!app) return;
    
    // 遮罩
    const overlay = document.createElement('div');
    overlay.className = 'sidebar-overlay';
    overlay.addEventListener('click', closeSidebar);
    app.prepend(overlay);
    
    // 汉堡按钮
    const toggle = document.createElement('button');
    toggle.className = 'menu-toggle';
    toggle.innerHTML = '☰';
    toggle.setAttribute('aria-label', '菜单');
    toggle.addEventListener('click', openSidebar);
    document.body.prepend(toggle);
    
    // 页面加载完毕，给表格加 data-label 属性（小屏卡片化）
    setTimeout(addTableLabels, 100);
});

// 给表格添加 data-label 实现卡片视图
function addTableLabels() {
    document.querySelectorAll('table').forEach(table => {
        // 获取表头
        const headers = [];
        table.querySelectorAll('thead th').forEach(th => {
            headers.push(th.textContent.trim());
        });
        if (headers.length === 0) return;
        
        // 给每行每个单元格加 data-label
        table.querySelectorAll('tbody tr').forEach(tr => {
            tr.querySelectorAll('td').forEach((td, i) => {
                if (i < headers.length && !td.hasAttribute('data-label')) {
                    td.setAttribute('data-label', headers[i]);
                }
            });
        });
        
        // 检测小屏 → 自动加 table-card-view class
        const wrapper = table.closest('.table-wrapper');
        if (wrapper && window.innerWidth <= 600) {
            wrapper.classList.add('table-card-view');
        }
    });
}

// 窗口变小时自动切换表格模式
window.addEventListener('resize', () => {
    document.querySelectorAll('.table-wrapper').forEach(w => {
        if (window.innerWidth <= 600) {
            w.classList.add('table-card-view');
        } else {
            w.classList.remove('table-card-view');
        }
    });
});

// ===== 主题切换 =====
let theme = localStorage.getItem('theme') || 'dark';

function toggleTheme() {
    theme = theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', theme);
    applyTheme();
}

function applyTheme() {
    const body = document.body;
    const icon = document.getElementById('themeIcon');
    const label = document.getElementById('themeLabel');
    
    if (theme === 'light') {
        body.classList.add('theme-light');
        if (icon) icon.textContent = '☀️';
        if (label) label.textContent = '亮色';
    } else {
        body.classList.remove('theme-light');
        if (icon) icon.textContent = '🌙';
        if (label) label.textContent = '深色';
    }
}
applyTheme();

// ===== 交易模式切换 =====
let tradeMode = localStorage.getItem('trade_mode') || 'paper';

function updateTradeModeUI() {
    const badge = document.getElementById('modeBadge');
    const hint = document.getElementById('modeHint');
    if (!badge) return;
    if (tradeMode === 'paper') {
        badge.textContent = '📄 纸交易';
        badge.style.color = '#3fb950';
        if (hint) { hint.textContent = '点此切换'; hint.style.color = '#8b949e'; }
    } else {
        badge.textContent = '🔴 实盘';
        badge.style.color = '#f85149';
        if (hint) { hint.textContent = '⚠️ 真实资金！'; hint.style.color = '#f85149'; }
    }
}

async function toggleTradeMode() {
    const targetMode = tradeMode === 'paper' ? 'live' : 'paper';
    const isLive = targetMode === 'live';
    const modeName = isLive ? '🔴 实盘' : '📄 纸交易';
    if (isLive) {
        if (!confirm('⚠️ 确认切换到实盘模式？\n\n切换后所有交易将使用真实资金执行！\n\n请确认：\n1. 实盘API Key已配置在环境变量\n2. 实盘券商已在券商页面启用\n3. 账户资金充足')) return;
        if (!confirm('再次确认：真的要切换到实盘吗？\n\n这个操作将禁用纸交易券商，启用实盘券商。')) return;
    } else {
        if (!confirm('切换为纸交易模式？')) return;
    }
    tradeMode = targetMode;
    localStorage.setItem('trade_mode', tradeMode);
    updateTradeModeUI();
    try {
        const resp = await fetch('/api/switch_mode', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: targetMode})
        });
        const d = await resp.json();
        if (d.status === 'ok') {
            showToast(d.message, 'success');
        } else {
            showToast('切换失败: ' + (d.message || d.error), 'error');
        }
    } catch(e) {
        showToast('切换失败: ' + e.message, 'error');
    }
}
updateTradeModeUI();
