import os
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
from langchain_text_splitters import MarkdownHeaderTextSplitter
from backend.embed import embed_text

# Load .env from the root folder
load_dotenv()

def main():
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    index_name = os.getenv("PINECONE_INDEX_NAME")

    # Create index if it doesn't exist
    if index_name not in [idx.name for idx in pc.list_indexes()]:
        print(f"Creating Pinecone index: {index_name}...")
        pc.create_index(
            name=index_name,
            dimension=768, # Gemini embedding dimension
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
    
    index = pc.Index(index_name)

    # Read the dummy 10-K
    file_path = os.path.join(os.path.dirname(__file__), 'data', 'nvda_2024_10k.md')
    with open(file_path, 'r', encoding='utf-8') as f:
        markdown_text = f.read()

    headers_to_split_on = [("#", "H1"), ("##", "H2")]
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    chunks = markdown_splitter.split_text(markdown_text)

    vectors = []
    for i, chunk in enumerate(chunks):
        # Prepend structural context before embedding
        item_section = chunk.metadata.get("H1", "Unknown")
        text = f"Context: Company: NVDA | Year: 2024 | Section: {item_section}\n\n{chunk.page_content}"
        
        embedding = embed_text(text)
        
        vectors.append({
            "id": f"nvda-2024-{i}",
            "values": embedding,
            "metadata": {
                "ticker": "NVDA",
                "fiscal_year": 2024,
                "form_type": "10-K",
                "item_section": item_section,
                "text": text
            }
        })

    index.upsert(vectors=vectors, namespace="sec-10k")
    print(f"Upserted {len(vectors)} chunks successfully.")

if __name__ == "__main__":
    main()
