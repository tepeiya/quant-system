# 回滚说明（Rollback）

## 1) 查看最近提交
```bash
git log --oneline -10
```

## 2) 回滚到指定提交（示例）
```bash
git reset --hard <commit_id>
docker compose down
docker compose up -d --build
```

## 3) 回滚到上一个版本
```bash
git reset --hard HEAD~1
docker compose down
docker compose up -d --build
```

## 4) 强制与GitHub主分支一致（恢复最新）
```bash
git fetch origin
git reset --hard origin/main
docker compose down
docker compose up -d --build
```

## 5) 若本地有改动导致pull失败
```bash
git checkout -- .
git clean -fd
git pull
```
