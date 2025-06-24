import streamlit as st
import re
import urllib.parse
from docx import Document
import tempfile
import requests

# Scopus API Key 管理
def get_scopus_key():
    try:
        return st.secrets["scopus_api_key"]
    except Exception:
        try:
            with open("scopus_key.txt", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            st.error("❌ 找不到 Scopus API 金鑰，請確認已在 secrets 設定或提供 scopus_key.txt")
            st.stop()

SCOPUS_API_KEY = get_scopus_key()

# Crossref 查詢
def search_crossref_by_title(title):
    url = "https://api.crossref.org/works"
    params = {
        "query.title": title,
        "rows": 5,
        "mailto": "pauline687@gmail.com"
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        items = response.json().get("message", {}).get("items", [])
        for item in items:
            cr_title = item.get("title", [""])[0]
            if title.lower() in cr_title.lower():
                return item.get("URL")
    return None

# Scopus 查詢
def search_scopus_by_title(title):
    base_url = "https://api.elsevier.com/content/search/scopus"
    headers = {
        "Accept": "application/json",
        "X-ELS-APIKey": SCOPUS_API_KEY
    }
    params = {
        "query": f'TITLE("{title}")',
        "count": 5
    }
    response = requests.get(base_url, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json()
        entries = data.get('search-results', {}).get('entry', [])
        for entry in entries:
            doc_title = entry.get('dc:title', '')
            if doc_title.strip().lower() == title.strip().lower():
                return entry.get('prism:url', 'https://www.scopus.com')
    return None

# Word 處理
def extract_paragraphs_from_docx(file):
    doc = Document(file)
    return [para.text.strip() for para in doc.paragraphs if para.text.strip()]

def extract_reference_section(paragraphs, start_keyword):
    start_index = -1
    for i, p in enumerate(paragraphs):
        if start_keyword.lower() in p.lower():
            start_index = i + 1
            break
    return paragraphs[start_index:] if start_index != -1 else []

# 擷取標題
def extract_title(ref_text, style):
    if style == "APA":
        match = re.search(r'\(\d{4}\)\.\s(.+?)(\.|\n|$)', ref_text)
        if match:
            return match.group(1).strip()
    elif style == "IEEE":
        match = re.search(r'"(.+?)"', ref_text)
        if match:
            return match.group(1).strip()
    return None

# 初始化 session state
for key in ["titles", "pending_titles", "scopus_results", "crossref_results"]:
    if key not in st.session_state:
        st.session_state[key] = []

# 介面設定
st.set_page_config(page_title="Reference Checker", layout="centered")
st.title("📚 Reference Checker")
st.write("上傳 Word 檔 (.docx)，從參考文獻區擷取標題，先查 Scopus，再查 Crossref（針對查不到的部分）")

# 上傳與選項
uploaded_file = st.file_uploader("請上傳 Word 檔案（.docx）", type=["docx"])
style = st.selectbox("請選擇參考文獻格式", ["APA", "IEEE"])
start_keyword = st.selectbox("請選擇參考文獻起始標題", ["參考文獻","References", "Reference"])

# 萃取 Word
if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    paragraphs = extract_paragraphs_from_docx(tmp_path)
    references = extract_reference_section(paragraphs, start_keyword)

    if not references:
        st.warning("⚠️ 找不到參考文獻段落，請檢查關鍵字是否正確。")
    else:
        st.session_state.titles = []
        for ref in references:
            title = extract_title(ref, style)
            if title:
                st.session_state.titles.append(title)

# 第一步：Scopus 查詢
if st.session_state.titles and st.button("🧪 第一步：使用 Scopus 查詢"):
    st.subheader("🔍 Scopus 查詢結果")
    st.session_state.scopus_results = {}
    st.session_state.pending_titles = []
    for i, title in enumerate(st.session_state.titles):
        url = search_scopus_by_title(title)
        if url:
            st.session_state.scopus_results[title] = url
            st.markdown(f"**{i+1}. {title}**  \n🔗 [Scopus 查詢結果]({url})", unsafe_allow_html=True)
        else:
            st.session_state.pending_titles.append(title)
            st.error(f"⚠️ 第 {i+1} 筆找不到 Scopus 結果：\n> {title}")

# 第二步：Crossref 補查
if st.session_state.pending_titles and st.button("🔁 第二步：使用 Crossref 補查"):
    st.subheader("🔍 Crossref 查詢結果（針對 Scopus 查無結果）")
    st.session_state.crossref_results = {}
    for i, title in enumerate(st.session_state.pending_titles):
        url = search_crossref_by_title(title)
        if url:
            st.session_state.crossref_results[title] = url
            st.markdown(f"**{i+1}. {title}**  \n🔗 [Crossref 查詢結果]({url})", unsafe_allow_html=True)
        else:
            st.error(f"❌ Crossref 查無結果：\n> {title}")

# 統整資訊
if st.session_state.titles:
    found = len(st.session_state.scopus_results) + len(st.session_state.crossref_results)
    unresolved = len(st.session_state.titles) - found
    st.markdown("---")
    st.subheader("📊 查詢統計結果")
    st.markdown(f"- ✅ 成功查詢結果：{found} 篇")
    st.markdown(f"- ❓ 尚未查到資料：{unresolved} 篇")

    if unresolved > 0:
        not_found = [t for t in st.session_state.titles if t not in st.session_state.scopus_results and t not in st.session_state.crossref_results]
        with st.expander("❗ 待查標題清單"):
            for i, t in enumerate(not_found, 1):
                st.markdown(f"{i}. {t}")
