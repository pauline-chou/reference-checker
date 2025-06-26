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
from serpapi import GoogleSearch

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

def get_serpapi_key():
    try:
        return st.secrets["serpapi_key"]
    except Exception:
        try:
            with open("serpapi_key.txt", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            st.error("❌ 找不到 SerpAPI 金鑰，請確認已設定 secrets 或提供 serpapi_key.txt")
            st.stop()

SERPAPI_KEY = get_serpapi_key()

# ========== 擷取 DOI ==========
def extract_doi(text):
    match = re.search(r'(10\.\d{4,9}/[-._;()/:A-Z0-9]+)', text, re.I)
    if match:
        return match.group(1).rstrip(".")

    doi_match = re.search(r'doi:\s*(https?://doi\.org/)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)', text, re.I)
    if doi_match:
        return doi_match.group(2).rstrip(".")

    return None

# ========== Crossref DOI 查詢 ==========
def search_crossref_by_doi(doi):
    url = f"https://api.crossref.org/works/{doi}"
    response = requests.get(url)
    if response.status_code == 200:
        item = response.json().get("message", {})
        titles = item.get("title")
        if isinstance(titles, list) and len(titles) > 0:
            return titles[0], item.get("URL")
        else:
            return None, item.get("URL")
    return None, None

# ========== 清洗標題 ==========
def clean_title(text):
    text = text.lower().strip()
    text = re.sub(r'[“”‘’]', '"', text)
    text = re.sub(r'[:：]{2,}', ':', text)
    text = re.sub(r'[^a-z0-9\s:.,\\-]', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.rstrip('.,:;- ')
    return text

# ========== Scopus 查詢 ==========
def search_scopus_by_title(title):
    base_url = "https://api.elsevier.com/content/search/scopus"
    headers = {
        "Accept": "application/json",
        "X-ELS-APIKey": SCOPUS_API_KEY
    }
    params = {
        "query": f'TITLE("{title}")',
        "count": 1
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

# ========== Serpapi 查詢 ==========
def search_scholar_by_title(title, api_key, threshold=0.90):
    search_url = f"https://scholar.google.com/scholar?q={urllib.parse.quote(title)}"

    # 呼叫 SerpAPI
    params = {
        "engine": "google_scholar",
        "q": title,
        "api_key": api_key,
        "num": 1
    }
    results = GoogleSearch(params).get_dict()
    organic = results.get("organic_results", [])

    if not organic:
        return search_url, "no_result"
    
    cleaned_query = clean_title(title)
    
    for result in organic:
        result_title = result.get("title", "")
        cleaned_result = clean_title(result_title)
        
        # 僅當標題「清洗後完全一致」才算 match
        if cleaned_query == cleaned_result:
            return search_url, "match"

        similarity = SequenceMatcher(None, cleaned_query, cleaned_result).ratio()
        if similarity >= threshold:
            return search_url, "similar"

    return search_url, "no_result"

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
        match = re.search(r'\(\d{4}\)\.\s(.+?)(?:\.\s|$)', ref_text)
        if match:
            return match.group(1).strip()
    elif style == "IEEE":
        matches = re.findall(r'"([^"]+)"', ref_text)
        if matches:
            return max(matches, key=len).strip().rstrip(",.")
        else:
            fallback = re.search(r'(?<!et al)([A-Z][^,.]+[a-zA-Z])[,\.]', ref_text)
            if fallback:
                return fallback.group(1).strip(" ,.")
    return None

# ========== Streamlit UI ==========
st.set_page_config(page_title="Reference Checker", layout="centered")
if "start_query" not in st.session_state:
    st.session_state.start_query = False
if "query_results" not in st.session_state:
    st.session_state.query_results = None
st.title("📚 Reference Checker")

st.markdown("""
<div style="background-color: #fff9db; padding: 15px; border-left: 6px solid #f1c40f; border-radius: 6px;">
    <span style="font-size: 16px; font-weight: bold;">⚠️ 注意事項</span><br>
    <span style="font-size: 15px; color: #444;">
    為節省核對時間，本系統只查對有 DOI 碼的期刊論文。並未檢查期刊名稱、作者、卷期、頁碼，僅針對篇名進行核對。本系統僅提供初步篩選參考，比對後應進行人工核對，不得直接以本系統核對結果作為學術倫理判斷的依據。
    </span>
</div>
""", unsafe_allow_html=True)
st.markdown(" ")
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
        crossref_doi_hits = {}
        scopus_hits = {}
        scholar_hits = {}
        scholar_similar = {}
        not_found = []

        progress_bar = st.progress(0.0)

        for i, (original_ref, title) in enumerate(title_pairs, 1):
            doi = extract_doi(original_ref)
            if doi:
                title_from_doi, url = search_crossref_by_doi(doi)
                if title_from_doi:
                    crossref_doi_hits[original_ref] = url
                    progress_bar.progress(i / len(title_pairs))
                    continue  # 成功查到 DOI 就略過標題查詢

            url = search_scopus_by_title(title)
            if url:
                scopus_hits[original_ref] = url
            else:
                gs_url, gs_type = search_scholar_by_title(title, SERPAPI_KEY)
                if gs_type == "match":
                    scholar_hits[original_ref] = gs_url
                elif gs_type == "similar":
                    scholar_similar[original_ref] = gs_url  # 加入 similar 分類
                else:
                    not_found.append(original_ref)

            progress_bar.progress(i / len(title_pairs))
            
        st.session_state.query_results = {
            "title_pairs": title_pairs,
            "crossref_doi_hits": crossref_doi_hits,
            "scopus_hits": scopus_hits,
            "scholar_hits": scholar_hits,
            "scholar_similar": scholar_similar,
            "not_found": not_found,
            "uploaded_filename": uploaded_file.name,
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
         # 規則表格
        st.markdown("---")
        st.subheader("🧠 查詢結果分類規則")
        rules = [
            ["🟢 Crossref DOI 命中", "Crossref", "使用參考文獻中的 DOI 直接查詢", "否"],
            ["🟢 標題命中", "Scopus / Google Scholar", "標題完全一致", "否"],
            ["🟡 Google Scholar 類似標題", "Google Scholar", "標題相似或僅部分關鍵字一致", "是"],
            ["🔴 查無結果", "—", "無任何結果或相似度過低", "—"],
        ]
        df_rules = pd.DataFrame(rules, columns=["分類燈號", "來源", "比對方式", "需人工確認"])
        st.dataframe(df_rules, use_container_width=True)


if st.session_state.query_results:
        st.markdown("---")
        st.subheader("📊 查詢結果分類")

        query_data = st.session_state.query_results
        not_found = query_data.get("not_found", [])
        title_pairs = query_data["title_pairs"]
        crossref_doi_hits = query_data["crossref_doi_hits"]
        scholar_similar = query_data["scholar_similar"]
        uploaded_filename = query_data["uploaded_filename"]
        report_time = query_data["report_time"]

        scopus_hits = query_data["scopus_hits"]
        scholar_hits = query_data["scholar_hits"]

        matched_count = len(crossref_doi_hits) + len(scopus_hits) + len(scholar_hits)

        hit_tab, similar_tab, miss_tab = st.tabs([
            f"🟢 命中結果（{matched_count}）",
            f"🟡 Google Scholar 類似標題（{len(scholar_similar)}）",
            f"🔴 均查無結果（{len(not_found)}）"
        ])

        with hit_tab:
            if crossref_doi_hits:
                with st.expander(f"\U0001F7E2 Crossref DOI 命中（{len(crossref_doi_hits)}）"):
                    for i, (title, url) in enumerate(crossref_doi_hits.items(), 1):
                        st.markdown(f"{i}. {title}  \n🔗 [DOI 連結]({url})", unsafe_allow_html=True)

            if scopus_hits:
                with st.expander(f"\U0001F7E2 Scopus 標題命中（{len(scopus_hits)}）"):
                    for i, (title, url) in enumerate(scopus_hits.items(), 1):
                        st.markdown(f"{i}. {title}  \n🔗 [Scopus 連結]({url})", unsafe_allow_html=True)

            if scholar_hits:
                with st.expander(f"\U0001F7E2 Google Scholar 標題命中（{len(scholar_hits)}）"):
                    for i, (title, url) in enumerate(scholar_hits.items(), 1):
                        st.markdown(f"{i}. {title}  \n🔗 [Scholar 連結]({url})", unsafe_allow_html=True)

            if not (crossref_doi_hits or scopus_hits or scholar_hits):
                st.info("沒有命中任何參考文獻。")

        with similar_tab:
            if scholar_similar:
                for i, (title, url) in enumerate(scholar_similar.items(), 1):
                    with st.expander(f"{i}. {title}"):
                        st.markdown(f"🔗 [Google Scholar 結果連結]({url})", unsafe_allow_html=True)
                        st.warning("⚠️ 此為相似標題，請人工確認是否為正確文獻。")
            else:
                st.info("無標題相似但不一致的結果。")

        with miss_tab:
            if not_found:
                for i, title in enumerate(not_found, 1):
                    scholar_url = f"https://scholar.google.com/scholar?q={urllib.parse.quote(title)}"
                    st.markdown(f"{i}. {title}  \n🔗 [Google Scholar 搜尋]({scholar_url})", unsafe_allow_html=True)
                st.markdown("👉 請考慮手動搜尋 Google Scholar。")
            else:
                st.success("所有標題皆成功查詢！")

        # 下載結果
        st.markdown("---")
        export_data = []
        for ref, title in title_pairs:
            if ref in crossref_doi_hits:
                export_data.append([ref, "Crossref 有 DOI 資訊", crossref_doi_hits[ref]])
            elif ref in scopus_hits:
                export_data.append([ref, "標題命中（Scopus）", scopus_hits[ref]])
            elif ref in scholar_hits:
                export_data.append([ref, "標題命中（Google Scholar）", scholar_hits[ref]])
            elif ref in scholar_similar:
                export_data.append([ref, "Google Scholar 類似標題", scholar_similar[ref]])
            elif ref in not_found:
                scholar_url = f"https://scholar.google.com/scholar?q={urllib.parse.quote(ref)}"
                export_data.append([ref, "查無結果", scholar_url])

        total_refs = len(title_pairs)
        matched_exact = len(crossref_doi_hits) + len(scopus_hits) + len(scholar_hits)
        matched_similar = len(scholar_similar)
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
        df_export = pd.DataFrame(export_data, columns=["原始參考文獻", "查核結果", "連結"])
        df_export.to_csv(csv_buffer, index=False)

        st.markdown(f"""
        📌 查核結果說明：本篇論文共有 {total_refs} 篇參考文獻，其中：

        - {len(crossref_doi_hits)} 篇為「Crossref 有 DOI 資訊」
        - {len(scopus_hits)} 篇為「標題命中（Scopus）」
        - {len(scholar_hits)} 篇為「標題命中（Google Scholar）」
        - {len(scholar_similar)} 篇為「Google Scholar 類似標題」
        - {len(not_found)} 篇為「查無結果」
        """)
        st.markdown("---")
        
        st.subheader("📥 下載查詢結果")
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