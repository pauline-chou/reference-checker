# 📚 Reference Checker

Reference Checker 是一個簡單實用的工具，可自動從 Word 檔（`.docx`）中擷取參考文獻標題，並透過 **Scopus API** 與 **Crossref API** 進行查詢，協助研究者快速判斷參考資料的正確性與可查詢性。

本專案全程採用 **vibe coding** 開發方式

⚠️ 注意事項
為節省比對時間，本系統僅查核具有 DOI 的期刊論文，**不會檢查期刊名稱、作者、卷期或頁碼**，比對僅以「篇名」為主。本系統提供之比對結果僅供**初步參考**，建議使用者在比對後仍應進行人工確認。**請勿將本系統結果作為學術倫理判斷之唯一依據。**
---

主要功能：
- 自動擷取 APA 或 IEEE 格式的文獻標題
- 若參考文獻中有 DOI，則直接比對，優先採用
- 優先查詢 Scopus API，若無結果再查 Crossref API
- 根據查詢結果自動分類為「DOI 命中」「Scopus 命中」「Crossref 完全符合」「Crossref 相似」「均無結果」
- 提供結果視覺化、分頁顯示，方便使用者人工確認
- 支援結果下載為 CSV 檔案


安裝與執行方式：
1. 安裝 Python 3.8 或以上版本
2. 安裝套件並執行

   git clone https://github.com/pauline-chou/reference-checker.git
   cd reference-checker
   pip install -r requirements.txt
   streamlit run app.py

3. API 金鑰設定（需先至 [Elsevier](https://dev.elsevier.com/) 申請 Scopus API Key）：
4. 在專案根目錄建立文字檔 scopus_key.txt，內容如下：你的_scopus_api_key
5. Crossref 查詢需要一組聯絡用 email，請將程式中的 `"your_email@example.com"` 替換為你自己的信箱，以符合 Crossref API 規範。


分類邏輯：
1. DOI 命中（🟢）：參考文獻中含 DOI，且成功查詢對應資料
2. Scopus 命中（🟢）：標題完全一致
3. Crossref 完全包含（🟢）：查詢標題完全出現在 Crossref 結果標題中
4. Crossref 相似（🟡）：標題相似度大於等於 0.9，建議人工確認
5. 查無結果（🔴）：Scopus 與 Crossref 均無查到結果


聯絡方式：
如您在使用過程中有任何建議或問題，歡迎與我聯繫~
Email: pauline687@gmail.com
