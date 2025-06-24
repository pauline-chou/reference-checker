import streamlit as st
import re
import urllib.parse
from docx import Document
import tempfile
import requests

# 🔑 API Key 管理：支援本機 .txt 與雲端 secrets.toml
def get_scopus_key():
    if "scopus_api_key" in st.secrets:
        return st.secrets["scopus_api_key"]
    else:
        with open("scopus_key.txt", "r") as f:
            return f.read().strip()

SCOPUS_API_KEY = get_scopus_key()

# Streamlit 設定
st.set_page_config(page_title="Reference Checker", layout="centered")
st.title("📚 Reference Checker")
st.write("上傳 Word 檔 (.docx)，系統將從參考文獻區開始擷取引用，並嘗試以標題搜尋 Scopus 文獻。")

# 上傳檔案與選項
uploaded_file = st.file_uploader("請上傳 Word 檔案（.docx）", type=["docx"])
style = st.selectbox("請選擇參考文獻格式", ["APA", "IEEE"])
start_keyword = st.text_input("請輸入參考文獻起始標題（例如 References 或 參考文獻）", "References")

# 擷取 Word 中所有段落
def extract_paragraphs_from_docx(file):
    doc = Document(file)
    return [para.text.strip() for para in doc.paragraphs if para.text.strip()]

# 擷取參考文獻區段
def extract_reference_section(paragraphs, start_keyword):
    start_index = -1
    for i, p in enumerate(paragraphs):
        if start_keyword.lower() in p.lower():
            start_index = i + 1
            break
    if start_index == -1:
        return []
    return paragraphs[start_index:]

# 根據格式擷取標題
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

# 使用 Scopus API 查詢標題
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

# 主處理流程
if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    paragraphs = extract_paragraphs_from_docx(tmp_path)
    references = extract_reference_section(paragraphs, start_keyword)

    if not references:
        st.warning("⚠️ 找不到參考文獻段落，請檢查『參考文獻標題關鍵字』是否正確。")
    else:
        st.subheader("🔍 查詢結果")
        for i, ref in enumerate(references):
            title = extract_title(ref, style)
            if title:
                scopus_url = search_scopus_by_title(title)
                if scopus_url:
                    st.markdown(f"**{i+1}. {title}**  \n🔗 [Scopus 查詢結果]({scopus_url})", unsafe_allow_html=True)
                else:
                    st.error(f"⚠️ 第 {i+1} 筆找不到完全吻合的 Scopus 文獻：\n> {title}")
            else:
                st.error(f"❌ 第 {i+1} 筆無法從中解析標題：\n> {ref}")
