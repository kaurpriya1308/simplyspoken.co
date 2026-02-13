import streamlit as st
import json
import re
from datetime import datetime
from urllib.parse import unquote

# ─────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="HAR → PDF Link Extractor",
    page_icon="📄",
    layout="wide"
)

# ─────────────────────────────────────────────
# Session State
# ─────────────────────────────────────────────
if 'raw_links' not in st.session_state:
    st.session_state.raw_links = []
if 'filtered_links' not in st.session_state:
    st.session_state.filtered_links = []
if 'har_loaded' not in st.session_state:
    st.session_state.har_loaded = False


# ─────────────────────────────────────────────
# CORE: Clean a URL
# ─────────────────────────────────────────────
def clean_url(url):
    """
    Fix broken URLs found in HAR files.
    
    Handles:
    - Escaped slashes:  https:\\/\\/domain.com\\/path
    - Double escaped:   https:\\\\/\\\\/domain.com
    - URL encoded:      https%3A%2F%2Fdomain.com
    - Quoted strings:   "https://domain.com/file.pdf"
    - Backslash noise:  https:\/\/domain.com\/path
    - Mixed escaping:   any combination of above
    """
    if not url:
        return ""

    cleaned = url.strip()

    # Remove surrounding quotes
    cleaned = cleaned.strip('"\'')
    cleaned = cleaned.strip('\\')

    # Fix escaped slashes (multiple passes for nested escaping)
    # \\/ → /
    # \/ → /
    for _ in range(5):
        old = cleaned
        cleaned = cleaned.replace('\\/', '/')
        cleaned = cleaned.replace('\\\\/', '/')
        cleaned = cleaned.replace('\\"', '')
        cleaned = cleaned.replace('\\n', '')
        cleaned = cleaned.replace('\\r', '')
        cleaned = cleaned.replace('\\t', '')
        if cleaned == old:
            break

    # Fix double-escaped backslashes
    cleaned = re.sub(r'\\+/', '/', cleaned)

    # URL decode if needed
    if '%2F' in cleaned or '%3A' in cleaned:
        try:
            cleaned = unquote(cleaned)
        except Exception:
            pass

    # Ensure proper protocol
    if cleaned.startswith('//'):
        cleaned = 'https:' + cleaned
    elif not cleaned.startswith('http'):
        # Skip non-URL strings
        return ""

    # Remove any remaining backslashes in URL
    cleaned = cleaned.replace('\\', '/')

    # Fix triple slashes (but keep ://)
    cleaned = re.sub(r'(?<!:)/{2,}', '/', cleaned)

    # Remove trailing garbage characters
    cleaned = cleaned.rstrip('\\",;\')} \t\n\r')

    # Remove fragment if present (#something)
    if '#' in cleaned:
        cleaned = cleaned.split('#')[0]

    return cleaned


# ─────────────────────────────────────────────
# CORE: Extract ALL URLs from HAR
# ─────────────────────────────────────────────
def extract_all_urls_from_har(har_content):
    """
    Extract every possible URL from a HAR file.
    
    Searches in:
    1. Request URLs (entries[].request.url)
    2. Response headers (Location, Content-Disposition)
    3. Response body content (HTML, JSON, JS)
    4. Query parameters
    5. POST body data
    6. Cookies (sometimes contain redirect URLs)
    """
    all_urls = set()

    try:
        har_data = json.loads(har_content)
    except json.JSONDecodeError as e:
        st.error(f"Invalid HAR file: {e}")
        return []

    entries = har_data.get('log', {}).get('entries', [])

    if not entries:
        st.error("No entries found in HAR file")
        return []

    for entry in entries:
        # ── 1. Request URL ──
        request = entry.get('request', {})
        req_url = request.get('url', '')
        if req_url:
            all_urls.add(req_url)

        # ── 2. Request headers ──
        for header in request.get('headers', []):
            val = header.get('value', '')
            if 'http' in val.lower():
                # Extract URLs from header values
                found = re.findall(
                    r'https?://[^\s"\'<>\\,;]+',
                    val
                )
                all_urls.update(found)

        # ── 3. Request POST data ──
        post_data = request.get('postData', {})
        post_text = post_data.get('text', '')
        if post_text:
            found = re.findall(
                r'https?://[^\s"\'<>\\,;]+',
                post_text
            )
            all_urls.update(found)

            # Also check for escaped URLs in POST
            found_escaped = re.findall(
                r'https?:\\?/\\?/[^\s"\'<>,;]+',
                post_text
            )
            all_urls.update(found_escaped)

        # ── 4. Response headers ──
        response = entry.get('response', {})
        for header in response.get('headers', []):
            name = header.get('name', '').lower()
            val = header.get('value', '')

            if name in ['location', 'content-location', 'link']:
                if 'http' in val:
                    all_urls.add(val)

            if name == 'content-disposition' and 'filename' in val:
                # Not a URL but useful info
                pass

        # ── 5. Response body ──
        content = response.get('content', {})
        body_text = content.get('text', '')

        if body_text:
            mime = content.get('mimeType', '').lower()

            # JSON responses
            if 'json' in mime or body_text.strip().startswith(('{', '[')):
                # Find URLs in JSON (handles escaped slashes)
                # Pattern for normal URLs
                found = re.findall(
                    r'https?://[^\s"\'<>\\,;\]})]+',
                    body_text
                )
                all_urls.update(found)

                # Pattern for escaped URLs like
                # https:\/\/domain.com\/path
                found_escaped = re.findall(
                    r'https?:\\?/\\?/[^\s"\'<>,;\]})]+',
                    body_text
                )
                all_urls.update(found_escaped)

                # Pattern for double-escaped
                # https:\\/\\/domain.com\\/path
                found_double = re.findall(
                    r'https?:\\{1,4}/\\{0,4}/[^\s"\'<>,;\]})]+',
                    body_text
                )
                all_urls.update(found_double)

            # HTML responses
            elif 'html' in mime:
                # href="..." and src="..."
                found = re.findall(
                    r'(?:href|src|data-href|data-src|data-url|action)'
                    r'\s*=\s*["\']([^"\']+)["\']',
                    body_text,
                    re.IGNORECASE
                )
                for f in found:
                    if f.startswith('http'):
                        all_urls.add(f)

                # Also raw URL patterns
                found_raw = re.findall(
                    r'https?://[^\s"\'<>]+',
                    body_text
                )
                all_urls.update(found_raw)

                # td values, span content, div content
                # with PDF links
                found_td = re.findall(
                    r'<(?:td|span|div|p|li)[^>]*>\s*'
                    r'(https?://[^\s<]+)\s*'
                    r'</(?:td|span|div|p|li)>',
                    body_text,
                    re.IGNORECASE
                )
                all_urls.update(found_td)

            # JavaScript responses
            elif 'javascript' in mime or 'script' in mime:
                found = re.findall(
                    r'https?://[^\s"\'<>\\,;]+',
                    body_text
                )
                all_urls.update(found)

                found_escaped = re.findall(
                    r'https?:\\?/\\?/[^\s"\'<>,;]+',
                    body_text
                )
                all_urls.update(found_escaped)

            # Plain text / XML
            else:
                found = re.findall(
                    r'https?://[^\s"\'<>]+',
                    body_text
                )
                all_urls.update(found)

    return list(all_urls)


# ─────────────────────────────────────────────
# CORE: Filter URLs by Keywords
# ─────────────────────────────────────────────
def filter_urls(all_urls, include_keywords, exclude_keywords,
                custom_xpath_keywords=None):
    """
    Filter URLs based on include/exclude keywords.

    Args:
        all_urls: list of raw URLs
        include_keywords: list like ['.pdf', 'download']
                          URL must contain at least ONE
        exclude_keywords: list like ['.jpg', '.png']
                          URL must NOT contain any
        custom_xpath_keywords: additional keywords to look
                               for in URL path/params

    Returns:
        list of (cleaned_url, matched_keyword)
    """
    results = []
    seen = set()

    # Combine include keywords
    all_include = [
        kw.strip().lower()
        for kw in include_keywords
        if kw.strip()
    ]

    if custom_xpath_keywords:
        all_include.extend([
            kw.strip().lower()
            for kw in custom_xpath_keywords
            if kw.strip()
        ])

    all_exclude = [
        kw.strip().lower()
        for kw in exclude_keywords
        if kw.strip()
    ]

    for raw_url in all_urls:
        # Clean the URL first
        cleaned = clean_url(raw_url)
        if not cleaned:
            continue

        cleaned_lower = cleaned.lower()

        # Skip if already seen
        if cleaned in seen:
            continue

        # ── EXCLUDE CHECK ──
        excluded = False
        for exc in all_exclude:
            if exc in cleaned_lower:
                excluded = True
                break
        if excluded:
            continue

        # ── INCLUDE CHECK ──
        matched_kw = None
        for inc in all_include:
            if inc in cleaned_lower:
                matched_kw = inc
                break

        if matched_kw:
            seen.add(cleaned)
            results.append((cleaned, matched_kw))

    # Sort by filename
    results.sort(key=lambda x: x[0].split('/')[-1].lower())

    return results


# ─────────────────────────────────────────────
# Generate TXT Output
# ─────────────────────────────────────────────
def generate_txt(filtered_results, source_file, include_kw,
                 exclude_kw, custom_kw):
    """Generate clean .txt output"""
    lines = []
    lines.append("=" * 70)
    lines.append("PDF LINKS EXTRACTED FROM HAR FILE")
    lines.append("=" * 70)
    lines.append(f"Source File    : {source_file}")
    lines.append(
        f"Extracted On   : "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    lines.append(f"Total PDFs     : {len(filtered_results)}")
    lines.append(f"Include Filter : {', '.join(include_kw)}")
    if custom_kw:
        lines.append(f"Custom Keywords: {', '.join(custom_kw)}")
    lines.append(f"Exclude Count  : {len(exclude_kw)} patterns")
    lines.append("=" * 70)
    lines.append("")
    lines.append("── PDF LINKS ──")
    lines.append("")

    for i, (url, keyword) in enumerate(filtered_results, 1):
        filename = url.split('/')[-1].split('?')[0]
        lines.append(f"{i:4d}. {filename}")
        lines.append(f"      {url}")
        lines.append(f"      [matched: {keyword}]")
        lines.append("")

    lines.append("=" * 70)
    lines.append("")
    lines.append("── PLAIN URL LIST (copy-paste ready) ──")
    lines.append("")
    for url, _ in filtered_results:
        lines.append(url)

    lines.append("")
    lines.append("=" * 70)
    lines.append("END")
    return "\n".join(lines)


# ═════════════════════════════════════════════
# STREAMLIT UI
# ═════════════════════════════════════════════

st.title("📄 HAR File → PDF Link Extractor")
st.markdown(
    "Upload a `.har` file from browser DevTools → "
    "Get clean, working PDF links in `.txt` format"
)

# ─────────────────────────────────────────────
# HOW TO GET HAR FILE
# ─────────────────────────────────────────────
with st.expander("📖 How to capture a .har file", expanded=False):
    st.markdown("""
    ### Steps:
    1. **Open Chrome** and go to the target website
    2. **Press F12** to open DevTools
    3. **Click Network tab**
    4. **Check "Preserve log"** checkbox
    5. **Browse the page** — click ALL tabs, buttons, 
       dropdowns that load documents
    6. **Wait** for everything to load
    7. **Right-click** anywhere in the Network tab list
    8. **Select "Save all as HAR with content"**
    9. **Upload** that `.har` file below
    
    ### Example for Shriram Finance:
    ```
    Go to: shriramfinance.in/investors/investor-information
    → Click each tab (Annual Reports, Quarterly Results, etc.)
    → Wait for content to load
    → Save HAR file
    → Upload here
    ```
    """)

st.markdown("---")

# ─────────────────────────────────────────────
# FILE UPLOAD
# ─────────────────────────────────────────────
uploaded_file = st.file_uploader(
    "📁 Upload .har file",
    type=['har'],
    help="Export from Chrome DevTools → Network tab → Save all as HAR"
)

# ─────────────────────────────────────────────
# FILTER SETTINGS
# ─────────────────────────────────────────────
st.markdown("---")
st.subheader("🔧 Filter Settings")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**✅ Include Keywords**")
    st.caption(
        "URL must contain at least ONE of these. "
        "Separate multiple keywords with `|`"
    )
    include_input = st.text_input(
        "Include keywords",
        value=".pdf",
        placeholder=".pdf|/download/|getfile|attachment",
        help=(
            "Examples:\n"
            "- .pdf (default — catches most PDFs)\n"
            "- .pdf|/download/ (PDF or download path)\n"
            "- .pdf|.xlsx|.docx (multiple file types)\n"
            "- .pdf|getfile|viewdoc (custom patterns)"
        ),
        key="include_kw"
    )

with col2:
    st.markdown("**❌ Exclude Keywords**")
    st.caption(
        "URLs with ANY of these are removed. "
        "Separate with `|`"
    )
    exclude_input = st.text_input(
        "Exclude keywords",
        value=(
            ".jpg|.jpeg|.png|.gif|.svg|.webp|"
            ".ico|.css|.js|.woff|.woff2|"
            "google-analytics|facebook|twitter|"
            "linkedin|instagram"
        ),
        placeholder=".jpg|.png|facebook|tracker",
        help="Patterns to exclude from results",
        key="exclude_kw"
    )

with col3:
    st.markdown("**🎯 Custom Path Keywords**")
    st.caption(
        "Additional keywords for PDF locations. "
        "Use when PDFs don't have .pdf extension."
    )
    custom_input = st.text_input(
        "Custom keywords (optional)",
        value="",
        placeholder="/documents/|/investor/|/reports/|viewPDF",
        help=(
            "For sites where PDF URLs don't end in .pdf:\n"
            "- /ViewDocument?id=\n"
            "- /api/getFile/\n"
            "- /content/download/\n"
            "These are combined with Include keywords"
        ),
        key="custom_kw"
    )

# Parse keywords
include_keywords = [
    kw.strip() for kw in include_input.split('|') if kw.strip()
]
exclude_keywords = [
    kw.strip() for kw in exclude_input.split('|') if kw.strip()
]
custom_keywords = [
    kw.strip() for kw in custom_input.split('|') if kw.strip()
] if custom_input.strip() else []

# Show active filters
st.info(
    f"**Active:** Include `{include_keywords}` "
    f"{'+ Custom `' + str(custom_keywords) + '`' if custom_keywords else ''}"
    f" | Excluding `{len(exclude_keywords)}` patterns"
)

# ─────────────────────────────────────────────
# PROCESS HAR FILE
# ─────────────────────────────────────────────
st.markdown("---")

if uploaded_file:
    # Read HAR content
    try:
        har_content = uploaded_file.read().decode('utf-8')
    except UnicodeDecodeError:
        har_content = uploaded_file.read().decode('utf-8', errors='ignore')

    file_size_mb = len(har_content) / (1024 * 1024)
    st.caption(
        f"📁 File: {uploaded_file.name} | "
        f"Size: {file_size_mb:.1f} MB"
    )

    if st.button(
        "🚀 Extract PDF Links", type="primary", key="extract_btn"
    ):
        with st.spinner("Parsing HAR file and extracting URLs..."):
            # Step 1: Get all URLs
            raw_urls = extract_all_urls_from_har(har_content)
            st.session_state.raw_links = raw_urls

            # Step 2: Filter
            filtered = filter_urls(
                raw_urls,
                include_keywords,
                exclude_keywords,
                custom_keywords
            )
            st.session_state.filtered_links = filtered
            st.session_state.har_loaded = True

        # Show metrics
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("🔗 Total URLs in HAR", len(raw_urls))
        with m2:
            st.metric("📄 PDF Links Found", len(filtered))
        with m3:
            st.metric("🚫 Filtered Out", len(raw_urls) - len(filtered))

# ─────────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────────
if st.session_state.har_loaded and st.session_state.filtered_links:
    st.markdown("---")
    st.header(f"📄 {len(st.session_state.filtered_links)} PDF Links Found")

    # ── RE-FILTER BUTTON ──
    if st.button(
        "🔄 Re-apply Filters (after changing keywords above)",
        key="refilter"
    ):
        filtered = filter_urls(
            st.session_state.raw_links,
            include_keywords,
            exclude_keywords,
            custom_keywords
        )
        st.session_state.filtered_links = filtered
        st.rerun()

    # ── DISPLAY RESULTS ──
    st.markdown("### Clean PDF Links:")

    for i, (url, keyword) in enumerate(
        st.session_state.filtered_links, 1
    ):
        filename = url.split('/')[-1].split('?')[0]
        if len(filename) > 80:
            filename = filename[:77] + "..."

        col_num, col_name, col_link = st.columns([0.5, 3, 6])
        with col_num:
            st.text(f"{i:3d}.")
        with col_name:
            st.text(f"📄 {filename}")
        with col_link:
            st.markdown(
                f"[Open Link]({url})",
                unsafe_allow_html=True
            )

    # ─────────────────────────────────────────
    # DOWNLOAD OPTIONS
    # ─────────────────────────────────────────
    st.markdown("---")
    st.header("⬇️ Download Results")

    d1, d2, d3 = st.columns(3)

    # Option 1: Plain URL list
    with d1:
        plain_urls = "\n".join(
            url for url, _ in st.session_state.filtered_links
        )
        st.download_button(
            "📝 URLs Only (.txt)",
            data=plain_urls,
            file_name=(
                f"pdf_urls_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            ),
            mime="text/plain",
            type="primary",
            help="Just the URLs, one per line. Copy-paste ready."
        )

    # Option 2: Detailed report
    with d2:
        report = generate_txt(
            st.session_state.filtered_links,
            uploaded_file.name if uploaded_file else "unknown",
            include_keywords,
            exclude_keywords,
            custom_keywords
        )
        st.download_button(
            "📋 Full Report (.txt)",
            data=report,
            file_name=(
                f"pdf_report_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            ),
            mime="text/plain",
            help="Detailed report with filenames, URLs, and filters used."
        )

    # Option 3: CSV format
    with d3:
        csv_lines = ["index,filename,url,matched_keyword"]
        for i, (url, kw) in enumerate(
            st.session_state.filtered_links, 1
        ):
            fname = url.split('/')[-1].split('?')[0]
            # Escape commas in filename
            fname = fname.replace(',', '_')
            csv_lines.append(f'{i},"{fname}","{url}","{kw}"')

        csv_data = "\n".join(csv_lines)
        st.download_button(
            "📊 CSV Format (.csv)",
            data=csv_data,
            file_name=(
                f"pdf_links_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            ),
            mime="text/csv",
            help="Open in Excel for sorting/filtering."
        )

    # ─────────────────────────────────────────
    # COPY-PASTE SECTION
    # ─────────────────────────────────────────
    st.markdown("---")
    st.subheader("📋 Copy-Paste Ready")

    plain_text = "\n".join(
        url for url, _ in st.session_state.filtered_links
    )
    st.text_area(
        "All PDF URLs (select all → copy)",
        value=plain_text,
        height=300,
        key="copyable_urls"
    )

# ─────────────────────────────────────────────
# DEBUG: RAW LINKS
# ─────────────────────────────────────────────
if st.session_state.har_loaded and st.session_state.raw_links:
    with st.expander(
        f"🔧 Debug: All {len(st.session_state.raw_links)} "
        f"raw URLs from HAR"
    ):
        st.caption(
            "If PDFs are missing from results, "
            "search here to find what keyword to add."
        )

        search_term = st.text_input(
            "🔍 Search raw URLs",
            placeholder="Type to search... e.g., report, annual, pdf",
            key="search_raw"
        )

        filtered_raw = st.session_state.raw_links
        if search_term:
            filtered_raw = [
                u for u in st.session_state.raw_links
                if search_term.lower() in u.lower()
            ]
            st.caption(
                f"Showing {len(filtered_raw)} URLs "
                f"matching '{search_term}'"
            )

        for i, url in enumerate(filtered_raw[:500], 1):
            cleaned = clean_url(url)
            if cleaned:
                is_pdf = '.pdf' in cleaned.lower()
                icon = "📄" if is_pdf else "🔗"
                st.text(f"{icon} {i}. {cleaned[:150]}")


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("📖 Guide")

    st.markdown("""
    ### How to Use

    **Step 1:** Capture HAR file
    ```
    Chrome → F12 → Network tab
    → Check "Preserve log"
    → Browse the site
    → Click all tabs/buttons
    → Right-click → Save all as HAR
    ```

    **Step 2:** Upload HAR file here

    **Step 3:** Adjust filters if needed

    **Step 4:** Download `.txt` with clean links

    ---

    ### Filter Examples

    **Standard PDFs:**
    ```
    Include: .pdf
    ```

    **PDFs without .pdf extension:**
    ```
    Include: .pdf|/ViewDocument|/GetFile
    ```

    **Multiple file types:**
    ```
    Include: .pdf|.xlsx|.docx
    ```

    **Site-specific paths:**
    ```
    Custom: /investors/|/reports/|/downloads/
    ```

    ---

    ### URL Cleaning

    The app automatically fixes:
    - `https:\\/\\/` → `https://`
    - `%2F` → `/`
    - Double escaping
    - Trailing garbage characters
    - Fragment removal

    ---

    ### Why HAR?
    
    HAR captures **everything** the browser
    loaded — including:
    - API responses (JSON with PDF URLs)
    - Lazy-loaded content
    - Tab-switch requests
    - All XHR/Fetch calls
    
    No scraping needed. No cookies issues.
    Just upload and extract.
    """)

    st.markdown("---")

    if st.button("🗑️ Clear All"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
