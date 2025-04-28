import streamlit as st
import pandas as pd
import io
import numpy as np
import math

# --- ハーバーサイン関数 (変更なし) ---
def haversine(lat1, lon1, lat2, lon2):
    if pd.isna(lat1) or pd.isna(lon1) or pd.isna(lat2) or pd.isna(lon2): return np.nan
    R=6371.0; lat1_rad,lon1_rad,lat2_rad,lon2_rad = map(math.radians,[lat1,lon1,lat2,lon2])
    dlon=lon2_rad-lon1_rad; dlat=lat2_rad-lat1_rad
    a=math.sin(dlat/2)**2 + math.cos(lat1_rad)*math.cos(lat2_rad)*math.sin(dlon/2)**2
    c=2*math.atan2(math.sqrt(a),math.sqrt(1-a)); distance=R*c; return distance

# --- ヘルパー関数: 文字コード自動判別 (★★★ インデント修正 ★★★) ---
def read_csv_with_fallback(bytes_data, filename):
    last_exception = None
    encodings_to_try = ['utf-8-sig', 'cp932', 'utf-8']
    for encoding in encodings_to_try:
        try:
            bytes_data.seek(0)
            df = pd.read_csv(bytes_data, encoding=encoding, low_memory=False)
            st.write(f"    - 「{filename}」を {encoding} で読み込み成功。")
            return df
        except UnicodeDecodeError as e:
            last_exception = e
            st.write(f"    - 「{filename}」: {encoding} での読み込み失敗。")
        except Exception as e: # ★★★ ここの except ブロック ★★★
            last_exception = e # ★★★ この行がインデントされているか確認 ★★★
            st.write(f"    - 「{filename}」: {encoding} で予期せぬエラー ({type(e).__name__})。") # ★★★ この行も ★★★
    # すべてのエンコーディングで失敗した場合
    st.error(f"ファイル「{filename}」の読み込みに失敗しました。エラー: {last_exception}")
    raise ValueError(f"文字コード判別不能 ({filename})") from last_exception

# --- Streamlit アプリ本体 ---
st.set_page_config(page_title="CO2排出量計算", layout="wide")
st.title("🚚 CO2排出量計算ツール")
st.write("""
販売実績明細CSV（複数可）と、緯度経度が付与されたコードリストCSVをアップロードしてください。
距離とCO2排出量（トラック輸送前提）を計算し、距離600km以下の結果と600km超の結果（異常値の可能性）を別々に出力します。
処理前後のデータ件数も表示し、整合性を確認できます。
""")

# --- CO2排出係数設定 ---
st.sidebar.markdown("### 計算設定")
co2_factor = st.sidebar.number_input(
    "CO2排出係数 (g-CO2 / トンキロ)", value=230.0, step=0.1, format="%.1f",
    help="トラック輸送を想定した、1トンキロあたりのCO2排出量(グラム)。"
)

# --- ファイルアップロードセクション ---
st.header("1. ファイルのアップロード")
col1, col2 = st.columns(2)
with col1:
    uploaded_sales_files = st.file_uploader(
        "販売実績明細CSV (最大12個)", type='csv', accept_multiple_files=True, key="sales_uploader_co2"
    )
    if uploaded_sales_files:
        if len(uploaded_sales_files) > 12: st.error(f"最大12個までです。({len(uploaded_sales_files)} 個選択中)")
        else: st.success(f"{len(uploaded_sales_files)} 個 受付完了")
with col2:
    uploaded_geocoded_list_file = st.file_uploader(
        "緯度経度付きコードリスト CSV", type='csv', key="geocoded_list_uploader"
    )
    if uploaded_geocoded_list_file: st.success("緯度経度リスト 受付完了")

# --- 処理実行セクション ---
st.header("2. 処理実行と結果")
all_files_uploaded = (
    uploaded_sales_files and 0 < len(uploaded_sales_files) <= 12 and uploaded_geocoded_list_file
)
res_col1, res_col2 = st.columns([1, 4])

with res_col1:
    if st.button("処理実行", disabled=not all_files_uploaded, use_container_width=True):
        # セッション状態リセット
        st.session_state.co2_processing_done = False
        st.session_state.co2_input_count = 0
        st.session_state.co2_normal_result_df = None
        st.session_state.co2_normal_count = 0
        st.session_state.co2_anomaly_result_df = None
        st.session_state.co2_anomaly_count = 0
        st.session_state.co2_error_message = None
        st.session_state.co2_log_messages = []
        st.session_state.co2_button_clicked = True

        st.info("CO2排出量計算処理を開始します...")
        progress_bar = st.progress(0, text="ファイル読み込み中...")
        log_messages = ["**処理ログ:**"]

        try:
            # --- 1. ファイル読み込み ---
            log_messages.append("--- ファイル読み込み開始 ---")
            files_read_count = 0
            total_files_to_read = len(uploaded_sales_files) + 1
            sales_dfs = []
            required_sales_cols = ['仕入先コード', '荷受人コード', '分析用単位数量']
            log_messages.append("--- 販売実績ファイルの読み込み ---")
            for i, uploaded_file in enumerate(uploaded_sales_files):
                bytes_data = io.BytesIO(uploaded_file.getvalue())
                filename = uploaded_file.name
                log_messages.append(f"  - 読み込み試行: {filename}")
                df = read_csv_with_fallback(bytes_data, filename)
                sales_dfs.append(df)
                files_read_count += 1
                progress_bar.progress(files_read_count / total_files_to_read, text=f"読み込み中: {filename}")
                log_messages.append(f"    -> 読み込み完了 ({filename})")
            if not sales_dfs: raise ValueError("読み込み可能な販売実績ファイルがありませんでした。")
            sales_data_raw = pd.concat(sales_dfs, ignore_index=True)
            input_row_count = len(sales_data_raw)
            st.session_state.co2_input_count = input_row_count
            log_messages.append(f"--- 販売実績データの結合完了 (合計: {input_row_count} 件) ---")

            required_geocoded_cols = ['コード種別', 'コード', '緯度', '経度']
            geocoded_list_bytes = io.BytesIO(uploaded_geocoded_list_file.getvalue())
            geocoded_list_filename = uploaded_geocoded_list_file.name
            log_messages.append(f"--- 緯度経度リストの読み込み ({geocoded_list_filename}) ---")
            geocoded_list_df = read_csv_with_fallback(geocoded_list_bytes, geocoded_list_filename)
            if not all(col in geocoded_list_df.columns for col in required_geocoded_cols):
                 raise ValueError(f"緯度経度リストに必要な列 ({', '.join(required_geocoded_cols)}) が見つかりません。")
            files_read_count += 1
            progress_bar.progress(files_read_count / total_files_to_read, text=f"読み込み中: {geocoded_list_filename}")
            log_messages.append(f"    -> 読み込み完了 ({geocoded_list_filename})")
            progress_bar.progress(1.0, text="全ファイル読み込み完了！")

            # --- 2. データ準備 ---
            log_messages.append("--- データ準備開始 ---")
            progress_bar.progress(0.1, text="データ準備中...")
            sales_data = sales_data_raw.copy()
            if not all(col in sales_data.columns for col in required_sales_cols):
                 missing_cols = [col for col in required_sales_cols if col not in sales_data.columns]
                 raise ValueError(f"結合後の販売実績データに必要な列 ({', '.join(missing_cols)}) が見つかりません。")
            sales_data['仕入先コード'] = sales_data['仕入先コード'].astype(str).str.strip()
            sales_data['荷受人コード'] = sales_data['荷受人コード'].astype(str).str.strip()
            sales_data['分析用単位数量_トン'] = pd.to_numeric(sales_data['分析用単位数量'], errors='coerce').fillna(0)
            log_messages.append("  - 販売実績データの準備完了")
            geo_list = geocoded_list_df[required_geocoded_cols].copy()
            geo_list['コード'] = geo_list['コード'].astype(str).str.strip()
            geo_list['緯度'] = pd.to_numeric(geo_list['緯度'], errors='coerce')
            geo_list['経度'] = pd.to_numeric(geo_list['経度'], errors='coerce')
            geo_list = geo_list.dropna(subset=['緯度', '経度'])
            geo_supplier = geo_list[geo_list['コード種別'] == '仕入先'].drop_duplicates(subset=['コード'], keep='first')
            geo_consignee = geo_list[geo_list['コード種別'] == '荷受人'].drop_duplicates(subset=['コード'], keep='first')
            log_messages.append(f"  - 緯度経度リスト準備完了 (仕入先: {len(geo_supplier)}件, 荷受人: {len(geo_consignee)}件)")
            log_messages.append("--- データ準備完了 ---")
            progress_bar.progress(0.3, text="緯度経度の紐付け中...")

            # --- 3. 緯度経度の付与 (マージ) ---
            merged_data = pd.merge(sales_data, geo_supplier[['コード', '緯度', '経度']], left_on='仕入先コード', right_on='コード', how='left', suffixes=('', '_仕入先'))
            merged_data.rename(columns={'緯度': '仕入先_緯度', '経度': '仕入先_経度'}, inplace=True)
            merged_data.drop(columns=['コード'], inplace=True, errors='ignore') # errors='ignore' を追加
            merged_data = pd.merge(merged_data, geo_consignee[['コード', '緯度', '経度']], left_on='荷受人コード', right_on='コード', how='left', suffixes=('', '_荷受人'))
            merged_data.rename(columns={'緯度': '荷受人_緯度', '経度': '荷受人_経度'}, inplace=True)
            merged_data.drop(columns=['コード'], inplace=True, errors='ignore') # errors='ignore' を追加
            log_messages.append("--- 緯度経度の紐付け完了 ---")
            progress_bar.progress(0.6, text="距離計算中...")

            # --- 4. 距離計算 ---
            log_messages.append("--- 距離計算開始 (ハーバーサイン法) ---")
            distances = merged_data.apply(lambda row: haversine(row.get('仕入先_緯度'), row.get('仕入先_経度'), row.get('荷受人_緯度'), row.get('荷受人_経度')), axis=1) # .get() を使用
            merged_data['距離_km'] = distances.fillna(0)
            log_messages.append("--- 距離計算完了 ---")
            progress_bar.progress(0.8, text="CO2排出量計算中...")

            # --- 5. CO2排出量計算 ---
            log_messages.append(f"--- CO2排出量計算開始 (係数: {co2_factor} g/トンキロ) ---")
            merged_data['CO2排出量_g'] = merged_data['距離_km'] * merged_data['分析用単位数量_トン'] * co2_factor
            log_messages.append("--- CO2排出量計算完了 ---")

            # --- 6. 結果の整理と分割 ---
            log_messages.append("--- 結果の整理と分割開始 ---")
            progress_bar.progress(0.9, text="結果整理中...")
            merged_data['距離_km'] = merged_data['距離_km'].round(5)
            merged_data['CO2排出量_g'] = merged_data['CO2排出量_g'].round(5)
            log_messages.append("  - 距離とCO2排出量を小数点以下5桁に丸めました。")
            original_cols = list(sales_data_raw.columns)
            added_cols = ['仕入先_緯度', '仕入先_経度', '荷受人_緯度', '荷受人_経度', '距離_km', 'CO2排出量_g']
            final_cols_exist = [col for col in original_cols + added_cols if col in merged_data.columns]
            result_df_all = merged_data[final_cols_exist].copy()
            normal_result_df = result_df_all[result_df_all['距離_km'] <= 600].copy()
            anomaly_result_df = result_df_all[result_df_all['距離_km'] > 600].copy()
            normal_row_count = len(normal_result_df)
            anomaly_row_count = len(anomaly_result_df)
            st.session_state.co2_normal_count = normal_row_count
            st.session_state.co2_anomaly_count = anomaly_row_count
            log_messages.append(f"  - 結果を分割しました (正常: {normal_row_count}件, 異常値疑い: {anomaly_row_count}件)。")
            st.session_state.co2_processing_done = True
            st.session_state.co2_normal_result_df = normal_result_df
            st.session_state.co2_anomaly_result_df = anomaly_result_df
            st.session_state.co2_log_messages = log_messages
            progress_bar.progress(1.0, text="処理完了！")
            st.success("CO2排出量計算が完了しました！")

        except ValueError as ve:
            st.error(f"処理を中断しました: {ve}")
            st.session_state.co2_error_message = str(ve)
            st.session_state.co2_log_messages = log_messages
            progress_bar.empty()
        except Exception as e:
            st.error(f"処理中に予期せぬエラーが発生しました: {e}")
            st.exception(e) # トレースバックも表示
            st.session_state.co2_error_message = str(e)
            st.session_state.co2_log_messages = log_messages
            progress_bar.empty()


# ---- 結果表示エリア ----
if st.session_state.get('co2_button_clicked', False):
    if st.session_state.get('co2_error_message'):
        with res_col2:
            st.error("エラーのため処理を完了できませんでした。")
            with st.expander("エラー詳細とログを表示", expanded=True):
                st.error(st.session_state.co2_error_message)
                log_messages = st.session_state.get('co2_log_messages', ["ログがありません。"])
                st.code('\n'.join(log_messages), language='text')
    elif st.session_state.get('co2_processing_done', False):
        with res_col2:
            st.subheader("処理結果概要")
            input_count = st.session_state.get('co2_input_count', 0)
            normal_count = st.session_state.get('co2_normal_count', 0)
            anomaly_count = st.session_state.get('co2_anomaly_count', 0)
            total_output_count = normal_count + anomaly_count
            count_col1, count_col2, count_col3, count_col4 = st.columns(4)
            with count_col1: st.metric("入力販売実績 件数", f"{input_count:,}")
            with count_col2: st.metric("正常結果 件数 (<=600km)", f"{normal_count:,}")
            with count_col3: st.metric("異常値疑い 件数 (>600km)", f"{anomaly_count:,}")
            with count_col4: st.metric("出力合計 件数", f"{total_output_count:,}", delta=f"{total_output_count - input_count:,}", delta_color="off" if total_output_count == input_count else "inverse")
            if input_count == total_output_count: st.success("✅ 入力件数と出力合計件数が一致しました。")
            else: st.warning("⚠️ 入力件数と出力合計件数が一致しません。処理ログを確認してください。")
            st.divider()
            st.markdown("##### 計算結果 (距離 <= 600km)")
            normal_df = st.session_state.get('co2_normal_result_df', pd.DataFrame())
            st.dataframe(normal_df, use_container_width=True, height=300)
            if not normal_df.empty:
                if uploaded_sales_files: base_filename = uploaded_sales_files[0].name.split('.')[0]; download_filename_normal = f"{base_filename}_co2_result_normal.csv"
                else: download_filename_normal = "co2_result_normal.csv"
                normal_csv = normal_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button("📥 正常結果をCSVでダウンロード (<= 600km)", normal_csv, download_filename_normal, "text/csv")
            else: st.caption("正常結果 (距離 <= 600km) はありません。")
            st.divider()
            st.markdown("##### 計算結果 (距離 > 600km) - 異常値の可能性")
            anomaly_df = st.session_state.get('co2_anomaly_result_df', pd.DataFrame())
            st.dataframe(anomaly_df, use_container_width=True, height=200)
            if not anomaly_df.empty:
                if uploaded_sales_files: base_filename = uploaded_sales_files[0].name.split('.')[0]; download_filename_anomaly = f"{base_filename}_co2_result_anomaly.csv"
                else: download_filename_anomaly = "co2_result_anomaly.csv"
                anomaly_csv = anomaly_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                st.download_button("📥 異常値疑い結果をCSVでダウンロード (> 600km)", anomaly_csv, download_filename_anomaly, "text/csv")
            else: st.caption("異常値疑い結果 (距離 > 600km) はありません。")
            with st.expander("処理ログを表示"):
                log_messages = st.session_state.get('co2_log_messages', ["ログがありません。"])
                st.code('\n'.join(log_messages), language='text')
elif not all_files_uploaded and (st.session_state.get("sales_uploader_co2") is not None or st.session_state.get("geocoded_list_uploader") is not None):
     with res_col1: st.warning("必要なファイルをすべてアップロードしてください。")
else:
     with res_col2: st.caption("ファイルを選択し、「処理実行」ボタンを押してください。")