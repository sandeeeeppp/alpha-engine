import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

# Switched to 8b-instant to avoid the Llama 3.3 XML formatting bug
supervisor_llm = ChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY"),
)

agent_llm = ChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY"),
)