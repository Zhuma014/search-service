from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import BaseModel
from config import settings
import google.generativeai as genai
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Configure Gemini for text generation
genai.configure(api_key=settings.GEMINI_API_KEY)
model = genai.GenerativeModel(settings.GEMINI_MODEL)


class GenerateRequest(BaseModel):
    prompt: str


@router.post("/generate")
async def generate(
    request: Request,
    body: GenerateRequest
):
    """
    Generate text based on user request using Gemini (max 80 characters).
    
    Request body:
    - prompt: User request or query for text generation
    
    Returns:
    - text: Generated text up to 80 characters
    """
    
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt field cannot be empty")
    
    try:
        # Generate text using Gemini
        generation_prompt = f"""You are a specialized AI assistant for a Document Management System. 
Your primary task is to generate professional text, descriptions, or summaries specifically related to official, corporate, or business documents.

Step 1: Analyze the user request.
Step 2: Check if it is related to documents, paperwork, or official corporate communication.
- If the request is NOT related to documents (e.g., casual chat, birthday greetings, jokes, general knowledge), IGNORE the request and reply EXACTLY with this text in Russian: "Я являюсь помощником по генерации текста по документообороту и могу помочь вам только с запросами, связанными с документами."
- If the request IS related to documents, provide the requested text, draft, or description directly.

Rules for valid requests:
1. Use a strictly formal, professional, and business-like tone.
2. Give the actual result or draft immediately. Do NOT explain what you are doing (no "Here is your document").
3. Provide a complete and comprehensive response based on the prompt.
4. Return ONLY the final generated text.

Request:
{body.prompt}"""
        
        response = model.generate_content(generation_prompt)
        generated_text = response.text.strip()
        
        logger.info(f"Generated text")
        
        return {
            "text": generated_text
        }
        
    except Exception as e:
        logger.error(f"Error generating description: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to generate description: {str(e)}"
        )
