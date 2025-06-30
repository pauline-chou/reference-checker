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


# ========================================= 所有規則封裝  =========================================
# ========== 年份規則 ==========
def is_valid_year(year_str):
    try:
        year = int(year_str)
        return 1000 <= year <= 2050
    except:
        return False
    
# ========== 抓附錄 ========== 
def is_appendix_heading(text):
    text = text.strip()
    return bool(re.match(
        r'^((\d+|[IVXLCDM]+|[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾]+)[、．. ]?\s*)?(附錄|APPENDIX)',
        text,
        re.IGNORECASE
    ))

# ========== APA規則 ==========    
def find_apa(ref_text):
    """
    判斷一段參考文獻是否為 APA 格式（標準括號年份 or n.d.）
    標準格式：Lin, J. (2020). Title.
    支援變體：中英文括號、句號符號、n.d. 年份
    """
    apa_match = re.search(r'[（(](\d{4}[a-c]?|n\.d\.)[）)]?[。\.]?', ref_text, re.IGNORECASE)
    if not apa_match:
        return False

    year_str = apa_match.group(1)[:4]
    year_pos = apa_match.start(1)

    # 避免像 887(2020) 這種前方是數字的情況
    pre_context = ref_text[max(0, year_pos - 5):year_pos]
    if re.search(r'\d', pre_context):
        return False

    if year_str.isdigit():
        return is_valid_year(year_str)
    return apa_match.group(1).lower() == "n.d."

def match_apa_title_section(ref_text):
    """
    擷取 APA 結構中的標題段落（位於年份後）
    範例：Lin, J. (2020). Title here.
    - 支援標點：.、。 、,
    - 避免誤抓數字中的逗號或句號
    """
    return re.search(
        r'[（(](\d{4}[a-c]?|n\.d\.)[）)]\s*[\.,，。]?\s*(.+?)(?:(?<!\d)[,，.。](?!\d)|$)',
        ref_text,
        re.IGNORECASE
    )

def find_apa_matches(ref_text):
    """
    回傳符合 APA 格式的年份 match（含位置、原文等）
    """
    APA_PATTERN = r'[（(](\d{4}[a-c]?|n\.d\.)[）)]?[。\.]?'
    matches = []
    for m in re.finditer(APA_PATTERN, ref_text, re.IGNORECASE):
        year_str = m.group(1)[:4]
        year_pos = m.start(1)
        pre_context = ref_text[max(0, year_pos - 5):year_pos]
        if re.search(r'\d', pre_context):
            continue
        if year_str.isdigit() and is_valid_year(year_str):
            matches.append(m)
        elif m.group(1).lower() == "n.d.":
            matches.append(m)
    return matches


# ========== APA_LIKE規則 ==========
def find_apalike(ref_text):
    valid_years = []

    # 類型 1：標點 + 年份 + 標點（常見格式）
    for match in re.finditer(r'[,，.。]\s*(\d{4}[a-c]?)[.。，]', ref_text):
        year_str = match.group(1)
        year_pos = match.start(1)
        year_core = year_str[:4]
        if not is_valid_year(year_core):
            continue

        # 前 5 字元不能有數字（排除 3.2020. 類型）
        pre_context = ref_text[max(0, year_pos - 5):year_pos]
        if re.search(r'\d', pre_context):
            continue

        # 若年份後 5 字元是 .加數字，或像 .v06、.abc 等常見 DOI 結尾，則排除
        after_context = ref_text[match.end(1):match.end(1) + 5]
        if re.match(r'\.(\d{1,2}|[a-z0-9]{2,})', after_context, re.IGNORECASE):
            continue

        # 排除 arXiv 尾巴，例如 arXiv:xxxx.xxxxx, 2023
        arxiv_pattern = re.compile(
            r'arxiv:\d{4}\.\d{5}[^a-zA-Z0-9]{0,3}\s*[,，]?\s*' + re.escape(year_str),
            re.IGNORECASE
        )
        arxiv_match = arxiv_pattern.search(ref_text)
        if arxiv_match and arxiv_match.start() < year_pos:
            continue

        valid_years.append((year_str, year_pos))

    # 類型 2：特殊格式「，2020，。」（中文常見）
    for match in re.finditer(r'，\s*(\d{4}[a-c]?)\s*，\s*。', ref_text):
        year_str = match.group(1)
        year_pos = match.start(1)
        year_core = year_str[:4]
        if not is_valid_year(year_core):
            continue
        pre_context = ref_text[max(0, year_pos - 5):year_pos]
        if re.search(r'\d', pre_context):
            continue
        valid_years.append((year_str, year_pos))

    return valid_years

def match_apalike_title_section(ref_text):
# 類型 1：常見格式（, 2020. Title.）
    match = re.search(
        r'[,，.。]\s*(\d{4}[a-c]?)(?:[.。，])+\s*(.*?)(?:(?<!\d)[,，.。](?!\d)|$)',
        ref_text
    )
    if match:
        return match

    # 類型 2：特殊中文格式（，2020，。Title）
    return re.search(
        r'，\s*(\d{4}[a-c]?)\s*，\s*。[ \t]*(.+?)(?:[，。]|$)',
        ref_text
    )

def find_apalike_matches(ref_text):
    """
    回傳符合 APA_LIKE 格式的年份 match（含位置、原文等）
    """
    matches = []

    # 類型 1：標點 + 年份 + 標點（常見格式）
    pattern1 = r'[,，.。]\s*(\d{4}[a-c]?)[.。，]'
    for m in re.finditer(pattern1, ref_text):
        year_str = m.group(1)
        year_pos = m.start(1)
        year_core = year_str[:4]
        if not is_valid_year(year_core):
            continue
        pre_context = ref_text[max(0, year_pos - 5):year_pos]
        after_context = ref_text[m.end(1):m.end(1) + 5]
        if re.search(r'\d', pre_context):
            continue
        # 新增條件：年份後若接 DOI 型式則排除
        if re.match(r'\.(\d{1,2}|[a-z0-9]{2,})', after_context, re.IGNORECASE):
            continue
        arxiv_pattern = re.compile(
            r'arxiv:\d{4}\.\d{5}[^a-zA-Z0-9]{0,3}\s*[,，]?\s*' + re.escape(year_str),
            re.IGNORECASE
        )
        if arxiv_pattern.search(ref_text) and arxiv_pattern.search(ref_text).start() < year_pos:
            continue
        matches.append(m)

    # 類型 2：特殊中文格式「，2020，。」
    pattern2 = r'，\s*(\d{4}[a-c]?)\s*，\s*。'
    for m in re.finditer(pattern2, ref_text):
        year_str = m.group(1)
        year_pos = m.start(1)
        year_core = year_str[:4]  # ✅ 補上 year_core
        pre_context = ref_text[max(0, year_pos - 5):year_pos]
        if re.search(r'\d', pre_context):
            continue
        if is_valid_year(year_core):
            matches.append(m)

    return matches


# ================================================================================================


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
def extract_reference_section_from_bottom(paragraphs, start_keywords=None):
    """
    從底部往上找出參考文獻區段起點，並向下擷取至遇到停止標題（如附錄）為止
    回傳格式：matched_section, matched_keyword
    """
    if start_keywords is None:
        start_keywords = [
            "參考文獻", "參考資料", "references", "reference",
            "bibliography", "works cited", "literature cited",
            "references and citations"
        ]

    for i in reversed(range(len(paragraphs))):
        para = paragraphs[i].strip()

        # 跳過太長或包含標點的段落（可能是正文）
        if len(para) > 30 or re.search(r'[.,;:]', para):
            continue

        normalized = para.lower()
        if normalized in start_keywords:
            # 從 i+1 開始擷取，直到遇到附錄為止
            result = []
            for p in paragraphs[i + 1:]:
                if is_appendix_heading(p):
                    break
                result.append(p)
            return result, para

    return [], None



# ========== 萃取參考文獻 (加強版) ==========
#也是需要把附錄截掉
def clip_until_stop(paragraphs_after):
    result = []
    for para in paragraphs_after:
        if is_appendix_heading(para):
            break
        result.append(para)
    return result

def extract_reference_section_improved(paragraphs):
    """
    改進的參考文獻區段識別，從底部往上掃描，使用多重策略和容錯機制
    返回：(參考文獻段落列表, 識別到的標題, 識別方法)
    """

    def is_reference_format(text):
        text = text.strip()
        if len(text) < 10:
            return False
        if re.search(r'\(\d{4}[a-c]?\)', text):  # APA 年份格式
            return True
        if re.match(r'^\[\d+\]', text):         # IEEE 編號格式
            return True
        if re.search(r'[A-Z][a-z]+,\s*[A-Z]\.', text):  # 作者名樣式
            return True
        return False

    reference_keywords = [
        "參考文獻", "references", "reference",
        "bibliography", "works cited", "literature cited",
        "references and citations", "參考文獻格式"
    ]

    # ✅ 從底部往上掃描
    for i in reversed(range(len(paragraphs))):
        para = paragraphs[i].strip()
        para_lower = para.lower()
        para_nospace = re.sub(r'\s+', '', para_lower)

        # ✅ 純標題相符（e.g. "References"）
        if para_lower in reference_keywords:
            return clip_until_stop(paragraphs[i + 1:]), para, "純標題識別（底部）"

        # ✅ 容錯標題（含章節編號）
        if re.match(
            r'^(第[一二三四五六七八九十百千萬壹貳參肆伍陸柒捌玖拾百千萬]+章[、.．]?\s*)?(參考文獻|references?|bibliography|works cited|literature cited|references and citations)\s*$',
            para_lower
        ):


            return clip_until_stop(paragraphs[i + 1:]), para, "章節標題識別（底部）"

        # ✅ 模糊關鍵字 + 後面段落像 APA 格式
        fuzzy_keywords = ["reference", "參考", "bibliography", "文獻", " REFERENCES AND CITATIONS"]
        if any(para_lower.strip() == k for k in fuzzy_keywords):  # ❗ 只接受整行剛好等於關鍵字
            if i + 1 < len(paragraphs):
                next_paras = paragraphs[i+1:i+6]
                if sum(1 for p in next_paras if is_reference_format(p)) >= 1:
                    return clip_until_stop(paragraphs[i + 1:]), para.strip(), "模糊標題+內容識別"



    return [], None, "未找到參考文獻區段"







# ========== 偵測格式 ==========
def detect_reference_style(ref_text):
    # IEEE 通常開頭是 [1]，或含有英文引號 "標題"
    if re.match(r'^\[\d+\]', ref_text) or '"' in ref_text:
        return "IEEE"

    # APA：使用封裝後的 find_apa()
    if find_apa(ref_text):
        return "APA"

    # APA_LIKE：使用封裝後的 find_apalike()
    if find_apalike(ref_text):
        return "APA_LIKE"

    return "Unknown"

# ========== 段落合併器（PDF 專用，根據參考文獻開頭切分） ==========
def is_reference_head(para):
    """
    判斷段落是否為參考文獻開頭（APA、APA_LIKE 或 IEEE）
    """
    # APA：使用封裝好的判斷
    if find_apa(para):
        return True

    # IEEE：開頭為 [數字]
    if re.match(r"^\[\d+\]", para):
        return True

    # APA_LIKE：使用封裝好的判斷
    if find_apalike(para):
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
        # 使用封裝好的 APA 判斷
        apa_count = 1 if find_apa(para) else 0

        # 使用封裝好的 APA_LIKE 判斷（回傳多個年份位置）
        apalike_count = len(find_apalike(para))

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


def split_multiple_apa_in_paragraph(paragraph):
    """
    改良版：從出現第 2 筆 APA 或 APA_LIKE 年份起，每筆往前固定 5 字元切段。
    - APA： (2020)、(2020a)、(n.d.)
    - APA_LIKE： , 2020. 或 .2020. 等，且前 5 字元不能含數字
    """

    # 使用統一封裝函數找出所有 APA 與 APA_LIKE 的 matches
    apa_matches = find_apa_matches(paragraph)
    apalike_matches = find_apalike_matches(paragraph)

    all_matches = apa_matches + apalike_matches
    all_matches.sort(key=lambda m: m.start())

    # 若不到 2 筆則不切
    if len(all_matches) < 2:
        return [paragraph]

    # 每筆從前面固定回推 5 字元切割
    split_indices = []
    for match in all_matches[1:]:  # 從第 2 筆開始切
        cut_index = max(0, match.start() - 5)
        split_indices.append(cut_index)

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
        match = match_apa_title_section(ref_text)
        if match:
            year_str = match.group(1)[:4]
            if year_str.isdigit() and not is_valid_year(year_str):
                return None
            return match.group(2).strip(" ,。")

    elif style == "IEEE":
        matches = re.findall(r'"([^"]+)"', ref_text)
        if matches:
            return max(matches, key=len).strip().rstrip(",.")
        fallback = re.search(r'(?<!et al)([A-Z][^,.]+[a-zA-Z])[,\.]', ref_text)
        if fallback:
            return fallback.group(1).strip(" ,.")

    elif style == "APA_LIKE":
        match = match_apalike_title_section(ref_text)
        if match:
            year_str = match.group(1)
            after_fragment = ref_text[match.end(1):match.end(1)+5]
            if is_valid_year(year_str) and not re.match(r'\.\d', after_fragment):
                return match.group(2).strip(" ,。")

    return None



# ========== 分析單筆參考文獻用（含 APA_LIKE 年份統計） ==========
def analyze_single_reference(ref_text, ref_index):
    style = detect_reference_style(ref_text)
    title = extract_title(ref_text, style)
    doi = extract_doi(ref_text)

    # APA 與 APA_LIKE 年份標註（高亮）
    highlights = ref_text
    # 所有 match 統一加入，並根據位置從後往前高亮，避免重疊 offset 錯亂
    all_year_matches = find_apa_matches(ref_text) + find_apalike_matches(ref_text)
    all_year_matches.sort(key=lambda m: m.start(), reverse=True)
    for match in all_year_matches:
        start, end = match.span()
        highlights = highlights[:start] + "**" + highlights[start:end] + "**" + highlights[end:]

    # === 年份統計 ===
    apa_year_count = len(find_apa_matches(ref_text))
    apalike_year_count = len(find_apalike_matches(ref_text))
    year_count = apa_year_count + apalike_year_count

    # === 輸出到 UI ===
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

        # ========== 擷取參考文獻區段：先跑加強版，找不到再 fallback ==========
        matched_section, matched_keyword, matched_method = extract_reference_section_improved(paragraphs)

        if not matched_section:
            matched_section, matched_keyword = extract_reference_section_from_bottom(paragraphs)
            matched_method = "標準標題識別（底部）"

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

        # 補丁：若第一筆為 Unknown 格式，合併第一、二筆段落
        if len(merged_references) >= 2:
            first_style = detect_reference_style(merged_references[0])
            if first_style == "Unknown":
                merged_references[0] = merged_references[0].strip() + " " + merged_references[1].strip()
                del merged_references[1]  # 刪除原第二筆


        title_pairs = []
        with st.expander("逐筆參考文獻解析結果（合併後段落 + 標題 + DOI + 格式）"):
            ref_index = 1
            for para in merged_references:
                # 統一取得 APA 和 APA_LIKE 所有年份 match
                apa_matches = find_apa_matches(para)
                apalike_matches = find_apalike_matches(para)
                total_valid_years = len(apa_matches) + len(apalike_matches)

                if total_valid_years >= 2:
                    sub_refs = split_multiple_apa_in_paragraph(para)
                    st.markdown(f"🔍 強制切分段落（原始段落含 {total_valid_years} 個年份）：")
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