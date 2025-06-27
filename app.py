import streamlit as st
import re
import urllib.parse
from docx import Document
import requests
from difflib import SequenceMatcher
import pandas as pd
from datetime import datetime
from io import StringIO
from serpapi import GoogleSearch
import fitz 
import re


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
        "count": 3
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
    params = {
        "engine": "google_scholar",
        "q": title,
        "api_key": api_key,
        "num": 3
    }

    try:
        results = GoogleSearch(params).get_dict()

        if "error" in results:
            error_msg = results["error"]
            st.session_state["serpapi_error"] = error_msg
            if any(keyword in error_msg.lower() for keyword in ["exceed", "limit", "run out", "searches"]):
                st.session_state["serpapi_exceeded"] = True
            return search_url, "no_result"


        organic = results.get("organic_results", [])
        if not organic:
            return search_url, "no_result"

        cleaned_query = clean_title(title)
        for result in organic:
            result_title = result.get("title", "")
            cleaned_result = clean_title(result_title)
            if cleaned_query == cleaned_result:
                return search_url, "match"
            if SequenceMatcher(None, cleaned_query, cleaned_result).ratio() >= threshold:
                return search_url, "similar"

        return search_url, "no_result"

    except Exception as e:
        st.session_state["serpapi_error"] = f"API 查詢錯誤：{e}"
        return search_url, "no_result"

    
# ========== Word 處理 ==========
def extract_paragraphs_from_docx(file):
    # 使用 BytesIO 處理 UploadedFile
    doc = Document(file)
    return [para.text.strip() for para in doc.paragraphs if para.text.strip()]

# ========== PDF 處理 ==========
def extract_paragraphs_from_pdf(file):
    text = ""
    with fitz.open(stream=file.read(), filetype="pdf") as doc:
        for page in doc:
            page_text = page.get_text("text")
            text += page_text + "\n"
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return paragraphs

# ========== 萃取參考文獻 ==========
def extract_reference_section_from_bottom(paragraphs, start_keywords=None):
    """
    從底部往上找出真正的參考文獻區段起點，並回傳關鍵字來源
    回傳格式：matched_section, matched_keyword
    """
    if start_keywords is None:
        start_keywords = [
            "參考文獻", "references", "reference",
            "bibliography", "works cited", "literature cited"
        ]

    for i in reversed(range(len(paragraphs))):
        para = paragraphs[i].strip()

        # 跳過太長或包含標點的段落（可能是正文）
        if len(para) > 30 or re.search(r'[.,;:]', para):
            continue

        normalized = para.lower()
        if normalized in start_keywords:
            return paragraphs[i + 1:], para  # ✅ 回傳段落和關鍵字本身

    return [], None


# ========== 偵測格式 ==========
def detect_reference_style(ref_text):
    # IEEE 通常開頭是 [1]，或含有英文引號 "標題"
    if re.match(r'^\[\d+\]', ref_text) or '"' in ref_text:
        return "IEEE"
    # APA 常見結構：作者（西元年）。標題。
    if re.search(r'\((\d{4}[a-c]?|n\.d\.)\)\.', ref_text, re.IGNORECASE):
        return "APA"
    return "Unknown"

# ========== 段落合併器（PDF 專用，根據參考文獻開頭切分） ==========

def is_reference_head(para):
    """
    判斷段落是否為參考文獻開頭（APA 或 IEEE）
    APA 條件：段落中出現 (XXXX). 且後面為 . 空白
    IEEE 條件：開頭為 [數字]
    """

    # APA：允許任何 4 位數字或 n.d.，但後面必須是 . 空白（符合 APA 格式）
    if re.search(r"\((\d{4}[a-c]?|n\.d\.)\)\.\s", para, re.IGNORECASE):
        return True

    # IEEE：開頭為 [數字]
    if re.match(r"^\[\d+\]", para):
        return True

    return False

def merge_references_by_heads(paragraphs):
    merged = []

    for para in paragraphs:
        # 若同一段中有多個 APA 年份出現，先嘗試分段
        if len(re.findall(r'\(\d{4}[a-c]?\)', para)) >= 2:
            sub_refs = split_multiple_apa_in_paragraph(para)
            
            # ✅ 既然是我們切出來的，就全部視為獨立文獻
            merged.extend([s.strip() for s in sub_refs if s.strip()])

        else:
            # 只有一篇時，再正常依據開頭進行合併判斷
            if is_reference_head(para):
                merged.append(para.strip())
            else:
                if merged:
                    merged[-1] += " " + para.strip()
                else:
                    merged.append(para.strip())

    return merged


#合併錯誤的檢查 可能會需二次分割
def split_multiple_apa_in_paragraph(paragraph):
    """
    改良版：從出現第 2 筆 (年份) 起，往前尋找 `X. (年份)` 的開頭作為切分點。
    具體做法：搜尋 `. (199X)` 前一個字元，作為切點，確保新段落從作者縮寫開始。
    """
    matches = list(re.finditer(r'\((\d{4}[a-z]?|n\.d\.)\)\.', paragraph, re.IGNORECASE))
    if len(matches) < 2:
        return [paragraph]

    split_indices = []

    for i in range(1, len(matches)):
        year_pos = matches[i].start()
        # 回溯至 ". " 再往前 1 個字元
        lookback_window = paragraph[max(0, year_pos - 10):year_pos]
        dot_space_match = re.search(r'([A-Z]\.)\s$', lookback_window)
        if dot_space_match:
            cut_offset = year_pos - (len(lookback_window) - dot_space_match.start(1))
            split_indices.append(cut_offset)
        else:
            # fallback：如找不到，仍以年份起點為切點
            split_indices.append(year_pos)

    # 實際分段
    segments = []
    start = 0
    for idx in split_indices:
        segments.append(paragraph[start:idx].strip())
        start = idx
    segments.append(paragraph[start:].strip())

    return [s for s in segments if s]



# ========== 擷取標題 ==========
def extract_title(ref_text, style):
    if style == "APA":
        match = re.search(r'\((\d{4}[a-c]?|n\.d\.)\)\.\s(.+?)(?:\.\s|$)', ref_text, re.IGNORECASE)
        if match:
            return match.group(2).strip()
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
    <span style="font-size: 16px; font-weight: bold;">注意事項</span><br>
    <span style="font-size: 15px; color: #444;">
    為節省核對時間，本系統只查對有 DOI 碼的期刊論文。並未檢查期刊名稱、作者、卷期、頁碼，僅針對篇名進行核對。本系統僅提供初步篩選參考，比對後應進行人工核對，不得直接以本系統核對結果作為學術倫理判斷的依據。
    </span>
</div>
""", unsafe_allow_html=True)
st.markdown(" ")

uploaded_files = st.file_uploader("請上傳最多 10 個 Word 或 PDF 檔案", type=["docx", "pdf"], accept_multiple_files=True)
# 攔截超過 10 檔案的情況
if uploaded_files and len(uploaded_files) > 10:
    st.error("❌ 上傳檔案超過 10 個，請刪除部分檔案後再試一次。")
    st.stop()

start_button = st.button("🚀 開始查詢")

if uploaded_files and start_button:
    st.subheader("📊 正在查詢中，請稍候...")

    all_results = []

    for uploaded_file in uploaded_files:
        file_ext = uploaded_file.name.split(".")[-1].lower()
        st.markdown(f"📄 處理檔案： {uploaded_file.name}")

        # 顯示獨立進度條（要寫在檔案 for 迴圈內）
        file_progress = st.progress(0.0)

        # 檔案解析
        if file_ext == "docx":
            paragraphs = extract_paragraphs_from_docx(uploaded_file)
            skip_section_detection = False
        elif file_ext == "pdf":
            paragraphs = extract_paragraphs_from_pdf(uploaded_file)
            skip_section_detection = False
            
        else:
            st.warning(f"⚠️ 檔案 {uploaded_file.name} 格式不支援，將略過。")
            continue


        # 偵測參考文獻段落
        matched_section = []
        if not skip_section_detection:
            matched_section, matched_keyword = extract_reference_section_from_bottom(paragraphs)
            # fallback：如果沒找到任何符合的關鍵字段落，就直接用整份處理
            if not matched_section:
                st.warning(f"⚠️ 檔案 {uploaded_file.name} 未偵測到參考文獻標題，將嘗試以全文處理。")
                matched_section = paragraphs
        else:
            matched_section = paragraphs

        with st.expander("擷取到的參考文獻段落（供人工檢查）"):
            if matched_keyword:
                st.markdown(f"🔍 偵測到參考文獻起點關鍵字為：**{matched_keyword}**")
            else:
                st.markdown("🔍 未偵測到特定關鍵字，改以整份文件處理。")

            for i, para in enumerate(matched_section, 1):
                st.markdown(f"**{i}.** {para}")

        
        # 合併 PDF 分段參考文獻（使用統一的「開頭合併法」）
        if file_ext == "pdf":
            merged_references = merge_references_by_heads(matched_section)
        else:
            merged_references = matched_section




        # 改為使用 merged_references 處理每筆文獻
        title_pairs = []
        with st.expander("逐筆參考文獻解析結果（合併後段落 + 標題 + DOI + 格式）"):
            ref_index = 1
            for para in merged_references:
                # 若同段包含多個 APA 年份，先強制分段處理
                year_matches = list(re.finditer(r'\(\d{4}[a-c]?\)', para))
                if len(year_matches) >= 2:
                    sub_refs = split_multiple_apa_in_paragraph(para)
                    st.markdown(f"🔍 強制切分段落（原始段落含 {len(year_matches)} 年份）：")
                    for i, sub_ref in enumerate(sub_refs, 1):
                        style = detect_reference_style(sub_ref)
                        title = extract_title(sub_ref, style)
                        doi = extract_doi(sub_ref)

                        highlights = sub_ref
                        for match in reversed(list(re.finditer(r'\(\d{4}[a-c]?\)', sub_ref))):
                            start, end = match.span()
                            highlights = highlights[:start] + "**" + highlights[start:end] + "**" + highlights[end:]


                        st.markdown(f"**{ref_index}.**")
                        st.write(highlights)
                        st.markdown(f"""
                        • 📰 **擷取標題**：{title if title else "❌ 無法擷取"}  
                        • 🔍 **擷取 DOI**：{doi if doi else "❌ 無 DOI"}  
                        • 🏷️ **偵測風格**：`{style}`  
                        • 📅 **年份出現次數**：{len(re.findall(r'\(\d{4}[a-c]?\)', sub_ref))}  
                        """)
                        if title:
                            title_pairs.append((sub_ref, title))
                        ref_index += 1
                else:
                    ref = para
                    style = detect_reference_style(ref)
                    title = extract_title(ref, style)
                    doi = extract_doi(ref)

                    highlights = ref
                    for match in reversed(list(re.finditer(r'\(\d{4}[a-c]?\)', ref))):
                        start, end = match.span()
                        highlights = highlights[:start] + "**" + highlights[start:end] + "**" + highlights[end:]

                    st.markdown(f"**{ref_index}.**")
                    st.write(highlights)
                    st.markdown(f"""
                    • 📰 **擷取標題**：{title if title else "❌ 無法擷取"}  
                    • 🔍 **擷取 DOI**：{doi if doi else "❌ 無 DOI"}  
                    • 🏷️ **偵測風格**：`{style}`  
                    • 📅 **年份出現次數**：{len(re.findall(r'\((\d{4}[a-c]?|n\.d\.)\)', ref, re.IGNORECASE))}  
                    """)
                    if title:
                        title_pairs.append((ref, title))
                    ref_index += 1



        # 查詢處理
        crossref_doi_hits = {}
        scopus_hits = {}
        scholar_hits = {}
        scholar_similar = {}
        not_found = []

        for i, (ref, title) in enumerate(title_pairs, 1):
            doi = extract_doi(ref)
            if doi:
                title_from_doi, url = search_crossref_by_doi(doi)
                if title_from_doi:
                    crossref_doi_hits[ref] = url
                    file_progress.progress(i / len(title_pairs))
                    continue

            url = search_scopus_by_title(title)
            if url:
                scopus_hits[ref] = url
            else:
                gs_url, gs_type = search_scholar_by_title(title, SERPAPI_KEY)
                if gs_type == "match":
                    scholar_hits[ref] = gs_url
                elif gs_type == "similar":
                    scholar_similar[ref] = gs_url
                else:
                    not_found.append(ref)

            file_progress.progress(i / len(title_pairs))

        file_results = {
            "filename": uploaded_file.name,
            "title_pairs": title_pairs,
            "crossref_doi_hits": crossref_doi_hits,
            "scopus_hits": scopus_hits,
            "scholar_hits": scholar_hits,
            "scholar_similar": scholar_similar,
            "not_found": not_found,
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        all_results.append(file_results)

    st.session_state.query_results = all_results

# 如果 SerpAPI 用量已超過，顯示一次性提示
if st.session_state.get("serpapi_exceeded"):
    st.warning("⚠️ SerpAPI 查詢額度已用完，因此部分結果可能無法從 Google Scholar 查得，請稍後再試或確認 API 使用狀況。")
elif st.session_state.get("serpapi_error"):
    st.warning(f"⚠️ Google Scholar 查詢時發生錯誤：{st.session_state['serpapi_error']}")




# ========== 上傳並處理 ==========


if st.session_state.query_results:
        st.markdown("---")
        st.subheader("📊 查詢結果分類")
        for result in st.session_state.query_results:
            not_found = result["not_found"]
            title_pairs = result["title_pairs"]
            crossref_doi_hits = result["crossref_doi_hits"]
            scholar_similar = result["scholar_similar"]
            uploaded_filename = result["filename"]
            report_time = result["report_time"]
            scopus_hits = result["scopus_hits"]
            scholar_hits = result["scholar_hits"]

            st.markdown(f"📄 檔案名稱： {uploaded_filename}")
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
        for result in st.session_state.query_results:
            filename = result["filename"]
            for ref, title in result["title_pairs"]:
                if ref in result["crossref_doi_hits"]:
                    export_data.append([filename, ref, "Crossref 有 DOI 資訊", result["crossref_doi_hits"][ref]])
                elif ref in result["scopus_hits"]:
                    export_data.append([filename, ref, "標題命中（Scopus）", result["scopus_hits"][ref]])
                elif ref in result["scholar_hits"]:
                    export_data.append([filename, ref, "標題命中（Google Scholar）", result["scholar_hits"][ref]])
                elif ref in result["scholar_similar"]:
                    export_data.append([filename, ref, "Google Scholar 類似標題", result["scholar_similar"][ref]])
                elif ref in result["not_found"]:
                    scholar_url = f"https://scholar.google.com/scholar?q={urllib.parse.quote(ref)}"
                    export_data.append([filename, ref, "查無結果", scholar_url])
        total_refs = sum(len(r["title_pairs"]) for r in st.session_state.query_results)
        matched_exact = sum(len(r["crossref_doi_hits"]) + len(r["scopus_hits"]) + len(r["scholar_hits"]) for r in st.session_state.query_results)
        matched_similar = sum(len(r["scholar_similar"]) for r in st.session_state.query_results)
        unmatched = sum(len(r["not_found"]) for r in st.session_state.query_results)

        header = StringIO()
        header.write(f"報告產出時間：{report_time}\n\n")
        header.write("說明：\n")
        header.write("為節省核對時間，本系統只查對有DOI碼的期刊論文。且並未檢查期刊名稱、作者、卷期、頁碼。只針對篇名進行核對。\n")
        header.write("本系統只是為了提供初步篩選，比對後應接著進行人工核對，任何人都不應該以本系統核對結果作為任何學術倫理判斷之基礎。\n\n")

        csv_buffer = StringIO()
        csv_buffer.write(header.getvalue())
        if not export_data:
            st.warning("⚠️ 沒有可匯出的查核結果。")
        else:
            df_export = pd.DataFrame(export_data, columns=["檔案名稱", "原始參考文獻", "查核結果", "連結"])
            df_export.to_csv(csv_buffer, index=False)

        # 統計所有檔案的總數
        total_files = len(st.session_state.query_results)
        total_refs = sum(len(r["title_pairs"]) for r in st.session_state.query_results)
        matched_crossref = sum(len(r["crossref_doi_hits"]) for r in st.session_state.query_results)
        matched_scopus = sum(len(r["scopus_hits"]) for r in st.session_state.query_results)
        matched_scholar = sum(len(r["scholar_hits"]) for r in st.session_state.query_results)
        matched_similar = sum(len(r["scholar_similar"]) for r in st.session_state.query_results)
        matched_notfound = sum(len(r["not_found"]) for r in st.session_state.query_results)


        st.markdown(f"""
        📌 查核結果說明：本次共處理 **{total_files} 篇論文**，總共擷取 **{total_refs} 篇參考文獻**，其中：

        - {matched_crossref} 篇為「Crossref 有 DOI 資訊」
        - {matched_scopus} 篇為「標題命中（Scopus）」
        - {matched_scholar} 篇為「標題命中（Google Scholar）」
        - {matched_similar} 篇為「Google Scholar 類似標題」
        - {matched_notfound} 篇為「查無結果」
        """)
        st.markdown("---")
        
        st.subheader("📥 下載查詢結果")

        st.download_button(
            label="📤 下載結果 CSV 檔",
            data=csv_buffer.getvalue().encode('utf-8-sig'),
            file_name="reference_results.csv",
            mime="text/csv"
        )
        st.write("🔁 若要重新上傳檔案，請按下鍵盤上的 F5 或點擊瀏覽器重新整理按鈕")    