import os
from dotenv import load_dotenv
from pinecone import Pinecone
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.tools import tool

load_dotenv()

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
# Appended -v2 to match the new index
index = pc.Index(os.getenv("PINECONE_INDEX_NAME") + "-v2")
emb = GoogleGenerativeAIEmbeddings(
    model="gemini-embedding-2", # Updated model
    google_api_key=os.getenv("GEMINI_API_KEY")
)

@tool
def pinecone_search(query: str, ticker: str, fiscal_year: int) -> str:
    """Search SEC 10-K filings for qualitative fundamental risk context."""
    vector = emb.embed_query(query)
    results = index.query(
        vector=vector,
        top_k=3,
        namespace="sec-10k",
        filter={"ticker": {"$eq": ticker}, "fiscal_year": {"$gte": fiscal_year}},
        include_metadata=True
    )
    
    if not results.matches:
        return "No relevant fundamental data found."
        
    return "\n\n---\n\n".join([m.metadata["text"] for m in results.matches])