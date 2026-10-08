from fastapi import APIRouter

from app.api.routes import auth, stats, tickets, users

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(tickets.router)
api_router.include_router(stats.router)
