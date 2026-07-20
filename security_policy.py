# 公共安全策略（单一真相来源）
# 注意：brokers 蓝图涉及券商凭证, 必须登录后访问, 不能放入公开路径
PUBLIC_PATHS = [
    "/login", "/register", "/logout",
    "/auth/login", "/auth/register", "/auth/logout",
    "/static/", "/api/csrf_token",
    "/api/health/full",
]
