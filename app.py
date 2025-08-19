import streamlit as st
import google.generativeai as genai
import os
import json
import re
from PIL import Image
import io
from dotenv import load_dotenv

# --- Load Environment Variables (for local testing) ---
load_dotenv()

try:
    # Pillow >= 9.1 exposes Resampling
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except Exception:
    # Older Pillow versions: pick a reasonable fallback without raising at import time
    RESAMPLE_LANCZOS = getattr(Image, 'LANCZOS', getattr(Image, 'ANTIALIAS', getattr(Image, 'BICUBIC', 1)))


def process_image_for_upload(image_bytes, rotate=0, crop_pct=0, resize_pct=100, max_kb=2048, max_dim=1600):
    """Process raw image bytes: rotate, center-crop, resize and compress to meet max_kb.

    Returns a tuple (processed_bytes, pil_image).
    - image_bytes: original bytes
    - rotate, crop_pct, resize_pct: transforms (same semantics as the UI)
    - max_kb: target maximum size in KB (best-effort)
    - max_dim: maximum width/height in pixels to cap dimensions
    """
    try:
        pil = Image.open(io.BytesIO(image_bytes)).convert('RGB')

        # Rotate
        if rotate:
            pil = pil.rotate(rotate, expand=True)

        # Center crop
        if crop_pct and crop_pct > 0:
            w, h = pil.size
            cp = crop_pct / 100.0
            crop_w = int(w * cp)
            crop_h = int(h * cp)
            left = max(0, (w - crop_w) // 2)
            top = max(0, (h - crop_h) // 2)
            pil = pil.crop((left, top, left + crop_w, top + crop_h))

        # Resize by percent
        if resize_pct and resize_pct != 100:
            new_w = max(1, int(pil.width * resize_pct / 100.0))
            new_h = max(1, int(pil.height * resize_pct / 100.0))
            pil = pil.resize((new_w, new_h), RESAMPLE_LANCZOS)

        # Also cap maximum dimensions to avoid huge uploads
        if max_dim and max(pil.size) > max_dim:
            scale = max_dim / float(max(pil.size))
            new_w = max(1, int(pil.width * scale))
            new_h = max(1, int(pil.height * scale))
            pil = pil.resize((new_w, new_h), Image.LANCZOS)
            pil = pil.resize((new_w, new_h), RESAMPLE_LANCZOS)

        # Compress to meet max_kb (best-effort) by lowering JPEG quality
        target_bytes = max(1, int(max_kb * 1024))
        quality = 95
        buf = io.BytesIO()
        pil.save(buf, format='JPEG', quality=quality)
        data = buf.getvalue()

        # If already under target, return
        while len(data) > target_bytes and quality >= 30:
            quality -= 5
            buf = io.BytesIO()
            pil.save(buf, format='JPEG', quality=quality)
            data = buf.getvalue()

        # If still too large, downscale a bit and retry (avoid infinite loop)
        if len(data) > target_bytes:
            # downscale by 90% and try again a few times
            for _ in range(3):
                new_w = max(1, int(pil.width * 0.9))
                new_h = max(1, int(pil.height * 0.9))
                pil = pil.resize((new_w, new_h), RESAMPLE_LANCZOS)
                quality = max(20, quality - 5)
                buf = io.BytesIO()
                pil.save(buf, format='JPEG', quality=quality)
                data = buf.getvalue()
                if len(data) <= target_bytes:
                    break

        return data, pil
    except Exception as e:
        # On failure, return original bytes as best-effort
        return image_bytes, None

# --- Configuration & Initialization ---
PROCESSED_DATA_DIR = "processed_data"
st.set_page_config(page_title="AI Manual Assistant", page_icon="🤖", layout="wide")
st.title("🤖 AI Assistant for Technical Manuals")
st.write("Select a manual, then ask a question using text and/or an image.")

# --- Responsive styling and mobile layout switcher ---
# This injects CSS and a small JS snippet that adds `st-mobile` to the root
# when the viewport is narrow. CSS then targets common Streamlit column and
# image containers to force a single-column, mobile-first layout.
st.markdown(
    """
    <style>
    /* Make Streamlit-rendered images responsive */
    .stImage img,
    div[data-testid="stImage"] img {
        max-width: 100% !important;
        width: auto !important;
        height: auto !important;
        display: block !important;
        margin-left: auto !important;
        margin-right: auto !important;
    }

    /* Ensure image containers don't impose extra padding on narrow screens */
    .stImage, div[data-testid="stImage"] {
        width: 100% !important;
        max-width: 100% !important;
    }

    /* Mobile-first: when the document root has the st-mobile class, stack columns */
    html.st-mobile {
        /* Make any column children use full width */
    }

    /* Generic rule: any role=group (Streamlit columns) becomes column-oriented */
    html.st-mobile [role="group"] {
        display: flex !important;
        flex-direction: column !important;
        width: 100% !important;
    }

    /* Also ensure Streamlit's columns (common generated classes) expand to full width */
    html.st-mobile .stColumns > div,
    html.st-mobile .css-1lcbmhc > div,
    html.st-mobile .block-container .stColumns > div {
        width: 100% !important;
        max-width: 100% !important;
        flex: 0 0 auto !important;
    }

    /* Small tweak: make buttons and input take full width on mobile for easier tapping */
    html.st-mobile .stButton button,
    html.st-mobile textarea,
    html.st-mobile input[type="text"],
    html.st-mobile input[type="search"] {
        width: 100% !important;
        box-sizing: border-box !important;
    }
    </style>

    <script>
    // Add a class to the document root when viewport is narrow so CSS can switch layout
    (function(){
        function updateMobileClass(){
            try{
                if(window.innerWidth <= 700){
                    document.documentElement.classList.add('st-mobile');
                } else {
                    document.documentElement.classList.remove('st-mobile');
                }
            }catch(e){console && console.warn && console.warn(e)}
        }
        // Run on load and on resize
        updateMobileClass();
        window.addEventListener('resize', function(){
            // throttle using requestAnimationFrame for performance
            if(window.requestAnimationFrame){
                window.requestAnimationFrame(updateMobileClass);
            } else {
                updateMobileClass();
            }
        });
    })();
    </script>
    """,
    unsafe_allow_html=True,
)

# --- Chat memory (stored in session state) ---
if 'chat' not in st.session_state:
    # chat is a list of dicts: {role: 'user'|'assistant', 'text': str}
    st.session_state['chat'] = []

def add_chat_message(role, text):
    st.session_state['chat'].append({'role': role, 'text': text})

def clear_chat():
    st.session_state['chat'] = []


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

def get_gemini_response(question, context, chat_history=None, image=None):
    """Queries the Gemini model with text, context, recent chat history, and optional image."""
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')

        # Build a combined prompt: context + recent chat + current question
        history_text = "\n".join([f"User: {m['text']}" if m['role']=='user' else f"Assistant: {m['text']}" for m in (chat_history or [])])

        prompt_parts = [
            """
            You are an expert assistant specialized in analyzing technical manuals for complex machinery like ultrasound equipment.
            Your task is to answer the user's question based ONLY on the provided context from the manual and the recent conversation below.
            If the user provides an image, use it as part of their query (e.g., "What is this button?" with an image of a button).
            After providing the answer, you MUST cite the specific page number(s) where you found the information.
            Format your citation clearly at the end of your answer, for example: (Source: Page 15) or (Source: Pages 28, 32).

            CONTEXT FROM MANUAL:
            {context}

            RECENT CONVERSATION:
            {history}

            CURRENT QUESTION:
            {question}

            ASSISTANT'S ANSWER:
            """.replace('{context}', context).replace('{history}', history_text).replace('{question}', question)
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
                    # Image sizing: use sidebar slider setting (0 -> responsive container width)
                    img_w = st.session_state.get('image_width_px', 0)
                    if img_w == 0:
                        st.image(image_path, caption=f"Reference: Page {page_num}", use_container_width=True)
                    else:
                        st.image(image_path, caption=f"Reference: Page {page_num}", width=int(img_w))
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

            # Sidebar: show conversation and clear control + image transform controls
            with st.sidebar:
                st.header("Conversation")
                # Image sizing control (0 => responsive container width)
                st.subheader("Image display")
                st.slider("Image width (px, 0 = container width)", 0, 1200, 0, key='image_width_px', help="Set 0 to use full container width (responsive)")
                # Validation / preview controls
                st.subheader("Image validation & edit")
                st.number_input("Max image size (KB)", min_value=100, max_value=10000, value=2048, key='max_image_kb')
                st.slider("Rotate (degrees)", -180, 180, 0, key='image_rotate')
                st.slider("Crop (center %) — 0 = no crop", 0, 100, 0, key='image_crop_pct')
                st.slider("Resize (%) — 100 = original", 10, 200, 100, key='image_resize_pct')
                if st.button("Clear conversation"):
                    clear_chat()
                if st.session_state['chat']:
                    for msg in st.session_state['chat']:
                        if msg['role'] == 'user':
                            st.markdown(f"**You:** {msg['text']}")
                        else:
                            st.markdown(f"**Assistant:** {msg['text']}")
                else:
                    st.info("No conversation yet. Ask a question to start.")

            col1, col2 = st.columns(2)
            with col1:
                uploaded_image = st.camera_input("Take a picture to ask about (optional)")
                uploaded_file = st.file_uploader("Or upload a photo from your device", type=["png", "jpg", "jpeg"], key='uploaded_file')

                # Build image bytes from the preferred source for preview and validation
                image_bytes = None
                if uploaded_file is not None:
                    try:
                        uploaded_file.seek(0)
                    except Exception:
                        pass
                    image_bytes = uploaded_file.read()
                elif uploaded_image is not None:
                    try:
                        uploaded_image.seek(0)
                    except Exception:
                        pass
                    image_bytes = uploaded_image.read()

                # If an image is selected, show its size and a live preview applying rotate/crop/resize
                processed_preview = None
                if image_bytes:
                    size_kb = len(image_bytes) / 1024
                    st.write(f"Selected image size: {size_kb:.1f} KB")
                    max_kb = st.session_state.get('max_image_kb', 2048)
                    if size_kb > max_kb:
                        st.warning(f"Image exceeds maximum size of {max_kb} KB. Please upload a smaller image or use resize.")
                    try:
                        # Use helper to apply all transforms and compress to max size
                        rotate = st.session_state.get('image_rotate', 0)
                        crop_pct = st.session_state.get('image_crop_pct', 0)
                        resize_pct = st.session_state.get('image_resize_pct', 100)
                        max_kb = st.session_state.get('max_image_kb', 2048)

                        processed_bytes, pil = process_image_for_upload(
                            image_bytes,
                            rotate=rotate,
                            crop_pct=crop_pct,
                            resize_pct=resize_pct,
                            max_kb=max_kb,
                        )

                        processed_preview = pil
                        if processed_preview is not None:
                            st.image(processed_preview, caption=f"Preview (≈{len(processed_bytes)//1024} KB)", use_container_width=True)
                        else:
                            st.warning("Preview unavailable for this image.")
                    except Exception as e:
                        st.error(f"Error processing image preview: {e}")
                # (Removed explicit camera trigger button — use the native camera widget or uploader)
            with col2:
                user_question = st.text_area("Ask a question about the manual:", height=150)

            if st.button("Get Answer", use_container_width=True):
                if not user_question:
                    st.error("Please ask a question.")
                else:
                    # Append user's question to chat memory
                    add_chat_message('user', user_question)

                    # Prefer an explicit uploaded file over the camera input if provided
                    image_source = uploaded_file if (uploaded_file is not None) else uploaded_image
                    pil_image = None
                    if image_source is not None:
                        try:
                            # Recreate processed version to send (same transforms as preview)
                            if image_bytes is None:
                                try:
                                    image_source.seek(0)
                                except Exception:
                                    pass
                                image_bytes2 = image_source.read()
                            else:
                                image_bytes2 = image_bytes

                            # Use helper to apply transforms and compress to max size before sending
                            rotate = st.session_state.get('image_rotate', 0)
                            crop_pct = st.session_state.get('image_crop_pct', 0)
                            resize_pct = st.session_state.get('image_resize_pct', 100)
                            max_kb = st.session_state.get('max_image_kb', 2048)

                            processed_bytes2, pil_image = process_image_for_upload(
                                image_bytes2,
                                rotate=rotate,
                                crop_pct=crop_pct,
                                resize_pct=resize_pct,
                                max_kb=max_kb,
                            )
                        except Exception as e:
                            st.error(f"Error preparing image for model: {e}")
                    full_context = "\n\n".join([f"Page {item['page']}:\n{item['content']}" for item in document_content])

                    # Use the most recent messages as context (limit to last 10)
                    recent_history = st.session_state['chat'][-10:]

                    with st.spinner("🧠 AI is thinking..."):
                        answer = get_gemini_response(user_question, full_context, chat_history=recent_history, image=pil_image)

                        # Append assistant reply to chat memory
                        add_chat_message('assistant', answer)

                        st.markdown("---")
                        st.subheader("💬 Answer")
                        st.markdown(answer)

                        display_referenced_pages(answer, selected_manual_name)