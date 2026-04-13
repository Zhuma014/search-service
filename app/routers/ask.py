from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import BaseModel
from app.elasticsearch.client import ESClient, get_index_name
from app.services.embeddings import get_query_embedding
from config import settings
import google.generativeai as genai
from datetime import datetime
from collections import deque
from typing import Optional
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory storage for chat history
chat_memory = {}

# Gemini только для генерации ответа (не для embeddings)
genai.configure(api_key=settings.GEMINI_API_KEY)
model = genai.GenerativeModel(settings.GEMINI_MODEL)


class AskRequest(BaseModel):
    document_id: str
    question:    str
    session_id:  str = None

class AskResponse(BaseModel):
    document_id: str
    session_id: Optional[str] = None
    question: str
    answer: str

@router.post("/ask", response_model=AskResponse, summary="Ask Question", description="Ask a question about a specific document using RAG with Gemini")
async def ask_question(
    request: Request,
    body: AskRequest,
    x_company_id: str = Header(None, alias="X-Company-ID")
):
    company_id = getattr(request.state, "company_id", None)
    index_name = get_index_name(company_id) if company_id else "*_documents"
    client     = ESClient.get_client()

    # 0. История чата
    history_context = ""
    if body.session_id and body.session_id in chat_memory:
        for msg in chat_memory[body.session_id]:
            role = "Пользователь" if msg["role"] == "user" else "Ассистент"
            history_context += f"{role}: {msg['content']}\n"

    # 1. Векторизуем вопрос локально — без API
    query_vector = get_query_embedding(body.question)

    # 2. kNN поиск в ES по конкретному документу
    search_body = {
        "knn": {
            "field":        "embedding",
            "query_vector": query_vector,
            "k":            5,
            "num_candidates": 50,
            "filter": {
                "term": {"document_id": body.document_id}
            }
        },
        "_source": ["content", "title", "filename"]
    }

    try:
        response = await client.search(index=index_name, body=search_body)

        # 3. Собираем контекст из найденных чанков
        chunks = [hit["_source"]["content"] for hit in response["hits"]["hits"]]
        if not chunks:
            return {
                "answer": "Документ не найден или в нём нет информации по вашему вопросу."
            }

        context = "\n\n".join(chunks)

        # 4. Формируем промпт для Gemini
        history_header = f"История беседы:\n{history_context}\n" if history_context else ""

        prompt = f"""Ты — экспертный аналитик документов. 
Твоя задача: дать подробный, развернутый и информативный ответ на основе предоставленного текста.

Правила:
1. Используй только информацию из «Текста документа» ниже.
2. Не ограничивайся короткими фразами. Раскрывай детали, приводи пояснения.
3. Отвечай на том языке, на котором задан вопрос.
4. Если в тексте нет ответа, прямо сообщи об этом, не выдумывая фактов.

{history_header}
Текст документа:
{context}

Вопрос: {body.question}
"""

        # 5. Gemini генерирует ответ (только текст, не embeddings)
        ai_response = await model.generate_content_async(prompt)
        ai_answer   = ai_response.text

        # 6. Сохраняем в историю
        if body.session_id:
            if body.session_id not in chat_memory:
                chat_memory[body.session_id] = deque(maxlen=5)
            chat_memory[body.session_id].append({"role": "user",      "content": body.question})
            chat_memory[body.session_id].append({"role": "assistant", "content": ai_answer})

        return {
            "document_id": body.document_id,
            "session_id":  body.session_id,
            "question":    body.question,
            "answer":      ai_answer,
        }

    except Exception as e:
        logger.error(f"RAG error: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing question: {str(e)}")