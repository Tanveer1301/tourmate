from .admin_console import public_router as public_config_router
from .admin_console import router as admin_router
from .auth import router as auth_router
from .collaboration import router as collaboration_router
from .deposits import router as deposits_router
from .expenses import router as expenses_router
from .feedback import router as feedback_router
from .settlement import router as settlement_router
from .tours import router as tours_router

__all__ = [
    "admin_router",
    "auth_router",
    "collaboration_router",
    "deposits_router",
    "expenses_router",
    "feedback_router",
    "public_config_router",
    "settlement_router",
    "tours_router",
]


