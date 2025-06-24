import streamlit as st
import requests
import urllib.parse

st.set_page_config(page_title="Reference Checker", layout="centered")

st.title("📚 Reference Checker")
st.write("上傳 Word 檔 (.docx)，系統將從參考文獻區擷取引用，並使用 Scopus API 進行查詢。")

# 🔐 優先從 st.secrets 讀取 API Key，其次讀取本地 txt
def get_scopus_key():
    if "scopus_api_key" in st.secrets:
        return st.secrets["scopus_api_key"]
    else:
        try:
            with open("scopus_key.txt", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            st.error("❌ 找不到 Scopus API 金鑰，請設定 .streamlit/secrets.toml 或提供 scopus_key.txt")
            st.stop()

# ✅ 在主程式前就定義好 key
SCOPUS_API_KEY = get_scopus_key()

# 🔎 查詢 Scopus API
def search_scopus_by_title(title):
    base_url = "https://api.elsevier.com/content/search/scopus"
    params = {
        "query": f"TITLE(\"{title}\")",
        "count": 3,
    }
    headers = {
        "X-ELS-APIKey": SCOPUS_API_KEY,
        "Accept": "application/json"
    }

    try:
        response = requests.get(base_url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            entries = data.get("search-results", {}).get("entry", [])
            if not entries:
                return "❌ 查無結果"
            top = entries[0]
            title_found = top.get("dc:title", "")
            url = top.get("prism:url", "")
            return f"[✅ 找到：{title_found}]({url})"
        else:
            return f"❌ API 錯誤（狀態碼：{response.status_code}）"
    except Exception as e:
        return f"❌ 查詢失敗：{e}"

# 📤 使用者輸入標題進行測試
title = st.text_input("請輸入文獻標題（測試用）", "")
if title:
    with st.spinner("查詢中..."):
        result = search_scopus_by_title(title)
        st.markdown(result)
