from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import requests
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# External n8n endpoint
EXTERNAL_URL = "http://10.121.252.247:5678/webhook/knowledge"

class KnowledgeRequest(BaseModel):
    session_id: str
    question: str

class KnowledgeResponse(BaseModel):
    output: str

@router.post("/knowledge", 
             response_model=KnowledgeResponse, 
             summary="Knowledge Base Query", 
             description="Query the n8n knowledge base via webhook")
async def query_knowledge(request: Request, body: KnowledgeRequest):
    """
    Forward the question to the n8n knowledge webhook and return the response.
    """
    try:
        logger.info(f"Forwarding knowledge request for session: {body.session_id} to {EXTERNAL_URL}")
        
        # Forward the Authorization header from the incoming request
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        headers = {}
        if auth_header:
            headers["Authorization"] = auth_header

        # n8n expects "chatInput" instead of "question" and "sessionId" instead of "session_id"
        payload = body.dict()
        payload["chatInput"] = payload.pop("question")
        payload["sessionId"] = payload.pop("session_id")

        # run_in_threadpool is used to call the synchronous requests library 
        # without blocking the FastAPI event loop.
        response = await run_in_threadpool(
            requests.post,
            EXTERNAL_URL,
            json=payload,
            headers=headers,
            timeout=60  # n8n might take some time to process
        )
        
        # Check if the request was successful
        response.raise_for_status()
        
        # Log the raw response for debugging
        logger.debug(f"n8n response: {response.text}")
        
        try:
            return response.json()
        except ValueError as e:
            logger.error(f"Failed to parse n8n response as JSON. Status: {response.status_code}, Headers: {dict(response.headers)}, Content: {response.text[:200]}")
            raise HTTPException(status_code=502, detail=f"Invalid JSON response from n8n (Status {response.status_code}): {response.text[:100]}")

        
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error from n8n: {e}. Content: {e.response.text if e.response else 'No content'}")

        detail = f"n8n service error: {str(e)}"
        if e.response is not None:
            try:
                # Try to extract more details from n8n response if available
                error_json = e.response.json()
                detail = error_json.get("message", detail)
            except:
                pass
        raise HTTPException(status_code=e.response.status_code if e.response is not None else 502, detail=detail)
        
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error to n8n: {e}")
        raise HTTPException(status_code=503, detail="Could not connect to the knowledge service")
        
    except Exception as e:
        logger.error(f"Unexpected error in knowledge endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
