/* ===== JS 工具 ===== */

// 通用API请求封装
async function apiFetch(url, options = {}) {
    const res = await fetch(url, options);
    let data = null;
    try { data = await res.json(); } catch (_) {}

    if (!res.ok) {
        const msg = (data && (data.message || data.error)) || `HTTP ${res.status}`;
        throw new Error(msg);
    }
    if (data && data.status === 'error') {
        throw new Error(data.message || '请求失败');
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
fetch('/auth/api/current_user').then(r => r.json()).then(d => {
    if (d.username) {
        const el = document.getElementById('loginUser');
        if (el) el.innerHTML = '<span class="user-dot"></span><span>' + d.username + '</span>' + (d.role === 'admin' ? ' <span style="font-size:10px;color:#d29922;">🔑</span>' : '');
    }
});

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
    tradeMode = tradeMode === 'paper' ? 'live' : 'paper';
    localStorage.setItem('trade_mode', tradeMode);
    updateTradeModeUI();
    try {
        await fetch('/api/trade_mode', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: tradeMode})
        });
    } catch(e) {}
}
updateTradeModeUI();
