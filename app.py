import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
import zipfile
import re

# ─────────────────────────────────────────────
# Page Configuration
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Bulk PDF Downloader & Link Extractor",
    page_icon="📥",
    layout="wide"
)

# ─────────────────────────────────────────────
# Session State Initialization
# ─────────────────────────────────────────────
if 'found_pdfs' not in st.session_state:
    st.session_state.found_pdfs = []
if 'downloaded_pdfs' not in st.session_state:
    st.session_state.downloaded_pdfs = {}  # filename -> bytes
if 'txt_output' not in st.session_state:
    st.session_state.txt_output = ""
if 'scan_done' not in st.session_state:
    st.session_state.scan_done = False


# ─────────────────────────────────────────────
# Core Functions
# ─────────────────────────────────────────────

def get_session_with_headers():
    """
    Create a requests session that mimics a real browser.
    This bypasses basic bot-detection on public websites.
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept': (
            'text/html,application/xhtml+xml,'
            'application/xml;q=0.9,*/*;q=0.8'
        ),
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })
    return session


def extract_pdf_links(url, session):
    """
    Given a webpage URL, fetch it and extract all PDF links.
    
    Strategy:
    1. Fetch page HTML
    2. Parse all <a> tags with href ending in .pdf
    3. Also check for links containing 'download' or 'pdf' 
       in query params
    4. Return list of absolute PDF URLs
    """
    pdf_links = []

    try:
        response = session.get(url, timeout=30, allow_redirects=True)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to fetch page: {e}")
        return pdf_links

    soup = BeautifulSoup(response.text, 'html.parser')

    # ── Find all anchor tags ──
    for tag in soup.find_all('a', href=True):
        href = tag['href'].strip()

        # Skip empty, javascript, and anchor-only links
        if not href or href.startswith('#') or href.startswith('javascript'):
            continue

        # Convert to absolute URL
        absolute_url = urljoin(url, href)

        # ── Check if link points to a PDF ──
        # Method 1: URL path ends with .pdf
        parsed = urlparse(absolute_url)
        path_lower = parsed.path.lower()

        if path_lower.endswith('.pdf'):
            pdf_links.append(absolute_url)
            continue

        # Method 2: Query params contain .pdf
        if '.pdf' in parsed.query.lower():
            pdf_links.append(absolute_url)
            continue

        # Method 3: Link text or title suggests PDF
        link_text = tag.get_text(strip=True).lower()
        title = tag.get('title', '').lower()
        onclick = tag.get('onclick', '').lower()

        if any(
            keyword in attr
            for keyword in ['pdf', 'download', 'annual report', 'quarterly']
            for attr in [link_text, title, onclick]
        ):
            # Only add if URL looks like it could serve a file
            if any(
                ext in absolute_url.lower()
                for ext in ['.pdf', 'download', 'getfile', 'document']
            ):
                pdf_links.append(absolute_url)

    # ── Also check for embedded objects / iframes ──
    for tag in soup.find_all(['embed', 'iframe', 'object'], src=True):
        src = tag.get('src', '') or tag.get('data', '')
        if src and '.pdf' in src.lower():
            pdf_links.append(urljoin(url, src))

    # ── Deduplicate while preserving order ──
    seen = set()
    unique_links = []
    for link in pdf_links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)

    return unique_links


def download_single_pdf(pdf_url, session, index):
    """
    Download a single PDF file. Returns tuple of
    (filename, bytes_content, success_bool, error_msg).
    """
    try:
        response = session.get(pdf_url, timeout=60, stream=True)
        response.raise_for_status()

        # ── Determine filename ──
        # Try Content-Disposition header first
        filename = None
        cd = response.headers.get('Content-Disposition', '')
        if 'filename' in cd:
            # Extract filename from header
            match = re.findall(r'filename[^;=\n]*=([\"\']?)(.+?)\1(;|$)', cd)
            if match:
                filename = match[0][1].strip()

        # Fallback: extract from URL path
        if not filename:
            parsed_path = urlparse(pdf_url).path
            filename = os.path.basename(parsed_path)

        # Fallback: generate generic name
        if not filename or not filename.endswith('.pdf'):
            filename = f"document_{index:03d}.pdf"

        # ── Clean filename ──
        # Remove special characters that break file systems
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = filename.strip()

        # ── Read content ──
        content = response.content

        # ── Verify it's actually a PDF ──
        content_type = response.headers.get('Content-Type', '').lower()
        is_pdf = (
            content[:4] == b'%PDF'
            or 'pdf' in content_type
        )

        if not is_pdf:
            return (filename, None, False, "Not a valid PDF file")

        return (filename, content, True, None)

    except Exception as e:
        return (f"document_{index:03d}.pdf", None, False, str(e))


def download_all_pdfs(pdf_urls, session, max_workers=5, progress_bar=None):
    """
    Download all PDFs in parallel.
    Returns dict of {filename: bytes} for successful downloads.
    """
    downloaded = {}
    errors = []
    total = len(pdf_urls)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                download_single_pdf, url, session, idx
            ): (url, idx)
            for idx, url in enumerate(pdf_urls, 1)
        }

        completed = 0
        for future in as_completed(future_map):
            url, idx = future_map[future]
            filename, content, success, error = future.result()

            completed += 1
            if progress_bar:
                progress_bar.progress(
                    completed / total,
                    text=f"Downloading {completed}/{total}: {filename}"
                )

            if success and content:
                # Handle duplicate filenames
                original_name = filename
                counter = 1
                while filename in downloaded:
                    name, ext = os.path.splitext(original_name)
                    filename = f"{name}_{counter}{ext}"
                    counter += 1

                downloaded[filename] = content
            else:
                errors.append({
                    'url': url,
                    'filename': filename,
                    'error': error
                })

    return downloaded, errors


def create_zip_from_memory(files_dict):
    """
    Create ZIP file in memory from dict of {filename: bytes}.
    """
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files_dict.items():
            zf.writestr(filename, content)
    zip_buffer.seek(0)
    return zip_buffer


def generate_txt_report(page_url, pdf_links, downloaded, errors):
    """
    Generate a .txt file listing all found PDF URLs
    and download status.
    """
    lines = []
    lines.append("=" * 70)
    lines.append("BULK PDF DOWNLOAD REPORT")
    lines.append("=" * 70)
    lines.append(f"Source Page : {page_url}")
    lines.append(f"Scan Date  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Total Found: {len(pdf_links)}")
    lines.append(f"Downloaded : {len(downloaded)}")
    lines.append(f"Failed     : {len(errors)}")
    lines.append("=" * 70)
    lines.append("")

    lines.append("─── ALL PDF LINKS FOUND ───")
    lines.append("")
    for i, link in enumerate(pdf_links, 1):
        lines.append(f"  {i:3d}. {link}")
    lines.append("")

    if downloaded:
        lines.append("─── SUCCESSFULLY DOWNLOADED ───")
        lines.append("")
        for filename in sorted(downloaded.keys()):
            size_kb = len(downloaded[filename]) / 1024
            lines.append(f"  ✓ {filename} ({size_kb:.1f} KB)")
        lines.append("")

    if errors:
        lines.append("─── FAILED DOWNLOADS ───")
        lines.append("")
        for err in errors:
            lines.append(f"  ✗ {err['url']}")
            lines.append(f"    Error: {err['error']}")
        lines.append("")

    lines.append("=" * 70)
    lines.append("END OF REPORT")
    lines.append("=" * 70)

    return "\n".join(lines)


# ─────────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────────

st.title("📥 Bulk PDF Downloader & Link Extractor")
st.markdown(
    "Paste a webpage URL → App finds **all PDF links** → "
    "Downloads them in bulk → Gives you **ZIP + TXT report**"
)

# ── Main Tabs ──
tab1, tab2 = st.tabs([
    "🔍 Scan & Download from Webpage",
    "📋 Paste PDF URLs Directly"
])

# ════════════════════════════════════════════
# TAB 1: SCAN WEBPAGE FOR PDFs
# ════════════════════════════════════════════
with tab1:
    st.header("Step 1: Enter Webpage URL")
    st.markdown(
        "Paste the investor/documents page URL. "
        "The app will scan it and find all PDF links."
    )

    page_url = st.text_input(
        "Webpage URL",
        placeholder="https://www.shriramfinance.in/investors/investor-information",
        help="Paste the page that contains PDF download links"
    )

    col_settings_1, col_settings_2 = st.columns(2)
    with col_settings_1:
        max_workers = st.slider(
            "Parallel downloads", 1, 10, 5,
            help="Higher = faster but more resource intensive"
        )
    with col_settings_2:
        timeout_seconds = st.slider(
            "Timeout per PDF (seconds)", 15, 120, 60
        )

    # ── SCAN BUTTON ──
    if st.button("🔍 Scan for PDFs", key="scan_page", type="primary"):
        if not page_url.strip():
            st.error("Please enter a URL!")
        else:
            with st.spinner("Scanning page for PDF links..."):
                session = get_session_with_headers()
                found = extract_pdf_links(page_url.strip(), session)

            if found:
                st.session_state.found_pdfs = found
                st.session_state.scan_done = True
                st.success(f"✅ Found **{len(found)}** PDF links!")
            else:
                st.warning(
                    "No PDF links found on this page. "
                    "The site might load PDFs via JavaScript. "
                    "Try Tab 2 to paste URLs directly."
                )
                st.session_state.found_pdfs = []
                st.session_state.scan_done = False

    # ── SHOW FOUND PDFs ──
    if st.session_state.scan_done and st.session_state.found_pdfs:
        st.header("Step 2: Review Found PDFs")

        # Show as dataframe for easy review
        pdf_data = []
        for i, link in enumerate(st.session_state.found_pdfs, 1):
            parsed = urlparse(link)
            name = os.path.basename(parsed.path) or f"document_{i}.pdf"
            pdf_data.append({
                "Select": True,
                "#": i,
                "Filename": name,
                "URL": link
            })

        # Let user see all links
        with st.expander(
            f"📄 View all {len(st.session_state.found_pdfs)} PDF links",
            expanded=True
        ):
            for item in pdf_data:
                st.text(f"{item['#']:3d}. {item['Filename']}")
                st.caption(f"     {item['URL']}")

        # ── Quick TXT download of just the links ──
        txt_links = "\n".join(st.session_state.found_pdfs)
        st.download_button(
            label="📝 Download PDF Links as .TXT",
            data=txt_links,
            file_name=f"pdf_links_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain",
            help="Just the list of PDF URLs, one per line"
        )

        st.header("Step 3: Download All PDFs")

        if st.button(
            f"⬇️ Download All {len(st.session_state.found_pdfs)} PDFs",
            key="download_all",
            type="primary"
        ):
            session = get_session_with_headers()
            progress_bar = st.progress(0, text="Starting downloads...")
            status_container = st.empty()

            downloaded, errors = download_all_pdfs(
                st.session_state.found_pdfs,
                session,
                max_workers=max_workers,
                progress_bar=progress_bar
            )

            progress_bar.progress(1.0, text="Done!")

            # Store results
            st.session_state.downloaded_pdfs = downloaded

            # Generate report
            report_txt = generate_txt_report(
                page_url,
                st.session_state.found_pdfs,
                downloaded,
                errors
            )
            st.session_state.txt_output = report_txt

            # ── Show Results ──
            col_r1, col_r2 = st.columns(2)
            with col_r1:
                st.metric("✅ Downloaded", len(downloaded))
            with col_r2:
                st.metric("❌ Failed", len(errors))

            if errors:
                with st.expander("Show failed downloads"):
                    for err in errors:
                        st.text(f"✗ {err['url']}")
                        st.caption(f"  Error: {err['error']}")

            # ── DOWNLOAD BUTTONS ──
            st.markdown("---")
            st.header("📦 Get Your Files")

            dl_col1, dl_col2, dl_col3 = st.columns(3)

            with dl_col1:
                if downloaded:
                    zip_data = create_zip_from_memory(downloaded)
                    st.download_button(
                        label=f"📦 Download ZIP ({len(downloaded)} PDFs)",
                        data=zip_data,
                        file_name=(
                            f"pdfs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                        ),
                        mime="application/zip",
                        type="primary"
                    )

            with dl_col2:
                st.download_button(
                    label="📝 Download Report (.TXT)",
                    data=report_txt,
                    file_name=(
                        f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    ),
                    mime="text/plain"
                )

            with dl_col3:
                # Individual file list
                with st.expander("Download individual PDFs"):
                    for fname, content in downloaded.items():
                        size_kb = len(content) / 1024
                        st.download_button(
                            label=f"⬇️ {fname} ({size_kb:.1f} KB)",
                            data=content,
                            file_name=fname,
                            mime="application/pdf",
                            key=f"dl_{fname}"
                        )


# ════════════════════════════════════════════
# TAB 2: PASTE PDF URLs DIRECTLY
# ════════════════════════════════════════════
with tab2:
    st.header("Paste PDF URLs Directly")
    st.markdown(
        "If the webpage uses JavaScript to load PDFs and "
        "auto-scan didn't work, paste PDF URLs here manually."
    )

    direct_urls = st.text_area(
        "PDF URLs (one per line)",
        height=250,
        placeholder=(
            "https://example.com/report1.pdf\n"
            "https://example.com/report2.pdf\n"
            "https://example.com/annual-report-2024.pdf"
        )
    )

    direct_workers = st.slider(
        "Parallel downloads",
        1, 10, 5,
        key="direct_workers"
    )

    if st.button("⬇️ Download All", key="download_direct", type="primary"):
        urls = [
            u.strip()
            for u in direct_urls.strip().split('\n')
            if u.strip()
        ]

        if not urls:
            st.error("Please paste at least one URL!")
        else:
            session = get_session_with_headers()
            progress_bar = st.progress(0, text="Starting...")

            downloaded, errors = download_all_pdfs(
                urls,
                session,
                max_workers=direct_workers,
                progress_bar=progress_bar
            )

            progress_bar.progress(1.0, text="Done!")

            report_txt = generate_txt_report(
                "Direct URL input",
                urls,
                downloaded,
                errors
            )

            st.success(f"✅ Downloaded {len(downloaded)} of {len(urls)} PDFs")

            if errors:
                with st.expander("Show errors"):
                    for err in errors:
                        st.text(f"✗ {err['url']}: {err['error']}")

            dl_c1, dl_c2 = st.columns(2)

            with dl_c1:
                if downloaded:
                    zip_data = create_zip_from_memory(downloaded)
                    st.download_button(
                        label=f"📦 Download ZIP ({len(downloaded)} files)",
                        data=zip_data,
                        file_name=(
                            f"pdfs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                        ),
                        mime="application/zip",
                        type="primary"
                    )

            with dl_c2:
                st.download_button(
                    label="📝 Download Report (.TXT)",
                    data=report_txt,
                    file_name=(
                        f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    ),
                    mime="text/plain"
                )


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("ℹ️ How to Use")

    st.markdown("""
    ### 🔍 Auto-Scan Mode (Tab 1)
    1. Go to the company's investor page
    2. Copy the URL from your browser
    3. Paste it here
    4. Click **Scan for PDFs**
    5. Review found links
    6. Click **Download All PDFs**
    7. Get your **ZIP** + **TXT report**

    ### 📋 Manual Mode (Tab 2)
    If auto-scan doesn't find PDFs
    (JavaScript-heavy sites):
    1. Open browser DevTools (F12)
    2. Go to **Network** tab
    3. Filter by **Doc** or search **.pdf**
    4. Copy all PDF URLs
    5. Paste them in Tab 2
    6. Download in bulk

    ---

    ### 🎯 Example URLs to Try
    ```
    https://www.shriramfinance.in/
    investors/investor-information
    ```

    ---

    ### ⚡ Why This Works
    - **No Selenium needed** — pure HTTP requests
    - **Browser-like headers** bypass basic blocks
    - **Parallel downloads** — 5-10x faster
    - **Works on Streamlit Cloud**
    - **ZIP + TXT output** ready to use
    """)

    st.markdown("---")

    if st.button("🗑️ Clear Everything"):
        st.session_state.found_pdfs = []
        st.session_state.downloaded_pdfs = {}
        st.session_state.txt_output = ""
        st.session_state.scan_done = False
        st.rerun()
