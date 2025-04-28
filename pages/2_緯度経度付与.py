import streamlit as st
import pandas as pd
import io
import numpy as np

# --- ヘルパー関数: 文字コードを自動判別して読み込む (app.pyからコピー) ---
def read_csv_with_fallback(bytes_data, filename):
    """
    指定されたバイトデータをCSVとして読み込む。
    まず UTF-8 (BOM付き) で試し、ダメなら CP932 (Shift_JIS) で試す。
    """
    last_exception = None # 最後のエラーを保持
    # BOM付きUTF-8, CP932, UTF-8(BOMなし) の順で試す
    encodings_to_try = ['utf-8-sig', 'cp932', 'utf-8']
    for encoding in encodings_to_try:
        try:
            bytes_data.seek(0) # 各試行の前にポインタを先頭に戻す
            df = pd.read_csv(bytes_data, encoding=encoding, low_memory=False)
            st.write(f"    - 「{filename}」を {encoding} で読み込み成功。")
            return df
        except UnicodeDecodeError as e:
            last_exception = e
            st.write(f"    - 「{filename}」: {encoding} での読み込み失敗。")
        except Exception as e:
            last_exception = e
            st.write(f"    - 「{filename}」: {encoding} で予期せぬエラー ({type(e).__name__})。")
            # ここでは他のエンコーディングも試す

    # すべてのエンコーディングで失敗した場合
    st.error(f"ファイル「{filename}」の読み込みに失敗しました。サポートされていない文字コードか、ファイル形式が不正です。エラー: {last_exception}")
    raise ValueError(f"文字コード判別不能 ({filename})") from last_exception

# --- Streamlit アプリ本体 ---
st.set_page_config(page_title="緯度経度付与", layout="wide") # ページタイトル設定
st.title("🌍 緯度経度付与")

st.write("""
郵便番号付きのコードリストCSV（`result_success.csv`）と、郵便番号-緯度経度対応のCSV (`geocode.csv`) をアップロードしてください。
リストの郵便番号に合致する緯度・経度を付与し、結果を成功リスト・失敗リストとして出力します。
""")

# --- ファイルアップロードセクション ---
st.header("1. ファイルのアップロード")

col1, col2 = st.columns(2)

with col1:
    uploaded_code_list_file = st.file_uploader(
        "郵便番号付きコードリスト CSV（result_success.csv）",
        type='csv',
        key="code_list_uploader"
    )
    if uploaded_code_list_file:
        st.success("コードリスト 受付完了")

with col2:
    uploaded_geocode_file = st.file_uploader(
        "郵便番号-緯度経度対応 CSV (geocode.csv)",
        type='csv',
        key="geocode_uploader"
    )
    if uploaded_geocode_file:
        st.success("Geocode CSV 受付完了")

# --- 処理実行セクション ---
st.header("2. 処理実行と結果")

all_files_uploaded = uploaded_code_list_file and uploaded_geocode_file

# 処理実行ボタンと結果表示エリアを列で分ける
res_col1, res_col2 = st.columns([1, 3])

with res_col1:
    if st.button("処理実行", disabled=not all_files_uploaded, use_container_width=True):
        st.session_state.geo_processing_done = False
        st.session_state.geo_success_df = None
        st.session_state.geo_failed_df = None
        st.session_state.geo_error_message = None
        st.session_state.geo_log_messages = []
        st.session_state.geo_button_clicked = True

        st.info("緯度経度付与処理を開始します...")
        progress_bar = st.progress(0, text="ファイル読み込み中...")
        log_messages = ["**処理ログ:**"]

        try:
            # --- 1. ファイル読み込み ---
            log_messages.append("--- ファイル読み込み開始 ---")

            # 郵便番号付きコードリスト読み込み
            required_code_list_cols = ['コード種別', 'コード', '郵便番号'] # 必要な列
            code_list_bytes = io.BytesIO(uploaded_code_list_file.getvalue())
            code_list_filename = uploaded_code_list_file.name
            log_messages.append(f"  - 読み込み試行: {code_list_filename}")
            code_list_df = read_csv_with_fallback(code_list_bytes, code_list_filename)
            if not all(col in code_list_df.columns for col in required_code_list_cols):
                error_msg = f"コードリストに必要な列 ({', '.join(required_code_list_cols)}) が見つかりません。"
                st.error(error_msg)
                raise ValueError(error_msg)
            log_messages.append(f"    -> 読み込み完了 ({code_list_filename})")
            progress_bar.progress(0.2, text=f"読み込み完了: {code_list_filename}")

            # Geocode CSV 読み込み
            required_geocode_cols = ['postal_cd', 'longitude', 'latitude'] # 必要な列
            geocode_bytes = io.BytesIO(uploaded_geocode_file.getvalue())
            geocode_filename = uploaded_geocode_file.name
            log_messages.append(f"  - 読み込み試行: {geocode_filename}")
            geocode_df_raw = read_csv_with_fallback(geocode_bytes, geocode_filename)
            if not all(col in geocode_df_raw.columns for col in required_geocode_cols):
                error_msg = f"Geocode CSVに必要な列 ({', '.join(required_geocode_cols)}) が見つかりません。"
                st.error(error_msg)
                raise ValueError(error_msg)
            log_messages.append(f"    -> 読み込み完了 ({geocode_filename})")
            progress_bar.progress(0.4, text=f"読み込み完了: {geocode_filename}")
            log_messages.append("--- ファイル読み込み完了 ---")

            # --- 2. データ準備 ---
            log_messages.append("--- データ準備開始 ---")
            progress_bar.progress(0.5, text="データ準備中...")

            # コードリストの郵便番号を整形 (文字列化、空白除去、ハイフン除去)
            code_list_df['郵便番号'] = code_list_df['郵便番号'].astype(str).str.strip()
            code_list_df['postal_key'] = code_list_df['郵便番号'].str.replace('-', '', regex=False)
            # 有効な郵便番号形式（7桁数字）を持つ行のみを保持
            original_code_list_count = len(code_list_df)
            code_list_df = code_list_df[code_list_df['postal_key'].str.match(r'^\d{7}$')].copy() # .copy()を追加
            log_messages.append(f"  - コードリスト: 元 {original_code_list_count} 件 -> 有効な郵便番号 {len(code_list_df)} 件")

            # Geocodeデータの準備と平均化
            geocode_df = geocode_df_raw[required_geocode_cols].copy()
            # 緯度経度を数値に変換 (数値以外は NaN になる)
            geocode_df['latitude'] = pd.to_numeric(geocode_df['latitude'], errors='coerce')
            geocode_df['longitude'] = pd.to_numeric(geocode_df['longitude'], errors='coerce')
            # 郵便番号を整形 (文字列化、空白除去、ハイフン除去)
            geocode_df['postal_cd'] = geocode_df['postal_cd'].astype(str).str.strip()
            geocode_df['postal_key'] = geocode_df['postal_cd'].str.replace('-', '', regex=False)
            # 緯度経度が両方とも有効で、郵便番号キーが7桁数字の行のみを対象にする
            original_geocode_count = len(geocode_df)
            geocode_df = geocode_df.dropna(subset=['latitude', 'longitude', 'postal_key'])
            geocode_df = geocode_df[geocode_df['postal_key'].str.match(r'^\d{7}$')]
            log_messages.append(f"  - Geocodeデータ: 元 {original_geocode_count} 件 -> 有効なデータ {len(geocode_df)} 件")

            # 郵便番号キーでグループ化し、緯度経度の平均を計算
            if not geocode_df.empty:
                geocode_avg = geocode_df.groupby('postal_key').agg(
                    latitude_avg=('latitude', 'mean'),
                    longitude_avg=('longitude', 'mean')
                ).reset_index()
                log_messages.append(f"  - 緯度経度の平均化完了 (ユニーク郵便番号 {len(geocode_avg)} 件)")
            else:
                geocode_avg = pd.DataFrame(columns=['postal_key', 'latitude_avg', 'longitude_avg'])
                log_messages.append("  - Geocodeデータが空のため、平均化スキップ")

            log_messages.append("--- データ準備完了 ---")
            progress_bar.progress(0.7, text="緯度経度の紐付け中...")

            # --- 3. データの結合 (マージ) ---
            # コードリストに postal_key がないとマージできないため、存在確認
            if 'postal_key' not in code_list_df.columns:
                 raise ValueError("コードリストの準備中にエラーが発生しました (postal_key列がありません)")
            if not geocode_avg.empty and 'postal_key' not in geocode_avg.columns:
                 raise ValueError("Geocodeデータの準備中にエラーが発生しました (postal_key列がありません)")

            merged_df = pd.merge(
                code_list_df,
                geocode_avg,
                on='postal_key',
                how='left' # コードリストを基準に結合
            )
            log_messages.append("--- データの結合完了 ---")
            progress_bar.progress(0.9, text="結果の分割中...")

            # --- 4. 結果の分割 ---
            log_messages.append("--- 結果の分割開始 ---")
            # 緯度経度が取得できたものを成功リストへ (NaNでない)
            success_condition = merged_df['latitude_avg'].notna() & merged_df['longitude_avg'].notna()
            geo_success_df = merged_df[success_condition].copy()
            geo_success_df = geo_success_df[['コード種別', 'コード', '郵便番号', 'latitude_avg', 'longitude_avg']] # 列を整理
            geo_success_df.rename(columns={'latitude_avg': '緯度', 'longitude_avg': '経度'}, inplace=True)
            log_messages.append(f"  - 成功リスト件数: {len(geo_success_df)}")

            # 緯度経度が取得できなかったものを失敗リストへ (NaN)
            geo_failed_df = merged_df[~success_condition].copy()
            # ★★★ 追加: 失敗理由カラムを追加 ★★★
            geo_failed_df['失敗理由'] = 'Geocodeデータに該当する有効な郵便番号が見つかりませんでした'
            # ★★★ 修正: 失敗リストに必要な列を再選択 ★★★
            geo_failed_df = geo_failed_df[['コード種別', 'コード', '郵便番号', '失敗理由']] # 失敗理由列を含める
            log_messages.append(f"  - 失敗リスト件数: {len(geo_failed_df)}")

            log_messages.append("--- 結果の分割完了 ---")
            progress_bar.progress(1.0, text="処理完了！")

            # 結果をセッション状態に保存
            st.session_state.geo_processing_done = True
            st.session_state.geo_success_df = geo_success_df
            st.session_state.geo_failed_df = geo_failed_df
            st.session_state.geo_log_messages = log_messages

            st.success("緯度経度付与処理が完了しました！")

        except ValueError as ve:
            st.error(f"処理を中断しました: {ve}")
            st.session_state.geo_error_message = str(ve)
            st.session_state.geo_log_messages = log_messages
            progress_bar.empty()
        except Exception as e:
            st.error(f"処理中に予期せぬエラーが発生しました: {e}")
            st.exception(e)
            st.session_state.geo_error_message = str(e)
            st.session_state.geo_log_messages = log_messages
            progress_bar.empty()

# ---- 結果表示エリア ----
if st.session_state.get('geo_button_clicked', False):
    # エラー発生時
    if st.session_state.get('geo_error_message'):
        with res_col2:
            st.error("エラーのため処理を完了できませんでした。")
            with st.expander("エラー詳細とログを表示", expanded=True):
                st.error(st.session_state.geo_error_message)
                log_messages = st.session_state.get('geo_log_messages', ["ログがありません。"])
                st.code('\n'.join(log_messages), language='text')
    # 正常完了時
    elif st.session_state.get('geo_processing_done', False):
        with res_col2:
            st.subheader("処理結果")

            # 成功リスト
            st.markdown("##### 成功リスト (緯度経度付与完了)")
            success_df = st.session_state.get('geo_success_df', pd.DataFrame())
            st.dataframe(success_df, use_container_width=True, height=300)
            if not success_df.empty:
                success_csv = success_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button("📥 成功リストCSVダウンロード", success_csv, "result_geocoded_success.csv", "text/csv")
            else:
                st.caption("成功リストは空です。")

            st.divider()

            # 失敗リスト
            st.markdown("##### 失敗リスト (緯度経度付与不可)")
            failed_df = st.session_state.get('geo_failed_df', pd.DataFrame())
            # ★★★ 表示/ダウンロードするDataFrameには失敗理由が含まれている ★★★
            st.dataframe(failed_df, use_container_width=True, height=300)
            if not failed_df.empty:
                failed_csv = failed_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button("📥 失敗リストCSVダウンロード", failed_csv, "result_geocoded_failed.csv", "text/csv")
            else:
                st.caption("失敗リストは空です。")

            # ログ
            with st.expander("処理ログを表示"):
                log_messages = st.session_state.get('geo_log_messages', ["ログがありません。"])
                st.code('\n'.join(log_messages), language='text')

# ボタンが押される前の初期状態、またはファイル未選択の場合
elif not all_files_uploaded and (st.session_state.get("code_list_uploader") is not None or st.session_state.get("geocode_uploader") is not None):
    with res_col1:
        st.warning("必要なファイルをすべてアップロードしてください。")
else:
    with res_col2:
        st.caption("ファイルを選択し、「処理実行」ボタンを押してください。")