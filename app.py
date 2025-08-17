import streamlit as st
import google.generativeai as genai
import os
import json
import re
from PIL import Image
from dotenv import load_dotenv

# --- Load Environment Variables (for local testing) ---
load_dotenv()

# --- Configuration & Initialization ---
PROCESSED_DATA_DIR = "processed_data"
st.set_page_config(page_title="AI Manual Assistant", page_icon="🤖", layout="wide")
st.title("🤖 AI Assistant for Technical Manuals")
st.write("Select a manual, then ask a question using text and/or an image.")

# --- API Key Configuration ---
try:
    # This robust method works for both local development (with .env) and Streamlit Cloud (with st.secrets)
    api_key = st.secrets.get("GOOGLE_API_KEY", os.environ.get("GOOGLE_API_KEY"))
    if not api_key:
        st.error("🔴 GOOGLE_API_KEY is not set!")
        st.info("Please add it to your Streamlit Secrets or your local .env file.")
        st.stop()
    genai.configure(api_key=api_key)
except Exception as e:
    st.error(f"Error configuring the Google API: {e}")
    st.stop()

# --- Core Functions ---

@st.cache_data
def get_available_manuals():
    """Scans for subdirectories in the processed data directory."""
    if not os.path.exists(PROCESSED_DATA_DIR):
        return []
    return [d for d in os.listdir(PROCESSED_DATA_DIR) if os.path.isdir(os.path.join(PROCESSED_DATA_DIR, d))]

@st.cache_data
def load_manual_data(manual_name):
    """Loads the content.json for a selected manual."""
    json_path = os.path.join(PROCESSED_DATA_DIR, manual_name, "content.json")
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        st.error(f"Could not find 'content.json' for '{manual_name}'. Did ingestion run correctly?")
        return None

def get_gemini_response(question, context, image=None):
    """Queries the Gemini model with text, context, and an optional image."""
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt_parts = [
            f"""
            You are an expert assistant specialized in analyzing technical manuals for complex machinery like ultrasound equipment.
            Your task is to answer the user's question based ONLY on the provided context from the manual.
            If the user provides an image, use it as part of their query (e.g., "What is this button?" with an image of a button).
            After providing the answer, you MUST cite the specific page number(s) where you found the information.
            Format your citation clearly at the end of your answer, for example: (Source: Page 15) or (Source: Pages 28, 32).

            CONTEXT FROM MANUAL:
            {context}

            QUESTION:
            {question}

            ASSISTANT'S ANSWER:
            """
        ]
        
        if image:
            prompt_parts.insert(1, image)
            
        response = model.generate_content(prompt_parts)
        return response.text
    except Exception as e:
        return f"An error occurred while communicating with the Gemini API: {e}"

def display_referenced_pages(response_text, manual_name):
    """Parses page numbers from the response and displays their images."""
    page_numbers = re.findall(r'Pages? \s*([\d,\s]+)', response_text, re.IGNORECASE)
    
    unique_pages = set()
    if page_numbers:
        for num_group in page_numbers:
            for num in re.findall(r'\d+', num_group):
                unique_pages.add(int(num))

    if unique_pages:
        st.markdown("---")
        st.subheader("Referenced Pages:")
        
        sorted_pages = sorted(list(unique_pages))
        
        cols = st.columns(min(len(sorted_pages), 3))
        for i, page_num in enumerate(sorted_pages):
            image_path = os.path.join(PROCESSED_DATA_DIR, manual_name, f"page_{page_num}.png")
            if os.path.exists(image_path):
                with cols[i % len(cols)]:
                    # --- THIS IS THE FIX ---
                    st.image(image_path, caption=f"Reference: Page {page_num}", use_column_width='always')
            else:
                with cols[i % len(cols)]:
                    st.warning(f"Image for page {page_num} not found.")

# --- Streamlit UI Flow ---
manuals = get_available_manuals()

if not manuals:
    st.warning("No processed manuals found. Please run the `ingest_v2.py` script first and ensure the `processed_data` folder is in the repository.")
else:
    selected_manual_name = st.selectbox("**Select a Manual:**", manuals)
    
    if selected_manual_name:
        document_content = load_manual_data(selected_manual_name)
        
        if document_content:
            st.success(f"Loaded '{selected_manual_name}' manual with {len(document_content)} pages.")
            
            col1, col2 = st.columns(2)
            with col1:
                uploaded_image = st.camera_input("Take a picture to ask about (optional)")
            with col2:
                user_question = st.text_area("Ask a question about the manual:", height=150)

            if st.button("Get Answer", use_container_width=True):
                if not user_question:
                    st.error("Please ask a question.")
                else:
                    pil_image = Image.open(uploaded_image) if uploaded_image else None
                    full_context = "\n\n".join([f"Page {item['page']}:\n{item['content']}" for item in document_content])
                    
                    with st.spinner("🧠 AI is thinking..."):
                        answer = get_gemini_response(user_question, full_context, image=pil_image)
                        
                        st.markdown("---")
                        st.subheader("💬 Answer")
                        st.markdown(answer)
                        
                        display_referenced_pages(answer, selected_manual_name)