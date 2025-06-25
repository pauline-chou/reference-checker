import streamlit as st
import re
import urllib.parse
from docx import Document
import tempfile
import requests
from difflib import SequenceMatcher
import pandas as pd

# ========== API Key 管理 ==========
def get_scopus_key():
    try:
        return st.secrets["scopus_api_key"]
    except Exception:
        try:
            with open("scopus_key.txt", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            st.error("❌ 找不到 Scopus API 金鑰，請確認已設定 secrets 或提供 scopus_key.txt")
            st.stop()

SCOPUS_API_KEY = get_scopus_key()

# ========== 清洗標題 ==========
def clean_title(text):
    # 去除標點、空白，並轉為小寫
    return re.sub(r'\W+', '', text).lower()

# ========== 相似度判斷 ==========
def is_similar(a, b, threshold=0.9):
    return SequenceMatcher(None, a, b).ratio() >= threshold

# ========== Crossref 查詢 ==========
def search_crossref_by_title(title):
    crossref_email = st.secrets.get("crossref_email", "your_email@example.com")  # ← 使用者記得自行修改
    url = "https://api.crossref.org/works"
    params = {
        "query.title": title,
        "rows": 5,
        "mailto": crossref_email
    }

    response = requests.get(url, params=params)
    if response.status_code != 200:
        return (None, None)

    items = response.json().get("message", {}).get("items", [])
    cleaned_input = clean_title(title)

    for item in items:
        cr_title = item.get("title", [""])[0]
        cr_url = item.get("URL")
        cleaned_cr_title = clean_title(cr_title)

        if cleaned_input == cleaned_cr_title:
            return ("exact", cr_url)
        elif is_similar(cleaned_input, cleaned_cr_title, threshold=0.9):
            return ("similar", cr_url)

    return (None, None)

# ========== Scopus 查詢 ==========
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

# ========== Word 處理 ==========
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

# ========== 擷取標題 ==========
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

# ========== Streamlit UI ==========
st.set_page_config(page_title="Reference Checker", layout="centered")
st.title("📚 Reference Checker")
st.write("上傳 Word 檔 (.docx)，自動查詢 Scopus → Crossref，分類為四類")

uploaded_file = st.file_uploader("請上傳 Word 檔案（.docx）", type=["docx"])
style = st.selectbox("請選擇參考文獻格式", ["APA", "IEEE"])
start_keyword = st.selectbox("請選擇參考文獻起始標題", ["參考文獻", "References", "Reference"])

# ========== 上傳並處理 ==========
if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    paragraphs = extract_paragraphs_from_docx(tmp_path)
    references = extract_reference_section(paragraphs, start_keyword)

    if not references:
        st.warning("⚠️ 找不到參考文獻段落，請確認關鍵字是否正確。")
    else:
        titles = []
        for ref in references:
            title = extract_title(ref, style)
            if title:
                titles.append(title)

        # ✅ 規則表格：提前顯示
        st.markdown("---")
        st.subheader("🧠 查詢結果分類規則")
        rules = [
            ["🟢 Scopus 首次找到", "Scopus", "標題完全一致", "否"],
            ["🟢 Crossref 完全包含", "Crossref", "查詢標題包含於 Crossref 標題中", "否"],
            ["🟡 Crossref 類似標題", "Crossref", "標題相似度 ≥ 0.9", "是"],
            ["🔴 均查無結果", "—", "無任何結果或相似度過低", "—"],
        ]
        df_rules = pd.DataFrame(rules, columns=["分類燈號", "來源", "比對方式", "需人工確認"])
        st.dataframe(df_rules, use_container_width=True)

        # ✅ 結果區預留
        result_tabs_placeholder = st.empty()

        # ✅ 開始查詢
        st.subheader("📊 正在查詢中，請稍候...")
        scopus_results = {}
        crossref_exact = {}
        crossref_similar = {}
        not_found = []

        progress_bar = st.progress(0.0)

        for i, title in enumerate(titles, 1):
            msg_box = st.empty()
            with st.status(f"🔍 第 {i} 筆：`{title}`", expanded=True) as status:
                msg_box.markdown("📡 正在查 Scopus...")
                url = search_scopus_by_title(title)
                if url:
                    scopus_results[title] = url
                    msg_box.markdown("✅ 已找到於 **Scopus**")
                    status.update(label=f"🟢 第 {i} 筆成功（Scopus）", state="complete")
                else:
                    msg_box.markdown("🔁 Scopus 無結果，改查 Crossref...")
                    match_type, url = search_crossref_by_title(title)
                    if match_type == "exact":
                        crossref_exact[title] = url
                        msg_box.markdown("✅ Crossref 完全包含")
                        status.update(label=f"🟢 第 {i} 筆成功（Crossref 完全包含）", state="complete")
                    elif match_type == "similar":
                        crossref_similar[title] = url
                        msg_box.markdown("🟡 Crossref 標題相似（建議人工確認）")
                        status.update(label=f"🟡 第 {i} 筆相似（需確認）", state="complete")
                    else:
                        not_found.append(title)
                        msg_box.markdown("❌ Crossref 也無結果")
                        status.update(label=f"🔴 第 {i} 筆未找到", state="error")
            progress_bar.progress(i / len(titles))

        # ✅ 將結果填入預留區塊
        with result_tabs_placeholder.container():
            st.markdown("---")
            st.subheader("📊 查詢結果分類")

            tab1, tab2, tab3, tab4 = st.tabs([
                f"🟢 Scopus 首次找到（{len(scopus_results)}）",
                f"🟢 Crossref 完全包含（{len(crossref_exact)}）",
                f"🟡 Crossref 類似標題（{len(crossref_similar)}）",
                f"🔴 均查無結果（{len(not_found)}）"
            ])

            with tab1:
                if scopus_results:
                    for i, (title, url) in enumerate(scopus_results.items(), 1):
                        with st.expander(f"{i}. {title}"):
                            st.markdown(f"🔗 [Scopus 連結]({url})", unsafe_allow_html=True)
                else:
                    st.info("Scopus 無任何命中結果。")

            with tab2:
                if crossref_exact:
                    for i, (title, url) in enumerate(crossref_exact.items(), 1):
                        with st.expander(f"{i}. {title}"):
                            st.markdown(f"🔗 [Crossref 連結]({url})", unsafe_allow_html=True)
                else:
                    st.info("Crossref 無完全包含結果。")

            with tab3:
                if crossref_similar:
                    for i, (title, url) in enumerate(crossref_similar.items(), 1):
                        with st.expander(f"{i}. {title}"):
                            st.markdown(f"🔗 [相似論文連結]({url})", unsafe_allow_html=True)
                            st.warning("⚠️ 此為相似標題，請人工確認是否為正確文獻。")
                else:
                    st.info("無標題相似但不一致的結果。")

            with tab4:
                if not_found:
                    for i, title in enumerate(not_found, 1):
                        st.markdown(f"{i}. {title}")
                    st.markdown("👉 請考慮手動搜尋 Google Scholar。")
                else:
                    st.success("所有標題皆成功查詢！")
