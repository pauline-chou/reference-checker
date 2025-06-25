import streamlit as st
import re
import urllib.parse
from docx import Document
import tempfile
import requests
from difflib import SequenceMatcher
import pandas as pd
from datetime import datetime
from io import StringIO

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
if "start_query" not in st.session_state:
    st.session_state.start_query = False
if "query_results" not in st.session_state:
    st.session_state.query_results = None
st.title("📚 Reference Checker")
st.write("上傳 Word 檔 (.docx)，自動查詢 Scopus → Crossref，分類為四類")

uploaded_file = st.file_uploader("請上傳 Word 檔案（.docx）", type=["docx"])
style = st.selectbox("請選擇參考文獻格式", ["APA", "IEEE"])
#start_keyword = st.selectbox("請選擇參考文獻起始標題", ["參考文獻", "References", "Reference"])
start_button = st.button("🚀 開始查詢")
# ========== 上傳並處理 ==========
if "selected_kw" not in st.session_state:
    st.session_state.selected_kw = None
if "paragraphs" not in st.session_state:
    st.session_state.paragraphs = None

if uploaded_file and start_button:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    paragraphs = extract_paragraphs_from_docx(tmp_path)
    st.session_state.paragraphs = paragraphs  # 儲存下來供後續使用

    auto_keywords = ["參考文獻", "References", "Reference"]
    matched_section = []
    matched_keyword = None

    for kw in auto_keywords:
        matched_section = extract_reference_section(paragraphs, kw)
        if matched_section:
            matched_keyword = kw
            st.session_state.selected_kw = matched_keyword
            st.session_state.matched_section = matched_section
            break

    else:
        st.warning("⚠️ 無法偵測參考文獻起始標題，請確認是否為以下其中之一：『參考文獻』、『References』或『Reference』。")
        st.stop()

    if matched_section:
        title_pairs = []
        for ref in matched_section:
            title = extract_title(ref, style)
            if title:
                title_pairs.append((ref, title))
        
        #開始查詢
        st.subheader("📊 正在查詢中，請稍候...")
        scopus_results = {}
        crossref_exact = {}
        crossref_similar = {}
        not_found = []

        progress_bar = st.progress(0.0)

        for i, (original_ref, title) in enumerate(title_pairs, 1):
            url = search_scopus_by_title(title)
            if url:
                scopus_results[original_ref] = url
            else:
                match_type, url = search_crossref_by_title(title)
                if match_type == "exact":
                    crossref_exact[original_ref] = url
                elif match_type == "similar":
                    crossref_similar[original_ref] = url
                else:
                    not_found.append(original_ref)
            progress_bar.progress(i / len(title_pairs))

        # 儲存查詢結果
        st.session_state.query_results = {
            "title_pairs": title_pairs,
            "scopus_results": scopus_results,
            "crossref_exact": crossref_exact,
            "crossref_similar": crossref_similar,
            "not_found": not_found,
            "uploaded_filename": uploaded_file.name,
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
         # 規則表格
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


if st.session_state.query_results:
    st.markdown("---")
    st.subheader("📊 查詢結果分類")

    query_data = st.session_state.query_results
    title_pairs = query_data["title_pairs"]
    scopus_results = query_data["scopus_results"]
    crossref_exact = query_data["crossref_exact"]
    crossref_similar = query_data["crossref_similar"]
    not_found = query_data["not_found"]
    uploaded_filename = query_data["uploaded_filename"]
    report_time = query_data["report_time"]

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
                scholar_url = f"https://scholar.google.com/scholar?q={urllib.parse.quote(title)}"
                st.markdown(f"{i}. {title}  \n🔗 [Google Scholar 搜尋]({scholar_url})", unsafe_allow_html=True)
            st.markdown("👉 請考慮手動搜尋 Google Scholar。")
        else:
            st.success("所有標題皆成功查詢！")

    # 下載結果
    st.markdown("---")
    st.subheader("📥 下載查詢結果")

    export_data = []
    for ref, title in title_pairs:
        if ref in scopus_results:
            export_data.append([ref, "Scopus 首次找到", scopus_results[ref]])
        elif ref in crossref_exact:
            export_data.append([ref, "Crossref 完全包含", crossref_exact[ref]])
        elif ref in crossref_similar:
            export_data.append([ref, "Crossref 類似標題", crossref_similar[ref]])
        elif ref in not_found:
            scholar_url = f"https://scholar.google.com/scholar?q={urllib.parse.quote(ref)}"
            export_data.append([ref, "查無結果", scholar_url])

    total_refs = len(title_pairs)
    matched_exact = len(scopus_results) + len(crossref_exact)
    matched_similar = len(crossref_similar)
    unmatched = len(not_found)

    header = StringIO()
    header.write(f"檔案名稱：{uploaded_filename}\n")
    header.write(f"報告產出時間：{report_time}\n\n")
    header.write("初步篩選核對結果：\n")
    header.write(f"本篇論文共有 {total_refs} 篇參考文獻，其中有 {matched_exact} 篇有找到相同篇名，有 {matched_similar} 篇找到類似篇名，{unmatched} 篇未找到對應的期刊論文，可能是專書、研討會論文、產業報告或其他論文，需要人工進行後續核對。\n\n")
    header.write("說明：\n")
    header.write("為節省核對時間，本系統只查對有DOI碼的期刊論文。且並未檢查期刊名稱、作者、卷期、頁碼。只針對篇名進行核對。\n")
    header.write("本系統只是為了提供初步篩選，比對後應接著進行人工核對，任何人都不應該以本系統核對結果作為任何學術倫理判斷之基礎。\n\n")

    csv_buffer = StringIO()
    csv_buffer.write(header.getvalue())
    df_export = pd.DataFrame(export_data, columns=["原始參考文獻", "分類", "連結"])
    df_export.to_csv(csv_buffer, index=False)

    col1, col2 = st.columns([1, 1])
    with col1:
        st.download_button(
            label="📤 下載結果 CSV 檔",
            data=csv_buffer.getvalue().encode('utf-8-sig'),
            file_name="reference_results.csv",
            mime="text/csv"
        )
    with col2:
        if st.button("🔁 重新上傳其他檔案"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()