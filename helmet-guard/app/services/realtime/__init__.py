"""实时推送包：导出连接管理单例。"""

from app.services.realtime.hub import ConnectionManager, hub

__all__ = ["ConnectionManager", "hub"]
