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
import unicodedata


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
    # 移除 dash 類符號
    dash_variants = ["-", "–", "—", "−", "‑", "‐"]
    for d in dash_variants:
        text = text.replace(d, "")

    # 標準化字符（例如全形轉半形）
    text = unicodedata.normalize('NFKC', text)

    # 過濾掉標點符號、符號類別（不刪文字！）
    cleaned = []
    for ch in text:
        if unicodedata.category(ch)[0] in ("L", "N", "Z"):  # L=Letter, N=Number, Z=Space
            cleaned.append(ch.lower())
        # else: 跳過標點與符號

    # 統一空白
    return re.sub(r'\s+', ' ', ''.join(cleaned)).strip()

# 專門給補救命中的清洗
def clean_title_for_remedial(text):
    """給補救查詢用的清洗：去掉單獨數字、標點、全形轉半形等"""
    # 標準化字元（全形轉半形）
    text = unicodedata.normalize('NFKC', text)

    # 移除 dash 類符號
    dash_variants = ["-", "–", "—", "−", "‑", "‐"]
    for d in dash_variants:
        text = text.replace(d, "")

    # 移除單獨的數字詞（如頁碼、卷號）
    text = re.sub(r'\b\d+\b', '', text)

    # 保留字母、數字、空白
    cleaned = []
    for ch in text:
        if unicodedata.category(ch)[0] in ("L", "N", "Z"):  # L=Letter, N=Number, Z=Space
            cleaned.append(ch.lower())

    return re.sub(r'\s+', ' ', ''.join(cleaned)).strip()

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
            return search_url, "error"

        organic = results.get("organic_results", [])
        if not organic:
            return search_url, "no_result"

        cleaned_query = clean_title(title)
        for result in organic:
            result_title = result.get("title", "")
            cleaned_result = clean_title(result_title)

            if not cleaned_query or not cleaned_result:
                continue

            if cleaned_query == cleaned_result:
                return search_url, "match"
            if SequenceMatcher(None, cleaned_query, cleaned_result).ratio() >= threshold:
                return search_url, "similar"

        return search_url, "no_result"

    except Exception as e:
        st.session_state["serpapi_error"] = f"API 查詢錯誤：{e}"
        return search_url, "error"


#補救搜尋
def search_scholar_by_ref_text(ref_text, api_key):
    search_url = f"https://scholar.google.com/scholar?q={urllib.parse.quote(ref_text)}"
    params = {
        "engine": "google_scholar",
        "q": ref_text,
        "api_key": api_key,
        "num": 1
    }

    try:
        results = GoogleSearch(params).get_dict()
        organic = results.get("organic_results", [])
        if not organic:
            return search_url, "no_result"

        first_title = organic[0].get("title", "")

        # 使用乾淨版清洗（不影響主流程）
        cleaned_ref = clean_title_for_remedial(ref_text)
        cleaned_first = clean_title_for_remedial(first_title)

        if cleaned_first in cleaned_ref or cleaned_ref in cleaned_first:
            return search_url, "remedial"

        return search_url, "no_result"

    except Exception as e:
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
def extract_reference_section_from_bottom(paragraphs, start_keywords=None, stop_keywords=None):
    """
    從底部往上找出參考文獻區段起點，並向下擷取至遇到停止關鍵詞（如附錄）為止
    回傳格式：matched_section, matched_keyword
    """
    if start_keywords is None:
        start_keywords = [
            "參考文獻", "參考資料", "references", "reference",
            "bibliography", "works cited", "literature cited"
        ]

    if stop_keywords is None:
        stop_keywords = ["附錄", "附錄一"]

    for i in reversed(range(len(paragraphs))):
        para = paragraphs[i].strip()

        # 跳過太長或包含標點的段落（可能是正文）
        if len(para) > 30 or re.search(r'[.,;:]', para):
            continue

        normalized = para.lower()
        if normalized in start_keywords:
            # 從 i+1 開始擷取，直到遇到 stop_keyword 為止
            result = []
            for p in paragraphs[i + 1:]:
                if any(kw in p.lower() for kw in stop_keywords):
                    break
                result.append(p)
            return result, para

    return [], None

# ========== 萃取參考文獻 (加強版) ==========
#也是需要把附錄截掉
def clip_until_stop(paragraphs_after, stop_keywords=None):
    if stop_keywords is None:
        stop_keywords = ["附錄", "附錄一"]
    result = []
    for para in paragraphs_after:
        if any(kw in para.lower() for kw in stop_keywords):
            break
        result.append(para)
    return result

def extract_reference_section_improved(paragraphs):
    """
    改進的參考文獻區段識別，使用多重策略和容錯機制
    返回：(參考文獻段落列表, 識別到的標題, 識別方法)
    """
    
    def is_reference_format(text):
        """判斷段落是否符合參考文獻格式"""
        text = text.strip()
        if len(text) < 10:  # 太短不太可能是參考文獻
            return False
            
        # APA格式：包含年份格式 (YYYY)
        if re.search(r'\(\d{4}[a-c]?\)', text):
            return True
            
        # IEEE格式：開頭是 [數字]
        if re.match(r'^\[\d+\]', text):
            return True
            
        # 通用格式：包含作者姓名模式
        if re.search(r'[A-Z][a-z]+,\s*[A-Z]\.', text):
            return True
            
        return False
    
    def is_chapter_title(text):
        """判斷是否為章節標題"""
        text = text.strip()
        
        # 中文數字章節標題
        chinese_nums = r'[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾]+'
        if re.match(f'^{chinese_nums}[、．.]', text):
            return True
            
        # 阿拉伯數字章節標題
        if re.match(r'^\d+[、．.]', text):
            return True
            
        # 英文章節標題
        if re.match(r'^[IVX]+[、．.]', text):
            return True
            
        return False
    
    # 策略1：明確的參考文獻標題識別
    reference_keywords = [
        "參考文獻", "references", "reference", 
        "bibliography", "works cited", "literature cited"
    ]
    
    for i, para in enumerate(paragraphs):
        para_clean = para.strip()
        para_lower = para_clean.lower()
        
        # 檢查章節標題格式的參考文獻
        if is_chapter_title(para_clean):
            for keyword in reference_keywords:
                if keyword in para_lower:
                    return clip_until_stop(paragraphs[i + 1:]), para_clean, "章節標題識別"
        
        # 檢查純標題格式
        if para_lower in reference_keywords:
            return paragraphs[i + 1:], para_clean, "純標題識別"
        
        # 補強：參考文獻前有數字或符號 
        para_no_space = re.sub(r'\s+', '', para_clean)
        if re.match(r'^(\d+|[IVXLCDM]+|[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾]+)?[、．. ]?參考文獻$', para_no_space):
            return clip_until_stop(paragraphs[i + 1:]), para_clean, "章節標題識別"

    
    # 策略2：關鍵字模糊匹配
    for i in range(len(paragraphs) - 1, -1, -1):  # 從底部向上
        para = paragraphs[i].strip().lower()
        
        # 跳過明顯的正文段落
        if len(para) > 100:  # 太長可能是正文
            continue
            
        # 模糊匹配參考文獻相關詞彙
        fuzzy_keywords = ["reference", "參考", "bibliography", "文獻"]
        for keyword in fuzzy_keywords:
            if keyword in para and len(para) < 50:
                # 檢查後續段落是否有參考文獻格式
                remaining = paragraphs[i + 1:]
                if remaining and sum(1 for p in remaining[:5] if is_reference_format(p)) >= 2:
                    return clip_until_stop(paragraphs[i + 1:]), para_clean, "章節標題識別"
    
    # 所有策略都失敗
    return [], None, "未找到參考文獻區段"







# ========== 偵測格式 ==========
def detect_reference_style(ref_text):
    # IEEE 通常開頭是 [1]，或含有英文引號 "標題"
    if re.match(r'^\[\d+\]', ref_text) or '"' in ref_text:
        return "IEEE"
    # APA 常見結構：作者（西元年）。標題。 支援全形或半形括號與句點混用
    if re.search(r'[（(](\d{4}[a-c]?|n\.d\.)[）)]?[。\.]?', ref_text, re.IGNORECASE):
        return "APA"
    # APA_LIKE：逗號或句點 + 年份 + 句點/句號，但需排除前5字含數字的情況
    matches = re.finditer(r'([,，.。])\s*(\d{4})[.。]', ref_text)
    for match in matches:
        start_idx = match.start(2)
        pre_context = ref_text[max(0, start_idx - 5):start_idx]
        if not re.search(r'\d', pre_context):  # 前5字元不能有數字
            return "APA_LIKE"
    # 新增這段：處理「，2011，。」格式
    if re.search(r'，\s*\d{4}\s*，\s*。', ref_text):
        return "APA_LIKE"
        
    return "Unknown"

# ========== 段落合併器（PDF 專用，根據參考文獻開頭切分） ==========

def is_reference_head(para):
    """
    判斷段落是否為參考文獻開頭（APA、APA_LIKE 或 IEEE）
    """

    # APA：允許任何 4 位數字或 n.d.，但後面必須是 . 空白（符合 APA 格式）
    if re.search(r"[（(](\d{4}[a-c]?|n\.d\.)[）)]?[。\.]?\s?", para, re.IGNORECASE):
        return True

    # IEEE：開頭為 [數字]
    if re.match(r"^\[\d+\]", para):
        return True

    # APA_LIKE：, 或 . 或 ， 後面緊接 4 位數字 + . 或 。 
    matches = re.finditer(r'([,，.。])\s*(\d{4})[.。]', para)
    for match in matches:
        start_idx = match.start(2)
        pre_context = para[max(0, start_idx - 5):start_idx]
        if not re.search(r'\d', pre_context):  # 前 5 個字元不能有數字
            return True

    return False

def detect_and_split_ieee(paragraphs):
    """
    若第一段為 IEEE 格式 [1] 開頭，則將整段合併並依據 [數字] 切割
    """
    if not paragraphs:
        return None

    first_line = paragraphs[0].strip()
    if not re.match(r'^\[\d+\]', first_line):
        return None

    full_text = ' '.join(paragraphs)  # 將換行視為空格
    refs = re.split(r'(?=\[\d+\])', full_text)  # 用 lookahead 保留切割點
    return [r.strip() for r in refs if r.strip()]

def merge_references_by_heads(paragraphs):
    merged = []

    for para in paragraphs:
        # 若包含多個 APA 年份或 APA_LIKE 年份，先嘗試強制切分
        apa_count = len(re.findall(r'[（(](\d{4}[a-c]?|n\.d\.)[）)]\s*[。\.]', para, re.IGNORECASE))
        apalike_count = 0
        for match in re.finditer(r'([,，.。])\s*(\d{4})[.。]', para):
            year_pos = match.start(2)
            pre_context = para[max(0, year_pos - 5):year_pos]
            if not re.search(r'\d', pre_context):
                apalike_count += 1

        if apa_count >= 2 or apalike_count >= 2:
            sub_refs = split_multiple_apa_in_paragraph(para)
            merged.extend([s.strip() for s in sub_refs if s.strip()])
        else:
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
    改良版：從出現第 2 筆 APA 或 APA_LIKE 年份起，每筆往前固定 5 字元切段。
    - APA： (2020)、(2020a)、(n.d.)
    - APA_LIKE： , 2020. 或 .2020. 等，且前 5 字元不能含數字
    """

    # 找 APA 年份位置
    apa_matches = list(re.finditer(r'[（(](\d{4}[a-c]?|n\.d\.)[）)]?[。\.]?', paragraph, re.IGNORECASE))


    # 找 APA_LIKE 年份位置（正常格式：, 或 . + 年份 + .）
    apalike_matches = []
    for match in re.finditer(r'([,，.。])\s*(\d{4})[.。]', paragraph):
        year_pos = match.start(2)
        pre_context = paragraph[max(0, year_pos - 5):year_pos]
        if not re.search(r'\d', pre_context):  # 前 5 字元不能有數字
            apalike_matches.append(match)

    # 額外處理格式：，2011，。
    for match in re.finditer(r'，\s*(\d{4})\s*，\s*。', paragraph):
        year_pos = match.start(1)
        pre_context = paragraph[max(0, year_pos - 5):year_pos]
        if not re.search(r'\d', pre_context):  # 前 5 字元不能有數字
            apalike_matches.append(match)

    # 統一處理：合併 APA 與 APA_LIKE 的 match list，按位置排序
    all_matches = apa_matches + apalike_matches
    all_matches.sort(key=lambda m: m.start())

    # 若找到至少兩個以上有效年份，就進行切分
    if len(all_matches) < 2:
        return [paragraph]

    # 每筆回溯固定 5 個字元切割
    split_indices = []
    for match in all_matches[1:]:  # 從第 2 筆開始切
        cut_index = max(0, match.start() - 5)
        split_indices.append(cut_index)

    # 切段
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
        # 改進：結尾可以是「.」、「。」或「,」，排除數字之間的逗號或句點
        match = re.search(
            r'[（(](\d{4}[a-c]?|n\.d\.)[）)]\s*[。\.]\s*(.+?)(?:(?<!\d)[,，.。](?!\d)|$)',
            ref_text,
            re.IGNORECASE
        )
        if match:
            return match.group(2).strip(" ,.")  # 去除結尾的逗號或句號

    elif style == "IEEE":
        matches = re.findall(r'"([^"]+)"', ref_text)
        if matches:
            return max(matches, key=len).strip().rstrip(",.")
        fallback = re.search(r'(?<!et al)([A-Z][^,.]+[a-zA-Z])[,\.]', ref_text)
        if fallback:
            return fallback.group(1).strip(" ,.")

    elif style == "APA_LIKE":
        # 常見格式：, 或 . 或 ， 後面緊接 4 位數字 + . 或 。 
        match = re.search(
            r'[,，.。]\s*\d{4}(?:[.。],?)+\s*(.*?)(?:(?<!\d)[,，.。](?!\d)|$)',
            ref_text
        )
        if match:
            return match.group(1).strip(" ,。")

        # 🔧 新增支援格式：，，2011，。標題...
        match = re.search(
            r'，\s*(\d{4})\s*，\s*。[ \t]*(.+?)(?:[，。]|$)',
            ref_text
        )
        if match:
            return match.group(2).strip(" ,。")

    return None



# ========== 分析單筆參考文獻用（含 APA_LIKE 年份統計） ==========
def analyze_single_reference(ref_text, ref_index):
    style = detect_reference_style(ref_text)
    title = extract_title(ref_text, style)
    doi = extract_doi(ref_text)

    # 高亮顯示 APA/APA_LIKE 年份
    highlights = ref_text
    for match in reversed(list(re.finditer(r'\((\d{4}[a-c]?|n\.d\.)\)', ref_text, re.IGNORECASE))):
        start, end = match.span()
        highlights = highlights[:start] + "**" + highlights[start:end] + "**" + highlights[end:]

    # APA_LIKE 額外統計 1：逗號/句點 + 年份 + 句點
    apalike_count = 0
    for match in re.finditer(r'([,，.。])\s*(\d{4})[.。]', ref_text):
        year_pos = match.start(2)
        pre_context = ref_text[max(0, year_pos - 5):year_pos]
        if not re.search(r'\d', pre_context):
            apalike_count += 1

    # APA_LIKE 額外統計 2：格式為 ，2011，。
    extra_apalike_count = len(re.findall(r'，\s*\d{4}\s*，\s*。', ref_text))

    # 合計所有年份出現次數
    apa_year_count = len(re.findall(r'\((\d{4}[a-c]?|n\.d\.)\)', ref_text, re.IGNORECASE))
    year_count = apa_year_count + apalike_count + extra_apalike_count

    # 輸出到 UI
    st.markdown(f"**{ref_index}.**")
    st.write(highlights)
    st.markdown(f"""
    • 📰 **擷取標題**：{title if title else "❌ 無法擷取"}  
    • 🔍 **擷取 DOI**：{doi if doi else "❌ 無 DOI"}  
    • 🏷️ **偵測風格**：{style}  
    • 📅 **年份出現次數**：{year_count}  
    """)
    return (ref_text, title) if title else None

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

        file_progress = st.progress(0.0)
        scholar_logs = []

        # 檔案解析
        if file_ext == "docx":
            paragraphs = extract_paragraphs_from_docx(uploaded_file)
        elif file_ext == "pdf":
            paragraphs = extract_paragraphs_from_pdf(uploaded_file)
        else:
            st.warning(f"⚠️ 檔案 {uploaded_file.name} 格式不支援，將略過。")
            continue

        # 偵測參考文獻段落
        matched_section, matched_keyword = extract_reference_section_from_bottom(paragraphs)
        matched_method = "標準偵測"

        if not matched_section:
            matched_section, matched_keyword, matched_method = extract_reference_section_improved(paragraphs)
            if not matched_section:
                st.error(f"❌ 無法識別檔案 {uploaded_file.name} 的參考文獻區段，已跳過該檔案。")
                continue


        with st.expander("擷取到的參考文獻段落（供人工檢查）"):
            st.markdown(f"參考文獻段落偵測方式：**{matched_method}**")
            st.markdown(f"起始關鍵段落：**{matched_keyword}**")
            for i, para in enumerate(matched_section, 1):
                st.markdown(f"**{i}.** {para}")

        # 合併
        if file_ext == "pdf":
            ieee_refs = detect_and_split_ieee(matched_section)
            merged_references = ieee_refs if ieee_refs else merge_references_by_heads(matched_section)
        else:
            merged_references = matched_section

        title_pairs = []
        with st.expander("逐筆參考文獻解析結果（合併後段落 + 標題 + DOI + 格式）"):
            ref_index = 1
            for para in merged_references:
                year_matches = re.findall(r'\((\d{4}[a-c]?|n\.d\.)\)', para, re.IGNORECASE)
                apalike_matches = [
                    match for match in re.finditer(r'([,，.。])\s*(\d{4})[.。]', para)
                    if not re.search(r'\d', para[max(0, match.start(2) - 5):match.start(2)])
                ]
                extra_apalike_matches = list(re.finditer(r'，\s*(\d{4})\s*，\s*。', para))
                if len(year_matches) + len(apalike_matches) + len(extra_apalike_matches) >= 2:
                    sub_refs = split_multiple_apa_in_paragraph(para)
                    st.markdown(f"🔍 強制切分段落（原始段落含 {len(year_matches) + len(apalike_matches)} 年份）：")
                    for sub_ref in sub_refs:
                        result = analyze_single_reference(sub_ref, ref_index)
                        if result:
                            title_pairs.append(result)
                        ref_index += 1
                else:
                    result = analyze_single_reference(para, ref_index)
                    if result:
                        title_pairs.append(result)
                    ref_index += 1

        # 查詢
        crossref_doi_hits = {}
        scopus_hits = {}
        scholar_hits = {}
        scholar_similar = {}
        scholar_remedial = {}
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
                scholar_logs.append(f"Google Scholar 回傳類型：{gs_type} / 標題：{title}")
                if gs_type == "match":
                    scholar_hits[ref] = gs_url
                elif gs_type == "similar":
                    scholar_similar[ref] = gs_url
                elif gs_type == "error":
                    not_found.append(ref)
                else:
                    remedial_url, remedial_type = search_scholar_by_ref_text(ref, SERPAPI_KEY)
                    scholar_logs.append(f"Google Scholar 回傳類型：remedial_{remedial_type} / 標題：{title}")
                    if remedial_type == "remedial":
                        scholar_remedial[ref] = remedial_url
                    else:
                        not_found.append(ref)

            file_progress.progress(i / len(title_pairs))

        if scholar_logs:
            with st.expander("Google Scholar 查詢過程紀錄"):
                for line in scholar_logs:
                    st.text(line)

        # 每個檔案都記錄結果
        file_results = {
            "filename": uploaded_file.name,
            "title_pairs": title_pairs,
            "crossref_doi_hits": crossref_doi_hits,
            "scopus_hits": scopus_hits,
            "scholar_hits": scholar_hits,
            "scholar_similar": scholar_similar,
            "scholar_remedial": scholar_remedial,
            "not_found": not_found,
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        all_results.append(file_results)

    # 檔案處理完畢，儲存至 session
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
            not_found = result.get("not_found", [])
            title_pairs = result.get("title_pairs", [])
            crossref_doi_hits = result.get("crossref_doi_hits", {})
            scholar_similar = result.get("scholar_similar", {})
            scholar_remedial = result.get("scholar_remedial", {})
            uploaded_filename = result.get("filename", "未知檔案")
            report_time = result.get("report_time", "未記錄")
            scopus_hits = result.get("scopus_hits", {})
            scholar_hits = result.get("scholar_hits", {})
            

            st.markdown(f"📄 檔案名稱： {uploaded_filename}")
            matched_count = len(crossref_doi_hits) + len(scopus_hits) + len(scholar_hits) + len(scholar_remedial)
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
                if scholar_remedial:
                    with st.expander(f"\U0001F7E2 Google Scholar 補救命中（{len(scholar_remedial)}）"):
                        for i, (title, url) in enumerate(scholar_remedial.items(), 1):
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
                elif ref in result.get("scholar_remedial", {}):
                    export_data.append([filename, ref, "Google Scholar 補救命中", result["scholar_remedial"][ref]])
                elif ref in result["not_found"]:
                    scholar_url = f"https://scholar.google.com/scholar?q={urllib.parse.quote(ref)}"
                    export_data.append([filename, ref, "查無結果", scholar_url])
        total_refs = sum(len(r["title_pairs"]) for r in st.session_state.query_results)
        matched_exact = sum(len(r["crossref_doi_hits"]) + len(r["scopus_hits"]) + len(r["scholar_hits"]) for r in st.session_state.query_results)
        matched_similar = sum(len(r["scholar_similar"]) for r in st.session_state.query_results)
        matched_remedial = sum(len(r.get("scholar_remedial", {})) for r in st.session_state.query_results)
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
        matched_remedial = sum(len(r.get("scholar_remedial", {})) for r in st.session_state.query_results)
        matched_similar = sum(len(r["scholar_similar"]) for r in st.session_state.query_results)
        matched_notfound = sum(len(r["not_found"]) for r in st.session_state.query_results)


        st.markdown(f"""
        📌 查核結果說明：本次共處理 **{total_files} 篇論文**，總共擷取 **{total_refs} 篇參考文獻**，其中：

        - {matched_crossref} 篇為「Crossref 有 DOI 資訊」
        - {matched_scopus} 篇為「標題命中（Scopus）」
        - {matched_scholar} 篇為「標題命中（Google Scholar）」
        - {matched_remedial} 篇為「Google Scholar 補救命中」
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