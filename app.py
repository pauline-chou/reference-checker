import streamlit as st
import re
import urllib.parse
from docx import Document
import tempfile

st.set_page_config(page_title="Reference Checker", layout="centered")

st.title("📚 Reference Checker")
st.write("上傳 Word 檔 (.docx)，系統將從參考文獻區開始擷取引用，產生可點擊的 Google Scholar 查詢連結。")

uploaded_file = st.file_uploader("請上傳 Word 檔案（.docx）", type=["docx"])
style = st.selectbox("請選擇參考文獻格式", ["APA", "IEEE"])
start_keyword = st.text_input("請輸入參考文獻起始標題（例如 References 或 參考文獻）", "References")

# 萃取 Word 中所有段落
def extract_paragraphs_from_docx(file):
    doc = Document(file)
    return [para.text.strip() for para in doc.paragraphs if para.text.strip()]

# 從段落中找出參考文獻區段
def extract_reference_section(paragraphs, start_keyword):
    start_index = -1
    for i, p in enumerate(paragraphs):
        if start_keyword.lower() in p.lower():
            start_index = i + 1
            break
    if start_index == -1:
        return []
    return paragraphs[start_index:]

# 根據引用格式擷取標題
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

# 產生 Google Scholar 查詢連結
def generate_scholar_link(title):
    base = "https://scholar.google.com/scholar?q="
    return base + urllib.parse.quote(title)

# 處理上傳檔案
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
                link = generate_scholar_link(title)
                st.markdown(f"**{i+1}. {title}**  \n👉 [Google Scholar 查詢]({link})", unsafe_allow_html=True)
            else:
                st.error(f"❌ 第 {i+1} 筆無法從中解析標題：\n> {ref}")
