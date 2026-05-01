"""
RAG Chat Agent — rag/agent.py
Run from project root: python -m rag.agent
"""

import sys
import os

# Make sure app/ is importable from project root
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.indexing.embeddings import embed

from qdrant_client import QdrantClient
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

QDRANT_HOST     = "localhost"
QDRANT_PORT     = 6333
COLLECTION_NAME = "documents"
CLAUDE_MODEL    = "claude-sonnet-4-20250514"
TOP_K           = 5


# ─────────────────────────────────────────────
# QDRANT CLIENT
# ─────────────────────────────────────────────

client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


# ─────────────────────────────────────────────
# RETRIEVER
# ─────────────────────────────────────────────

def retrieve(query: str) -> list[dict]:
    vector = embed(query)

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=TOP_K,
    )

    return [
        {
            "score":    round(r.score, 3),
            "filename": r.payload.get("filename", "unknown"),
            "text":     r.payload.get("text", ""),
        }
        for r in results.points
    ]


def format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "No relevant documents found."
    return "\n\n".join(
        f"[Source: {c['filename']} | score: {c['score']}]\n{c['text']}"
        for c in chunks
    )


# ─────────────────────────────────────────────
# PROMPT + LLM + CHAIN
# ─────────────────────────────────────────────

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a document assistant.
Answer the user's question using ONLY the context below.
If the answer is not in the context, say "I couldn't find that in the documents."
Always mention the source filename when referencing information.

Context:
{context}"""),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{question}"),
])

llm = ChatAnthropic(
    model=CLAUDE_MODEL,
    temperature=0.2,
    max_tokens=1024,
)

chain = prompt | llm | StrOutputParser()


# ─────────────────────────────────────────────
# CHAT LOOP
# ─────────────────────────────────────────────

def chat() -> None:
    print("\n" + "═" * 50)
    print("  Omnidoc RAG Agent  |  Qdrant + Claude")
    print("  'exit' to quit  |  'clear' to reset memory")
    print("═" * 50 + "\n")

    chat_history = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("Goodbye!")
            break
        if user_input.lower() == "clear":
            chat_history.clear()
            print("[memory cleared]\n")
            continue

        # 1. Retrieve
        chunks = retrieve(user_input)

        # 2. Show sources
        print("\n📎 Sources:")
        for c in chunks:
            print(f"   {c['filename']}  (score: {c['score']})")
        print()

        # 3. Generate answer
        answer = chain.invoke({
            "context":      format_context(chunks),
            "chat_history": chat_history,
            "question":     user_input,
        })

        print(f"Agent: {answer}\n")

        # 4. Update memory
        chat_history.append(HumanMessage(content=user_input))
        chat_history.append(AIMessage(content=answer))


if __name__ == "__main__":
    chat()