# 📚 Reference Checker

Reference Checker 是一個簡單實用的工具，可自動從 Word 檔（`.docx`）中擷取參考文獻標題，並透過 **Scopus API** 與 **Crossref API** 進行查詢，協助研究者快速判斷參考資料的正確性與可查詢性。

> 本專案全程採用 **vibe coding** 開發方式

---

主要功能：
- 自動擷取 APA 或 IEEE 格式的文獻標題
- 優先查詢 Scopus API，若無結果再查 Crossref API
- 根據查詢結果自動分類為「Scopus 命中」「Crossref 完全符合」「Crossref 相似」「均無結果」
- 提供結果視覺化、分頁顯示，方便使用者人工確認


安裝與執行方式：
1. 安裝 Python 3.8 或以上版本
2. 安裝套件並執行

   git clone https://github.com/pauline-chou/reference-checker.git
   cd reference-checker
   pip install -r requirements.txt
   streamlit run app.py

3. API 金鑰設定（需先至 [Elsevier](https://dev.elsevier.com/) 申請 Scopus API Key）：
4. 在專案根目錄建立文字檔 scopus_key.txt，內容如下：你的_scopus_api_key
5. 請記得將程式碼中的 "your_email@example.com" 替換為你自己的聯絡信箱，否則 Crossref 可能拒絕查詢請求。


分類邏輯：
1. Scopus 命中（🟢）：標題完全一致
2. Crossref 完全包含（🟢）：查詢標題完全出現在 Crossref 結果標題中
3. Crossref 相似（🟡）：標題相似度大於等於 0.9，建議人工確認
4. 查無結果（🔴）：Scopus 與 Crossref 均無查到結果


聯絡方式：
如您在使用過程中有任何建議或問題，歡迎與我聯繫~
Email: pauline687@gmail.com
