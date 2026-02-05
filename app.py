import streamlit as st
import os
import sys
from pathlib import Path
import tempfile
import shutil
from gtts import gTTS
import time
import urllib.request
import zipfile
import subprocess

st.set_page_config(
    page_title="AI Avatar Generator",
    page_icon="🎬",
    layout="wide"
)

st.markdown("# 🎬 AI Avatar Generator")
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

def check_sadtalker():
    """Check if SadTalker is set up"""
    sadtalker_path = Path("SadTalker")
    
    if not sadtalker_path.exists():
        return False, "Not downloaded"
    
    checkpoints = sadtalker_path / "checkpoints"
    if not checkpoints.exists() or len(list(checkpoints.glob("*"))) < 3:
        return False, "Models not downloaded"
    
    return True, "Ready"

def patch_numpy_warning():
    """Fix numpy VisibleDeprecationWarning issue"""
    preprocess_file = Path("SadTalker/src/face3d/util/preprocess.py")
    
    if not preprocess_file.exists():
        return False
    
    # Read file
    with open(preprocess_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if already patched
    if 'PATCHED_NUMPY_WARNING' in content:
        return True
    
    # Replace the problematic line
    old_line = 'warnings.filterwarnings("ignore", category=np.VisibleDeprecationWarning)'
    new_line = '''# PATCHED_NUMPY_WARNING
try:
    warnings.filterwarnings("ignore", category=np.VisibleDeprecationWarning)
except AttributeError:
    # numpy 2.0+ removed VisibleDeprecationWarning
    pass'''
    
    if old_line in content:
        content = content.replace(old_line, new_line)
        
        # Write back
        with open(preprocess_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return True
    
    return False

def download_sadtalker():
    """Download and setup SadTalker"""
    status = st.empty()
    progress = st.progress(0)
    
    try:
        # Download ZIP
        status.info("📥 Downloading SadTalker (1-2 minutes)...")
        progress.progress(10)
        
        zip_url = "https://github.com/OpenTalker/SadTalker/archive/refs/heads/main.zip"
        zip_path = "sadtalker.zip"
        
        urllib.request.urlretrieve(zip_url, zip_path)
        
        # Extract
        status.info("📦 Extracting files...")
        progress.progress(30)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(".")
        
        # Rename folder
        if Path("SadTalker-main").exists():
            if Path("SadTalker").exists():
                shutil.rmtree("SadTalker")
            Path("SadTalker-main").rename("SadTalker")
        
        os.remove(zip_path)
        
        # Patch numpy warning BEFORE installing
        status.info("🔧 Patching numpy compatibility...")
        progress.progress(40)
        patch_numpy_warning()
        
        # Install requirements
        status.info("📦 Installing packages (3-5 minutes)...")
        progress.progress(50)
        
        # Install numpy first
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "numpy==1.23.5"],
            capture_output=True,
            timeout=300
        )
        
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "SadTalker/requirements.txt"],
            capture_output=True,
            timeout=600
        )
        
        # Download models
        status.info("⬇️ Downloading AI models (5-10 minutes, ~2GB)...")
        progress.progress(70)
        
        download_script = Path("SadTalker/scripts/download_models.py")
        if download_script.exists():
            subprocess.run(
                [sys.executable, str(download_script)],
                cwd="SadTalker",
                timeout=900
            )
        
        progress.progress(100)
        status.success("✅ Setup complete!")
        time.sleep(2)
        status.empty()
        progress.empty()
        
        return True
        
    except Exception as e:
        status.error(f"❌ Setup failed: {str(e)}")
        return False

# Check status
sadtalker_ready, status_msg = check_sadtalker()

# Patch numpy if SadTalker exists but not patched
if sadtalker_ready:
    if patch_numpy_warning():
        st.sidebar.success("✅ Numpy compatibility patched")

if not sadtalker_ready:
    st.warning(f"⚠️ Setup Required - Status: {status_msg}")
    
    st.markdown("### 🚀 Quick Setup")
    st.info("Click the button below to automatically download and set up everything (10-15 minutes)")
    
    if st.button("📥 Download & Setup SadTalker", type="primary"):
        if download_sadtalker():
            st.success("✅ Setup complete! Refreshing page...")
            time.sleep(2)
            st.rerun()
    
    st.markdown("---")
    st.markdown("### 🌐 Or Use Google Colab Instead")
    st.info("Google Colab works perfectly and requires no installation!")
    
    with st.expander("📋 Google Colab Code (Click to Expand)"):
        st.code('''
# Paste this in Google Colab: https://colab.research.google.com/

your_text = "Hello! This is my AI avatar."

# Fix numpy
!pip install -q numpy==1.23.5

# Download SadTalker
!git clone https://github.com/OpenTalker/SadTalker.git
%cd SadTalker

# Patch numpy warning
import fileinput
for line in fileinput.input('src/face3d/util/preprocess.py', inplace=True):
    if 'np.VisibleDeprecationWarning' in line:
        print('    pass  # Patched for numpy 2.0+')
    else:
        print(line, end='')

# Install & setup
!pip install -q -r requirements.txt
!pip install -q gTTS
!bash scripts/download_models.sh

# Upload photo
from google.colab import files
uploaded = files.upload()
photo = list(uploaded.keys())[0]

# Generate
from gtts import gTTS
tts = gTTS(text=your_text, lang='en')
tts.save('speech.mp3')

!python inference.py \\
  --driven_audio speech.mp3 \\
  --source_image {photo} \\
  --result_dir ./results \\
  --still --preprocess full

# Download
import glob
videos = glob.glob('./results/**/*.mp4', recursive=True)
if videos:
    files.download(videos[0])
        ''', language='python')
    
    st.stop()

# Main interface
st.success("✅ System Ready")

col1, col2 = st.columns([1, 1])

with col1:
    st.markdown("### 📷 Upload Photo")
    uploaded_image = st.file_uploader(
        "Choose a photo (JPG, PNG)",
        type=['jpg', 'jpeg', 'png']
    )
    
    if uploaded_image:
        st.image(uploaded_image, use_column_width=True)

with col2:
    st.markdown("### 📝 Enter Text")
    text_input = st.text_area(
        "What should your avatar say?",
        height=200,
        placeholder="Example: Hello! Welcome to my channel..."
    )
    
    st.caption(f"Characters: {len(text_input)}")

st.markdown("---")

def generate_speech(text, lang, speed, output_path):
    """Generate speech"""
    slow = (speed == "Slow")
    tts = gTTS(text=text, lang=lang, slow=slow)
    tts.save(output_path)
    return output_path

def create_video(image_path, audio_path, expression_scale):
    """Create video"""
    sadtalker_path = Path("SadTalker")
    results_dir = sadtalker_path / "results"
    
    if results_dir.exists():
        shutil.rmtree(results_dir)
    results_dir.mkdir()
    
    cmd = [
        sys.executable,
        "inference.py",
        "--driven_audio", str(audio_path),
        "--source_image", str(image_path),
        "--result_dir", str(results_dir),
        "--still",
        "--preprocess", "full",
        "--expression_scale", str(expression_scale)
    ]
    
    result = subprocess.run(
        cmd,
        cwd=str(sadtalker_path),
        capture_output=True,
        text=True,
        timeout=300
    )
    
    if result.returncode != 0:
        raise Exception(f"Generation failed: {result.stderr}")
    
    video_files = list(results_dir.rglob("*.mp4"))
    if not video_files:
        raise Exception("No video generated")
    
    return max(video_files, key=lambda p: p.stat().st_mtime)

if st.button("🎬 Generate Video", type="primary"):
    
    if not uploaded_image:
        st.error("❌ Please upload a photo!")
    elif not text_input or len(text_input.strip()) < 5:
        st.error("❌ Please enter text (min 5 characters)!")
    else:
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                progress = st.progress(0)
                status = st.empty()
                
                # Save image
                status.text("📷 Processing image...")
                progress.progress(20)
                
                image_path = temp_path / "input.jpg"
                with open(image_path, "wb") as f:
                    f.write(uploaded_image.getbuffer())
                
                # Generate speech
                status.text("🎤 Generating speech...")
                progress.progress(40)
                
                audio_path = temp_path / "speech.mp3"
                generate_speech(text_input, language, voice_speed, audio_path)
                
                # Generate video
                status.text("🎬 Creating video (1-3 minutes)...")
                progress.progress(60)
                
                video_file = create_video(image_path, audio_path, expression_scale)
                
                # Save
                status.text("💾 Saving...")
                progress.progress(90)
                
                output_dir = Path("outputs")
                output_dir.mkdir(exist_ok=True)
                
                final_video = output_dir / f"video_{int(time.time())}.mp4"
                shutil.copy(video_file, final_video)
                
                progress.progress(100)
                status.empty()
                
                st.session_state.video_generated = True
                st.session_state.video_path = str(final_video)
                
                st.success("✅ Video generated!")
                time.sleep(1)
                st.rerun()
                
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            with st.expander("🔍 Error Details"):
                import traceback
                st.code(traceback.format_exc())

# Show video
if st.session_state.video_generated and st.session_state.video_path:
    st.markdown("---")
    st.markdown("## 🎉 Video Ready!")
    
    video_path = st.session_state.video_path
    
    if os.path.exists(video_path):
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.video(video_path)
        
        with col2:
            with open(video_path, "rb") as f:
                st.download_button(
                    label="⬇️ Download Video",
                    data=f,
                    file_name="ai_avatar.mp4",
                    mime="video/mp4"
                )
            
            if st.button("🔄 Create Another"):
                st.session_state.video_generated = False
                st.session_state.video_path = None
                st.rerun()

st.markdown("---")
st.markdown("<div style='text-align: center; color: #666;'><p>Made with ❤️ using Streamlit</p></div>", unsafe_allow_html=True)
