import streamlit as st
import pandas as pd
import io # バイトデータを扱うために必要

# --- ヘルパー関数: 文字コードを自動判別して読み込む ---
def read_csv_with_fallback(bytes_data, filename):
    """
    指定されたバイトデータをCSVとして読み込む。
    まず UTF-8 (BOM付き) で試し、ダメなら CP932 (Shift_JIS) で試す。
    """
    last_exception = None # 最後のエラーを保持
    try:
        # まず UTF-8 (BOM付き) 'utf-8-sig' で試す
        bytes_data.seek(0) # 念のためポインタを先頭に
        df = pd.read_csv(bytes_data, encoding='utf-8-sig', low_memory=False)
        st.write(f"    - 「{filename}」を UTF-8 (BOM付き) で読み込み成功。")
        return df
    except UnicodeDecodeError as e:
        last_exception = e
        st.write(f"    - 「{filename}」: UTF-8(BOM付き) 失敗。CP932 (Shift_JIS) を試します...")
        try:
            # BytesIOのポインタを先頭に戻すことが重要
            bytes_data.seek(0)
            # 次に CP932 (Shift_JIS) で試す
            df = pd.read_csv(bytes_data, encoding='cp932', low_memory=False)
            st.write(f"    - 「{filename}」を CP932 (Shift_JIS) で読み込み成功。")
            return df
        except Exception as e_cp932:
            last_exception = e_cp932
            # どちらのエンコーディングでも読み込めなかった場合
            st.error(f"ファイル「{filename}」の読み込みに失敗しました。サポートされていない文字コードか、ファイル形式が不正です。エラー: {last_exception}")
            # 特定のエラーとして上位に伝える
            raise ValueError(f"文字コード判別不能 ({filename})") from last_exception
    except Exception as e_other:
        last_exception = e_other
        # read_csv 自体の他のエラー (ファイル形式がCSVでないなど)
        st.error(f"ファイル「{filename}」の読み込み中に予期せぬエラーが発生しました: {last_exception}")
        raise ValueError(f"ファイル読み込みエラー ({filename})") from last_exception

# --- Streamlit アプリ本体 ---
st.set_page_config(layout="wide") # 横幅を広く使う設定
st.title("販売実績の仕入先コード、荷受人コード 郵便番号紐付け")

st.write("""
販売実績CSVに含まれる「仕入先コード」「荷受人コード」に、
マスターCSVファイルを使って郵便番号を紐付け、結果を出力します。
""")

# --- ファイルアップロードセクション ---
st.header("1. ファイルのアップロード")

col1, col2, col3 = st.columns(3) # アップローダーを横に並べる

with col1:
    uploaded_sales_files = st.file_uploader(
        "販売実績CSV (最大12個)", # ラベルを短く
        type='csv',
        accept_multiple_files=True,
        key="sales_uploader"
    )
    if uploaded_sales_files:
        if len(uploaded_sales_files) > 12:
            st.error(f"最大12個までです。({len(uploaded_sales_files)} 個選択中)")
        else:
            st.success(f"{len(uploaded_sales_files)} 個 受付完了")

with col2:
    uploaded_supplier_master = st.file_uploader(
        "仕入先マスタCSV", # ラベルを短く
        type='csv',
        accept_multiple_files=False,
        key="supplier_uploader"
    )
    if uploaded_supplier_master:
        st.success(f"受付完了")

with col3:
    uploaded_consignee_master = st.file_uploader(
        "荷受人マスタCSV", # ラベルを短く
        type='csv',
        accept_multiple_files=False,
        key="consignee_uploader"
    )
    if uploaded_consignee_master:
        st.success(f"受付完了")


# --- 処理実行セクション ---
st.header("2. 処理実行と結果")

# すべての必須ファイルがアップロードされているかを確認
all_files_uploaded = (
    uploaded_sales_files and
    0 < len(uploaded_sales_files) <= 12 and # ファイルが1つ以上12個以下
    uploaded_supplier_master and
    uploaded_consignee_master
)

# 処理実行ボタンと結果表示エリアを列で分ける
res_col1, res_col2 = st.columns([1, 3]) # 結果表示エリアを広く取る

with res_col1:
    if st.button("処理実行", disabled=not all_files_uploaded, use_container_width=True):
        st.session_state.processing_done = False # 実行時にリセット
        st.session_state.success_df = None
        st.session_state.failed_df = None
        st.session_state.error_message = None
        st.session_state.log_messages = [] # ログもリセット
        st.session_state.button_clicked = True # ボタンが押されたことを記録

        st.info("処理を開始します...")
        progress_bar = st.progress(0, text="ファイル読み込み中...")
        log_messages = ["**処理ログ:**"] # ローカル変数としても初期化

        try:
            # --- 1. ファイル読み込み ---
            total_files_to_read = len(uploaded_sales_files) + 2 # 全ファイル数
            files_read_count = 0
            log_area = st.empty() # ログ表示用のプレースホルダー
            log_messages.append("**ファイル読み込みログ:**")

            sales_dfs = []
            required_sales_cols = ['仕入先コード', '荷受人コード']
            log_messages.append("--- 販売実績ファイルの読み込み ---")
            for i, uploaded_file in enumerate(uploaded_sales_files):
                bytes_data = io.BytesIO(uploaded_file.getvalue())
                filename = uploaded_file.name
                log_messages.append(f"  - 読み込み試行: {filename}")
                # read_csv_with_fallback内でst.writeされるため、ここではログリストに追加
                df = read_csv_with_fallback(bytes_data, filename)
                if not all(col in df.columns for col in required_sales_cols):
                     error_msg = f"ファイル「{filename}」に必要な列 ({', '.join(required_sales_cols)}) が見つかりません。"
                     st.error(error_msg)
                     raise ValueError(error_msg)
                sales_dfs.append(df[required_sales_cols])
                files_read_count += 1
                progress_bar.progress(files_read_count / total_files_to_read, text=f"読み込み中: {filename}")
                log_messages.append(f"    -> 読み込み完了 ({filename})") # ファイル名を追加

            if not sales_dfs:
                 error_msg = "読み込み可能な販売実績ファイルがありませんでした。"
                 st.error(error_msg)
                 raise ValueError(error_msg)

            sales_data = pd.concat(sales_dfs, ignore_index=True)
            log_messages.append("--- 販売実績データの結合完了 ---")

            # 仕入先マスタ読み込み
            log_messages.append("--- 仕入先マスタの読み込み ---")
            required_supplier_cols = ['仕入先コード', '仕入先郵便番号']
            supplier_master_bytes = io.BytesIO(uploaded_supplier_master.getvalue())
            supplier_filename = uploaded_supplier_master.name
            log_messages.append(f"  - 読み込み試行: {supplier_filename}")
            supplier_master = read_csv_with_fallback(supplier_master_bytes, supplier_filename)
            if not all(col in supplier_master.columns for col in required_supplier_cols):
                error_msg = f"仕入先マスタに必要な列 ({', '.join(required_supplier_cols)}) が見つかりません。"
                st.error(error_msg)
                raise ValueError(error_msg)
            files_read_count += 1
            progress_bar.progress(files_read_count / total_files_to_read, text=f"読み込み中: {supplier_filename}")
            log_messages.append(f"    -> 読み込み完了 ({supplier_filename})")

            # 荷受人マスタ読み込み
            log_messages.append("--- 荷受人マスタの読み込み ---")
            required_consignee_cols = ['荷受人コード', '郵便番号']
            consignee_master_bytes = io.BytesIO(uploaded_consignee_master.getvalue())
            consignee_filename = uploaded_consignee_master.name
            log_messages.append(f"  - 読み込み試行: {consignee_filename}")
            consignee_master = read_csv_with_fallback(consignee_master_bytes, consignee_filename)
            if not all(col in consignee_master.columns for col in required_consignee_cols):
                 error_msg = f"荷受人マスタに必要な列 ({', '.join(required_consignee_cols)}) が見つかりません。"
                 st.error(error_msg)
                 raise ValueError(error_msg)
            files_read_count += 1
            progress_bar.progress(files_read_count / total_files_to_read, text=f"読み込み中: {consignee_filename}")
            log_messages.append(f"    -> 読み込み完了 ({consignee_filename})")
            progress_bar.progress(1.0, text="全ファイルの読み込み完了！")
            log_messages.append("--- 全ファイル読み込み完了 ---")

            # --- 2. コードの抽出・縦持ち変換・重複削除 ---
            log_messages.append("--- コードの抽出と整形開始 ---")
            progress_bar.progress(0.1, text="コード抽出中...") # 処理段階を示す

            # 仕入先コード
            supplier_codes = sales_data[['仕入先コード']].copy()
            supplier_codes.rename(columns={'仕入先コード': 'コード'}, inplace=True)
            supplier_codes['コード種別'] = '仕入先'

            # 荷受人コード
            consignee_codes = sales_data[['荷受人コード']].copy()
            consignee_codes.rename(columns={'荷受人コード': 'コード'}, inplace=True)
            consignee_codes['コード種別'] = '荷受人'

            all_codes = pd.concat([supplier_codes, consignee_codes], ignore_index=True)
            log_messages.append(f"  - 結合後の総コード数 (空含む): {len(all_codes)}")

            all_codes = all_codes.dropna(subset=['コード'])
            log_messages.append(f"  - 空コード除去後の数: {len(all_codes)}")
            # コードを文字列に統一し、前後の空白を削除
            all_codes['コード'] = all_codes['コード'].astype(str).str.strip()
            # 空白削除後に空文字になったものや、特定の不正コードを除外したい場合はここに追加
            all_codes = all_codes[all_codes['コード'] != '']
            log_messages.append(f"  - 空白除去後の数: {len(all_codes)}")

            unique_codes = all_codes.drop_duplicates().reset_index(drop=True)
            log_messages.append(f"  - 重複除去後のユニークコード数: {len(unique_codes)}")
            log_messages.append("--- コード抽出と整形完了 ---")
            progress_bar.progress(0.3, text="マスタデータ準備中...")

            # --- 3. マスターデータ準備 ---
            log_messages.append("--- マスターデータの準備開始 ---")

            # 仕入先マスタ
            supplier_master = supplier_master.dropna(subset=['仕入先コード', '仕入先郵便番号'])
            supplier_master['仕入先コード'] = supplier_master['仕入先コード'].astype(str).str.strip()
            # ★★★ 修正点: 仕入先コードからハイフンを削除 ★★★
            supplier_master['仕入先コード'] = supplier_master['仕入先コード'].str.replace('-', '', regex=False)
            # ★★★ ここまで ★★★
            supplier_master = supplier_master.drop_duplicates(subset=['仕入先コード'], keep='last')
            log_messages.append(f"  - 準備後の仕入先マスタ件数: {len(supplier_master)}")

            # 荷受人マスタ
            consignee_master = consignee_master.dropna(subset=['荷受人コード', '郵便番号'])
            consignee_master['荷受人コード'] = consignee_master['荷受人コード'].astype(str).str.strip()
            # ★★★ 荷受人コードも必要ならハイフン削除を有効化 ★★★
            # consignee_master['荷受人コード'] = consignee_master['荷受人コード'].str.replace('-', '', regex=False)
            # ★★★ ここまで ★★★
            consignee_master = consignee_master.drop_duplicates(subset=['荷受人コード'], keep='last')
            log_messages.append(f"  - 準備後の荷受人マスタ件数: {len(consignee_master)}")

            log_messages.append("--- マスターデータの準備完了 ---")
            progress_bar.progress(0.5, text="郵便番号の紐付け中...")

            # --- 4. マスターデータと結合 (マージ) ---
            # 仕入先コードと紐付け
            merged_supplier = pd.merge(
                unique_codes[unique_codes['コード種別'] == '仕入先'],
                supplier_master[['仕入先コード', '仕入先郵便番号']],
                left_on='コード',
                right_on='仕入先コード',
                how='left' # unique_codes を基準に結合
            )
            # 荷受人コードと紐付け
            merged_consignee = pd.merge(
                unique_codes[unique_codes['コード種別'] == '荷受人'],
                consignee_master[['荷受人コード', '郵便番号']],
                left_on='コード',
                right_on='荷受人コード',
                how='left'
            )

            # 結合結果を整形し、再度結合
            merged_supplier = merged_supplier[['コード種別', 'コード', '仕入先郵便番号']]
            merged_supplier.rename(columns={'仕入先郵便番号': '郵便番号'}, inplace=True)

            merged_consignee = merged_consignee[['コード種別', 'コード', '郵便番号']]

            # 全てのコード（紐付けできたもの、できなかったものを含む）
            merged_all = pd.concat([merged_supplier, merged_consignee], ignore_index=True)
            # 郵便番号も文字列に統一し、NaNや "nan" を空文字に置換
            merged_all['郵便番号'] = merged_all['郵便番号'].fillna('').astype(str)
            merged_all['郵便番号'] = merged_all['郵便番号'].replace('nan', '', regex=False)


            log_messages.append("--- 郵便番号の紐付け完了 ---")
            progress_bar.progress(0.8, text="結果の分割中...")

            # --- 5. 結果の分割 (成功リストと失敗リスト) ---
            # 郵便番号が紐付けられた（空でない）ものを成功リストへ
            # 郵便番号が数字だけで構成されているかなどもチェックするとより確実
            # ここでは単純に空文字でないかで判定
            success_df = merged_all[(merged_all['郵便番号'].notna()) & (merged_all['郵便番号'] != '')].copy()
            # 郵便番号が紐付けられなかった（空である）ものを失敗リストへ
            failed_df = merged_all[(merged_all['郵便番号'].isna()) | (merged_all['郵便番号'] == '')][['コード種別', 'コード']].copy()

            log_messages.append(f"  - 成功リスト件数: {len(success_df)}")
            log_messages.append(f"  - 失敗リスト件数: {len(failed_df)}")
            log_messages.append("--- 結果の分割完了 ---")
            progress_bar.progress(1.0, text="処理完了！")

            # 結果をセッション状態に保存
            st.session_state.processing_done = True
            st.session_state.success_df = success_df
            st.session_state.failed_df = failed_df
            st.session_state.log_messages = log_messages # ログも保存

            st.success("処理が完了しました！結果を表示します。")

        except ValueError as ve:
            st.error(f"処理を中断しました: {ve}")
            st.session_state.error_message = str(ve)
            st.session_state.log_messages = log_messages # エラーまでのログを保存
            progress_bar.empty()
        except Exception as e:
            st.error(f"処理中に予期せぬエラーが発生しました: {e}")
            st.exception(e)
            st.session_state.error_message = str(e)
            st.session_state.log_messages = log_messages # エラーまでのログを保存
            progress_bar.empty()


# ---- 結果表示エリア ----
# ボタンが押された後のみ結果エリアを評価する
if st.session_state.get('button_clicked', False):
    # エラーが発生した場合
    if st.session_state.get('error_message'):
        with res_col2: # エラーメッセージも右カラムに表示
             st.error(f"エラーのため処理を完了できませんでした。")
             # エラー詳細とログはExpanderに入れる
             with st.expander("エラー詳細とログを表示", expanded=True):
                 st.error(st.session_state.error_message)
                 log_messages = st.session_state.get('log_messages', ["ログがありません。"])
                 st.code('\n'.join(log_messages), language='text')

    # 正常に完了した場合
    elif st.session_state.get('processing_done', False):
        with res_col2: # 結果表示は右側のカラムに
            st.subheader("処理結果")

            # 成功リスト表示とダウンロード
            st.markdown("##### 成功リスト (郵便番号紐付け完了)")
            success_df_display = st.session_state.get('success_df', pd.DataFrame()) # デフォルトは空DF
            st.dataframe(success_df_display, use_container_width=True, height=300) # 高さを指定
            if not success_df_display.empty:
                # CSVダウンロード用にエンコーディングを指定
                success_csv = success_df_display.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button(
                    label="📥 成功リストをCSVでダウンロード",
                    data=success_csv,
                    file_name='result_success.csv',
                    mime='text/csv',
                )
            else:
                st.caption("成功リストは空です。")

            st.divider() # 区切り線

            # 失敗リスト表示とダウンロード
            st.markdown("##### 失敗リスト (郵便番号紐付け不可)")
            failed_df_display = st.session_state.get('failed_df', pd.DataFrame())
            st.dataframe(failed_df_display, use_container_width=True, height=300) # 高さを指定
            if not failed_df_display.empty:
                # CSVダウンロード用にエンコーディングを指定
                failed_csv = failed_df_display.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button(
                    label="📥 失敗リストをCSVでダウンロード",
                    data=failed_csv,
                    file_name='result_failed.csv',
                    mime='text/csv',
                )
            else:
                st.caption("失敗リストは空です。")

            # 処理ログの表示 (任意)
            with st.expander("処理ログを表示"):
                 log_messages = st.session_state.get('log_messages', ["ログがありません。"])
                 st.code('\n'.join(log_messages), language='text')

# ボタンが押される前の初期状態、またはファイル未選択の場合
elif not all_files_uploaded and st.session_state.get("sales_uploader") is not None: # 一度でもアップロード操作があったか
    with res_col1: # ボタン列に警告を出す
        st.warning("必要なファイルをすべてアップロードし、販売実績ファイルが12個以下であることを確認してください。")
else: # まだ何も操作されていない初期状態
     with res_col2:
         st.caption("ファイルを選択し、「処理実行」ボタンを押してください。")