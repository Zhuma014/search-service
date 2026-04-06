from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import re
import jwt
import logging

logger = logging.getLogger(__name__)

class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip tenant check for health endpoint
        if request.url.path in ["/health", "/docs", "/openapi.json"]:
            return await call_next(request)
            
        company_id = request.headers.get("X-Company-ID")
        if company_id:
            # Validate company_id: only alphanumeric, dash, and underscore
            if not re.match(r"^[a-zA-Z0-9\-_]+$", company_id):
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid X-Company-ID format"}
                )
            
            # Store company_id in request state for routers to use
            request.state.company_id = company_id
            
        # Extract JWT info from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"}
            )
            
        token = auth_header.split(" ")[1]
        try:
            # Decode the JWT without verifying the signature as per user preference
            user_info = jwt.decode(token, options={"verify_signature": False})
            request.state.user_info = user_info
        except Exception as e:
            logger.warning(f"Failed to decode JWT token: {e}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid token"}
            )

        response = await call_next(request)
        return response
