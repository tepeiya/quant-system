from pathlib import Path
files = [
'web/templates/login.html','web/templates/register.html','web/templates/brokers.html',
'web/templates/settings.html','web/templates/trading.html','web/templates/signals.html',
'web/templates/positions.html','web/templates/dashboard.html','web/templates/heatmap.html',
'web/templates/pairs.html','web/templates/factors.html','web/templates/trades.html','web/templates/history.html','web/templates/macro.html','web/templates/wheel.html'
]
for fp in files:
    p = Path(fp)
    s = p.read_text()
    s = s.replace('await fetch(', 'await apiFetch(')
    p.write_text(s)
print('patched', len(files))
