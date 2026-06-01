# 部署后检查清单（上线自检）

## 1. 拉取并重启
```bash
cd ~/quant-system
git pull
docker compose down
docker compose up -d --build
```

## 2. 容器状态
```bash
docker compose ps
docker compose logs --tail=50
```

## 3. 关键页面检查
```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8765/login
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8765/brokers/
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8765/settings/
```

## 4. 登录与健康检查
```bash
# 登录测试
curl -X POST http://localhost:8765/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"quant123"}'

# 健康检查
curl http://localhost:8765/api/health/full
```

## 5. 热图/信号/券商接口
```bash
curl http://localhost:8765/heatmap/api/data
curl http://localhost:8765/signals/api/today
curl http://localhost:8765/brokers/api/list
```

## 6. 常见故障快速定位
- 登录网络错误：检查 login.html 是否请求 `/auth/login`
- 券商启用404：检查 `/brokers/api/toggle`
- Dashboard报错：看 `/api/health/full` 的 `checks` 字段
- 热图空白：先补缓存 `python3 data_filler.py`

## 7. 数据补全（建议后台）
```bash
docker compose exec -d m-plus python3 data_filler.py
docker compose logs -f m-plus | grep -E 'filler|cache|Tiingo'
```
