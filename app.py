import streamlit as st
import os
import sys
import subprocess
from pathlib import Path
import tempfile
import shutil
from gtts import gTTS
import time

st.set_page_config(
    page_title="HeyGen Clone - AI Avatar Generator",
    page_icon="🎬",
    layout="wide"
)

# Custom CSS
st.markdown("""
    <style>
    .main {
        padding: 2rem;
    }
    .stButton>button {
        width: 100%;
        background-color: #FF4B4B;
        color: white;
        height: 3rem;
        font-size: 1.2rem;
        font-weight: bold;
    }
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #D4EDDA;
        color: #155724;
        margin: 1rem 0;
    }
    </style>
""", unsafe_allow_html=True)

# Title
st.markdown("# 🎬 HeyGen Clone - AI Avatar Generator")
st.markdown("### Create talking avatar videos from photos + text")
st.markdown("---")

# Initialize session state
if 'video_generated' not in st.session_state:
    st.session_state.video_generated = False
if 'video_path' not in st.session_state:
    st.session_state.video_path = None

# Sidebar
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    
    language = st.selectbox(
        "🌍 Language",
        ["en", "es", "fr", "de", "it", "pt", "ru", "zh-CN", "ja", "ko"],
        index=0
    )
    
    voice_speed = st.select_slider(
        "🎤 Voice Speed",
        options=["Slow", "Normal", "Fast"],
        value="Normal"
    )
    
    expression_scale = st.slider(
        "😊 Expression Strength",
        min_value=0.5,
        max_value=2.0,
        value=1.0,
        step=0.1
    )
    
    enhance_face = st.checkbox("✨ Enhance Face Quality", value=True)
    
    st.markdown("---")
    st.markdown("### 📖 How to Use")
    st.markdown("""
    1. Upload a clear photo
    2. Enter your text
    3. Click Generate
    4. Wait 2-3 minutes
    5. Download video!
    """)
    
    st.markdown("---")
    st.markdown("### 💡 Tips")
    st.markdown("""
    - Use front-facing photos
    - Good lighting helps
    - Keep text under 200 words
    - First generation downloads models (5 min)
    """)

# Main content
col1, col2 = st.columns([1, 1])

with col1:
    st.markdown("### 📷 Upload Photo")
    uploaded_image = st.file_uploader(
        "Choose a photo (JPG, PNG)",
        type=['jpg', 'jpeg', 'png'],
        help="Upload a clear, front-facing photo for best results"
    )
    
    if uploaded_image:
        st.image(uploaded_image, caption="Your Photo", use_column_width=True)

with col2:
    st.markdown("### 📝 Enter Text")
    text_input = st.text_area(
        "What should your avatar say?",
        height=200,
        placeholder="Example: Hello! Welcome to my channel. Today I'm going to show you something amazing...",
        help="Enter the text you want your avatar to speak"
    )
    
    char_count = len(text_input)
    st.caption(f"Characters: {char_count} {'⚠️ (Keep under 500 for best results)' if char_count > 500 else ''}")

# Generate button
st.markdown("---")

def generate_speech(text, lang, speed, output_path):
    """Generate speech from text"""
    slow = (speed == "Slow")
    tts = gTTS(text=text, lang=lang, slow=slow)
    tts.save(output_path)
    return output_path

def setup_sadtalker():
    """Check and setup SadTalker"""
    sadtalker_path = Path("SadTalker")
    
    if not sadtalker_path.exists():
        st.error("⚠️ SadTalker not found. Please set up the environment first.")
        st.code("""
# Run these commands in your terminal:
git clone https://github.com/OpenTalker/SadTalker.git
cd SadTalker
pip install -r requirements.txt
bash scripts/download_models.sh
        """)
        return None
    
    checkpoints = sadtalker_path / "checkpoints"
    if not checkpoints.exists() or not list(checkpoints.glob("*")):
        st.error("⚠️ Models not downloaded. Run: bash scripts/download_models.sh")
        return None
    
    return sadtalker_path

def create_video(image_path, audio_path, sadtalker_path, expression_scale, enhance):
    """Create talking video using SadTalker"""
    
    results_dir = sadtalker_path / "results"
    if results_dir.exists():
        shutil.rmtree(results_dir)
    results_dir.mkdir()
    
    enhancer = "gfpgan" if enhance else "none"
    
    cmd = [
        sys.executable,
        "inference.py",
        "--driven_audio", str(audio_path),
        "--source_image", str(image_path),
        "--result_dir", str(results_dir),
        "--still",
        "--preprocess", "full",
        "--expression_scale", str(expression_scale),
        "--enhancer", enhancer
    ]
    
    # Run SadTalker
    result = subprocess.run(
        cmd,
        cwd=str(sadtalker_path),
        capture_output=True,
        text=True,
        timeout=300
    )
    
    if result.returncode != 0:
        raise Exception(f"SadTalker failed: {result.stderr}")
    
    # Find generated video
    video_files = list(results_dir.rglob("*.mp4"))
    if not video_files:
        raise Exception("No video generated")
    
    return max(video_files, key=lambda p: p.stat().st_mtime)

# Generate button
if st.button("🎬 Generate Video", type="primary"):
    
    if not uploaded_image:
        st.error("❌ Please upload a photo!")
    elif not text_input or len(text_input.strip()) < 5:
        st.error("❌ Please enter text (at least 5 characters)!")
    else:
        try:
            # Create temp directory
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                # Progress bar
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # Save uploaded image
                status_text.text("📷 Processing image...")
                progress_bar.progress(10)
                
                image_path = temp_path / "input_image.jpg"
                with open(image_path, "wb") as f:
                    f.write(uploaded_image.getbuffer())
                
                # Generate speech
                status_text.text("🎤 Generating speech...")
                progress_bar.progress(30)
                
                audio_path = temp_path / "speech.mp3"
                generate_speech(text_input, language, voice_speed, audio_path)
                
                # Setup SadTalker
                status_text.text("🔧 Setting up video generator...")
                progress_bar.progress(40)
                
                sadtalker_path = setup_sadtalker()
                if not sadtalker_path:
                    st.stop()
                
                # Generate video
                status_text.text("🎬 Creating video (this takes 1-3 minutes)...")
                progress_bar.progress(50)
                
                video_file = create_video(
                    image_path,
                    audio_path,
                    sadtalker_path,
                    expression_scale,
                    enhance_face
                )
                
                # Copy to permanent location
                status_text.text("💾 Saving video...")
                progress_bar.progress(90)
                
                output_dir = Path("outputs")
                output_dir.mkdir(exist_ok=True)
                
                final_video = output_dir / f"video_{int(time.time())}.mp4"
                shutil.copy(video_file, final_video)
                
                # Complete
                progress_bar.progress(100)
                status_text.text("✅ Video generated successfully!")
                
                # Store in session state
                st.session_state.video_generated = True
                st.session_state.video_path = str(final_video)
                
                # Auto-rerun to show video
                st.rerun()
                
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            import traceback
            with st.expander("🔍 View Error Details"):
                st.code(traceback.format_exc())

# Display generated video
if st.session_state.video_generated and st.session_state.video_path:
    st.markdown("---")
    st.markdown("## 🎉 Video Generated Successfully!")
    
    video_path = st.session_state.video_path
    
    if os.path.exists(video_path):
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.video(video_path)
        
        with col2:
            st.markdown("### 📥 Download")
            with open(video_path, "rb") as f:
                st.download_button(
                    label="⬇️ Download Video",
                    data=f,
                    file_name="ai_avatar_video.mp4",
                    mime="video/mp4"
                )
            
            file_size = os.path.getsize(video_path) / (1024 * 1024)
            st.info(f"📊 Size: {file_size:.1f} MB")
            
            if st.button("🔄 Create Another Video"):
                st.session_state.video_generated = False
                st.session_state.video_path = None
                st.rerun()

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p>Made with ❤️ using Streamlit | Powered by SadTalker</p>
    <p>⚠️ For educational purposes only</p>
</div>
""", unsafe_allow_html=True)
