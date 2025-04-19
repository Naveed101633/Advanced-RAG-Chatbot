import os
import uuid
from flask import Flask, request, render_template, session, redirect, url_for
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
import google.generativeai as genai

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management

# Google API Key (set as environment variable in Replit)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not set in environment variables")
genai.configure(api_key=GOOGLE_API_KEY)

# Directories
UPLOAD_FOLDER = "uploads"
CHROMA_PERSIST_DIR = "chroma_db"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)

# Initialize embeddings
embeddings = GoogleGenerativeAIEmbeddings(
    model="models/text-embedding-004", google_api_key=GOOGLE_API_KEY
)

# Initialize LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash", api_key=GOOGLE_API_KEY
)

# Prompt template
message = """
Answer this question using the provided context only.

{question}

Context:
{context}
"""
prompt = ChatPromptTemplate.from_messages([("human", message)])

def create_vectorstore(pdf_path, collection_name):
    """Create or load vectorstore for a PDF."""
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents(documents)

    vectorstore = Chroma.from_documents(
        documents=splits,
        embedding=embeddings,
        persist_directory=os.path.join(CHROMA_PERSIST_DIR, collection_name)
    )
    return vectorstore

def get_vectorstore(collection_name):
    """Retrieve existing vectorstore."""
    return Chroma(
        persist_directory=os.path.join(CHROMA_PERSIST_DIR, collection_name),
        embedding_function=embeddings
    )

@app.route("/", methods=["GET", "POST"])
def index():
    # Initialize session variables
    if "chat_history" not in session:
        session["chat_history"] = []
    if "collection_name" not in session:
        session["collection_name"] = None
    if "pdf_uploaded" not in session:
        session["pdf_uploaded"] = False

    if request.method == "POST":
        # Handle PDF upload
        if "pdf" in request.files:
            pdf_file = request.files["pdf"]
            if pdf_file.filename.endswith(".pdf"):
                # Generate unique collection name
                collection_name = str(uuid.uuid4())
                pdf_path = os.path.join(UPLOAD_FOLDER, f"{collection_name}.pdf")
                pdf_file.save(pdf_path)

                # Create vectorstore
                create_vectorstore(pdf_path, collection_name)

                # Update session
                session["collection_name"] = collection_name
                session["pdf_uploaded"] = True
                session["chat_history"] = []  # Reset chat history
                return redirect(url_for("index"))

        # Handle query
        if "query" in request.form and session["pdf_uploaded"]:
            query = request.form["query"]
            if query.strip():
                # Retrieve vectorstore
                vectorstore = get_vectorstore(session["collection_name"])
                retriever = RunnableLambda(vectorstore.similarity_search).bind(k=1)

                # Build RAG chain
                rag_chain = (
                    {"context": retriever, "question": RunnablePassthrough()}
                    | prompt
                    | llm
                )

                # Get response
                response = rag_chain.invoke(query)

                # Update chat history
                session["chat_history"].append({"role": "user", "content": query})
                session["chat_history"].append({"role": "ai", "content": response.content})
                session.modified = True  # Ensure session updates

    return render_template("index.html", chat_history=session["chat_history"], pdf_uploaded=session["pdf_uploaded"])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)